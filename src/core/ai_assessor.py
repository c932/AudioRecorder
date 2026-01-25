import os
import json
import string
try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None

class PronunciationCoach:
    def __init__(self):
        self.load_config()
        
    def load_config(self):
        self.config = {}
        self.speech_key = os.getenv("SPEECH_KEY")
        self.speech_region = os.getenv("SPEECH_REGION")
        
        # Try Loading from config.json
        # Load from correct user data path
        from src.utils import get_user_data_path
        config_path = get_user_data_path("config.json")
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    self.config = json.load(f)
                    if self.config.get("azure_key"):
                        self.speech_key = self.config.get("azure_key")
                    if self.config.get("azure_region"):
                        self.speech_region = self.config.get("azure_region")
            except:
                pass
        
        self.use_dummy = (not self.speech_key or not self.speech_region or speechsdk is None)

    def assess(self, audio_file, reference_text):
        """
        Returns a dict: {'accuracy_score': int, 'fluency_score': int, 'completeness_score': int, 'feedback': str}
        """
        provider = self.config.get("ai_provider", "")
        
        if provider.startswith("Azure"):
            return self._assess_azure(audio_file, reference_text)
        elif "OpenAI" in provider or "Ollama" in provider:
            return self._assess_hybrid(audio_file, reference_text)
        else:
            # Fallback logic
            if self.speech_key and speechsdk: 
                 return self._assess_azure(audio_file, reference_text)
            return self._dummy_assess(reference_text)

    def _assess_azure(self, audio_file, reference_text):
        if not speechsdk:
            return {"accuracy_score": 0, "feedback": "Azure SDK 未安装。"}
            
        try:
            speech_config = speechsdk.SpeechConfig(subscription=self.speech_key, region=self.speech_region)
            audio_config = speechsdk.audio.AudioConfig(filename=audio_file)
            
            pronunciation_config = speechsdk.PronunciationAssessmentConfig(
                reference_text=reference_text,
                grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
                granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
                enable_miscue=True
            )
            
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config, 
                audio_config=audio_config
            )
            pronunciation_config.apply_to(speech_recognizer)
            
            result = speech_recognizer.recognize_once()
            
            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                pronunciation_result = speechsdk.PronunciationAssessmentResult(result)
                score = pronunciation_result.accuracy_score
                
                # Feedback Logic based on score
                feedback = "发音很棒！继续保持！"
                if score < 60:
                    feedback = "声音有点小，或者发音不太清晰，试着大声一点？"
                elif score < 80:
                    feedback = "发音还可以，但有些音节不够饱满，请听听标准发音。"
                elif score < 90:
                    feedback = "非常接近了！注意语调和连读会更完美。"
                    
                return {
                    "accuracy_score": score,
                    "fluency_score": pronunciation_result.fluency_score,
                    "completeness_score": pronunciation_result.completeness_score,
                    "feedback": feedback
                }
            elif result.reason == speechsdk.ResultReason.NoMatch:
                return {"accuracy_score": 0, "feedback": "没有检测到语音，请大声一点。"}
            else:
                return {"accuracy_score": 0, "feedback": "无法识别，请再试一次。"}
                
        except Exception as e:
            print(f"Azure Error: {e}")
            return {"accuracy_score": 0, "feedback": f"AI 服务错误: {str(e)}"}

    def warmup(self):
        """Pre-loads the model if Whisper is selected as provider."""
        stt_provider = self.config.get("stt_provider", "Google")
        if "Whisper" in stt_provider:
             print("[AIAssessor] Warming up Whisper model...")
             try:
                 self._ensure_whisper_loaded()
                 
                 # Run dummy inference to wake up JIT/CUDA
                 import numpy as np
                 print("[AIAssessor] Running dummy inference...")
                 dummy_audio = np.zeros(16000, dtype=np.float32) 
                 self.whisper_model.transcribe(dummy_audio, fp16=False)
                 
                 print("[AIAssessor] Whisper model ready.")
             except Exception as e:
                 print(f"[AIAssessor] Warmup failed: {e}")

    def _ensure_whisper_loaded(self):
        if not hasattr(self, 'whisper_model') or self.whisper_model is None:
            import whisper
            import torch
            
            print("Loading Whisper Model (small)...")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"Whisper Device: {device}")
            self.whisper_model = whisper.load_model("small", device=device)

    def _assess_hybrid(self, audio_file, reference_text):
        """
        1. STT: Google Web Speech OR Local Whisper
        2. Score: Levenshtein + Confidence Penalty
        3. Feedback: LLM (Context-Aware)
        """
        import Levenshtein
        from openai import OpenAI
        
        stt_provider = self.config.get("stt_provider", "Google")
        recognized_text = ""
        confidence = 1.0
        candidates = []
        
        # --- STT SECTION ---
        if "Whisper" in stt_provider:
            # Local Whisper
            try:
                self._ensure_whisper_loaded()
                    
                # Force English and add prompt to help with context
                result = self.whisper_model.transcribe(
                    audio_file, 
                    fp16=False, 
                    language="en",
                    initial_prompt=f"The word is {reference_text}. Pronunciation assessment."
                ) 
                recognized_text = result["text"].strip()
                
                # Estimate confidence from segments
                # Whisper gives logprob. e^logprob = prob
                avg_logprob = -1.0 # Default if empty
                if result.get("segments"):
                   avg_logprob = result["segments"][0].get("avg_logprob", -1.0)
                
                import math
                confidence = math.exp(avg_logprob)
                
                # Remove trailing punctuation for cleaner comparison
                import string
                recognized_text = recognized_text.translate(str.maketrans('', '', string.punctuation))
                
                print(f"Whisper: {recognized_text} (Conf: {confidence:.2f})")
                
            except ImportError as e:
                 print(f"Whisper Import Error: {e}")
                 return {"accuracy_score": 0, "feedback": f"Whisper 缺失依赖: {e}"}
            except Exception as e:
                 print(f"Whisper Error: {e}")
                 # Fallback?
                 return {"accuracy_score": 0, "feedback": f"Whisper 识别出错: {e}"}
        
        else:
            # Google Web Speech (Free & Simple)
            import speech_recognition as sr
            r = sr.Recognizer()
            try:
                with sr.AudioFile(audio_file) as source:
                    audio_data = r.record(source)
                    payload = r.recognize_google(audio_data, show_all=True)
                    
                    if not payload:
                         return {"accuracy_score": 0, "feedback": "没有检测到清晰的语音。"}
                         
                    alts = payload.get('alternative', [])
                    if not alts:
                         return {"accuracy_score": 0, "feedback": "无法识别。"}
                         
                    for item in alts:
                        candidates.append(item.get('transcript', ''))
                    
                    top_transcript = alts[0].get('transcript', '')
                    top_confidence = alts[0].get('confidence', 0.8)
                    
                    recognized_text = top_transcript
                    confidence = top_confidence
            except Exception as e:
                print(f"Google STT Error: {e}")
                return {"accuracy_score": 0, "feedback": "语音识别服务连接失败。"}

        # --- SCORE SECTION ---
        # Base Similarity
        def normalize(text):
            return text.translate(str.maketrans('', '', string.punctuation)).lower().strip()

        similarity = Levenshtein.ratio(normalize(reference_text), normalize(recognized_text))
        score = int(similarity * 100)
        
        # Scoring Optimization (Configurable)
        threshold = self.config.get("scoring_threshold", 0.80) 
        penalty_factor = self.config.get("scoring_penalty", 100 if "Whisper" in stt_provider else 60)
        enable_cap = self.config.get("scoring_strict_cap", True)
        
        penalty_log = 0.0
        
        if score > 80:
             if confidence < threshold:
                 penalty = (threshold - confidence) * penalty_factor
                 penalty = min(40, max(0, penalty)) # Cap penalty
                 score = max(0, int(score - penalty))
                 penalty_log = penalty
                 print(f"Confidence Penalty applied: -{penalty:.1f}")
                 
             # CRITICAL CAP
             if enable_cap and score > 90 and confidence < threshold: 
                 print(f"Quality Cap applied: Score {score} -> 88 (Conf {confidence:.2f} too low)")
                 score = 88
                 
             # Hard Cap only for Very Low Confidence
             if confidence < 0.4 and score > 85:
                 score = 85 
                 
        # --- FEEDBACK GENERATION ---
        # 1. Default Rule-Based Feedback (Fallback)
        if score >= 90:
            feedback = "发音很标准！非常棒！"
        elif score >= 80:
            feedback = "发音不错，但还有提升空间。注意元音的饱满度。"
        elif score >= 60:
            feedback = "读音基本准确，但声音太小或不够自信。请大声朗读！"
        else:
            feedback = "听不太清，或者发音偏差较大。请仔细听示范音，再试一次。"

        # 2. Specific feedback for the Quality Cap case
        if score == 88 and confidence < threshold and similarity > 0.95:
            feedback = "读音准确，但不够自信。想拿 90+ 需要更大声、更清晰！"

        # 3. LLM Enhancement (Only if configured)
        provider = self.config.get("ai_provider", "")
        has_llm = provider and ("Ollama" in provider or "OpenAI" in provider)
        
        if score < 100 and has_llm:
            provider = self.config.get("ai_provider", "")
            base_url = self.config.get("ollama_base") if "Ollama" in provider else self.config.get("openai_base")
            api_key = "ollama" if "Ollama" in provider else self.config.get("openai_key")
            model = self.config.get("ollama_model") if "Ollama" in provider else self.config.get("openai_model")
            
            try:
                client = OpenAI(base_url=base_url, api_key=api_key)
                
                # Use candidates if google, or just single text if Whisper (Whisper returns segments, not easy N-best without beam search hacking)
                context_str = str(candidates) if candidates else f"'{recognized_text}'"
                
                prompt = f"""
                我是少儿英语老师。
                目标单词/句子: "{reference_text}"
                学生读成: {context_str}
                置信度: {confidence:.2f}
                最终评分: {score}
                
                请判断学生的具体发音问题（如元音不饱满、辅音丢失、读错词等）。
                用中文给出一句简短的鼓励性纠音建议（30字以内）。
                """
                
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=150
                )
                llm_feedback = response.choices[0].message.content.strip()
                if llm_feedback:
                    feedback = llm_feedback
            except Exception as e:
                print(f"LLM Error (Using Fallback): {e}")
                # Do NOT overwrite 'feedback' with an error message. 
                # Keep the rule-based feedback.
        
        return {
            "accuracy_score": score,
            "fluency_score": score, 
            "completeness_score": score,
            "feedback": feedback,
            "details": {
                "confidence": confidence,
                "similarity": similarity,
                "penalty": penalty_log,
                "recognized": recognized_text,
                "threshold": threshold,
                "raw_score": int(similarity * 100),
                "capped": (score == 88 and enable_cap)
            }
        }

    def _dummy_assess(self, reference_text):
        import random
        # Simulate a score
        score = random.randint(50, 100)
        
        # Generate fake specific feedback
        feedbacks = [
            "注意元音的发音要饱满。",
            "试着模仿标准发音的语调。",
            "你的语速适中，继续加油！",
            "注意单词结尾的辅音不要吞掉。",
            "很好的尝试，再来一次会更好！", 
            "这个单词中间的音节有点模糊。"
        ]
        
        feedback = "完美！"
        if score < 90:
            feedback = random.choice(feedbacks)
            
        print("Using Dummy AI Assessor (No Azure Keys found)")
        return {
            "accuracy_score": score,
            "fluency_score": random.randint(60, 100),
            "completeness_score": random.randint(80, 100),
            "feedback": feedback
        }
