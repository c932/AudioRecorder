import os
import json
import string
import math
import sys
import re
import threading

# Ensure ffmpeg is in PATH for Whisper
def _setup_ffmpeg_path():
    """Add bundled ffmpeg to PATH if it exists."""
    # Try to find ffmpeg in bin folder (relative to project root)
    possible_paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bin"),  # dev: project_root/bin
    ]

    # For PyInstaller frozen app
    if getattr(sys, 'frozen', False):
        possible_paths.insert(0, os.path.join(os.path.dirname(sys.executable), "bin"))

    for bin_path in possible_paths:
        ffmpeg_exe = os.path.join(bin_path, "ffmpeg.exe")
        if os.path.exists(ffmpeg_exe):
            # Add to PATH if not already there
            if bin_path not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bin_path + os.pathsep + os.environ.get("PATH", "")
                print(f"[AIAssessor] Added ffmpeg to PATH: {bin_path}")
            return True
    return False

_setup_ffmpeg_path()

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None

from PyQt6.QtCore import QObject, pyqtSignal


class AssessorSignals(QObject):
    """Signals for async LLM feedback generation."""
    feedback_ready = pyqtSignal(str, str)   # (reference_word, llm_feedback_text)
    feedback_error = pyqtSignal(str)         # error message


class PronunciationCoach:
    def __init__(self):
        self.signals = AssessorSignals()
        self._current_reference = ""  # Track current word for async feedback race condition
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
            except (json.JSONDecodeError, IOError) as e:
                print(f"[AIAssessor] Error loading config: {e}")
                pass
        
        self.use_dummy = (not self.speech_key or not self.speech_region or speechsdk is None)

    # ------------------------------------------------------------------ #
    #  Unified LLM Client                                                 #
    # ------------------------------------------------------------------ #
    def _get_llm_client(self):
        """
        Returns (OpenAI_client, model_name) based on current provider config.
        Returns (None, None) if no valid LLM provider is configured.
        """
        from openai import OpenAI
        
        provider = self.config.get("ai_provider", "")
        
        if "Custom" in provider:
            base_url = self.config.get("custom_base", "http://localhost:8080/v1")
            api_key = self.config.get("custom_key") or "not-needed"
            model = self.config.get("custom_model", "")
            if not model:
                return None, None
            return OpenAI(base_url=base_url, api_key=api_key), model
            
        elif "Ollama" in provider:
            base_url = self.config.get("ollama_base", "http://localhost:11434/v1")
            api_key = "ollama"
            model = self.config.get("ollama_model", "qwen2.5")
            return OpenAI(base_url=base_url, api_key=api_key), model
            
        elif "OpenAI" in provider:
            base_url = self.config.get("openai_base", "https://api.openai.com/v1")
            api_key = self.config.get("openai_key", "")
            model = self.config.get("openai_model", "gpt-4o")
            if not api_key:
                return None, None
            return OpenAI(base_url=base_url, api_key=api_key), model
            
        return None, None

    def _has_llm(self):
        """Check if any LLM provider is configured."""
        provider = self.config.get("ai_provider", "")
        return bool(provider and (
            "Ollama" in provider or "OpenAI" in provider or "Custom" in provider
        ))

    # ------------------------------------------------------------------ #
    #  Assess (Main Entry Point)                                          #
    # ------------------------------------------------------------------ #
    def assess(self, audio_file, reference_text):
        """
        Returns a dict: {'accuracy_score': int, 'fluency_score': int, 'completeness_score': int, 'feedback': str}
        This method is synchronous and returns quickly with rule-based feedback.
        Use generate_feedback_async() for LLM-enhanced feedback.
        """
        provider = self.config.get("ai_provider", "")
        
        if provider.startswith("Azure"):
            return self._assess_azure(audio_file, reference_text)
        elif "OpenAI" in provider or "Ollama" in provider or "Custom" in provider:
            return self._assess_hybrid(audio_file, reference_text)
        else:
            # Fallback logic
            if self.speech_key and speechsdk: 
                 return self._assess_azure(audio_file, reference_text)
            return self._dummy_assess(reference_text)

    def generate_feedback_async(self, score, confidence, reference_text, recognized_text, candidates=None):
        """
        Generate LLM feedback asynchronously in a background thread.
        Emits signals.feedback_ready(reference_text, feedback_text) on success.
        """
        if score >= 100:
            return  # Perfect score, no need LLM feedback
        
        if not self._has_llm():
            return  # No LLM configured
        
        self._current_reference = reference_text
        
        t = threading.Thread(
            target=self._generate_feedback_worker,
            args=(score, confidence, reference_text, recognized_text, candidates or []),
            daemon=True
        )
        t.start()

    def _generate_feedback_worker(self, score, confidence, reference_text, recognized_text, candidates):
        """Background worker for LLM feedback generation."""
        client, model = self._get_llm_client()
        if not client:
            return
        
        try:
            context_str = str(candidates) if candidates else f"'{recognized_text}'"
            
            prompt = f"""我是少儿英语老师。
目标单词/句子: "{reference_text}"
学生读成: {context_str}
置信度: {confidence:.2f}
最终评分: {score}

请判断学生的具体发音问题（如元音不饱满、辅音丢失、读错词等）。
用中文给出一句简短的鼓励性纠音建议（30字以内）。"""
            
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150
            )
            llm_feedback = response.choices[0].message.content.strip()
            if llm_feedback:
                # Only emit if the reference word hasn't changed (avoid race condition)
                if self._current_reference == reference_text:
                    self.signals.feedback_ready.emit(reference_text, llm_feedback)
        except Exception as e:
            print(f"LLM Async Error: {e}")
            # Silently fail - rule-based feedback is already displayed

    # ------------------------------------------------------------------ #
    #  Azure Assessment                                                   #
    # ------------------------------------------------------------------ #
    def _assess_azure(self, audio_file, reference_text):
        if not speechsdk:
            return {"accuracy_score": 0, "fluency_score": 0, "completeness_score": 0, "feedback": "Azure SDK 未安装。"}

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
                return {"accuracy_score": 0, "fluency_score": 0, "completeness_score": 0, "feedback": "没有检测到语音，请大声一点。"}
            else:
                return {"accuracy_score": 0, "fluency_score": 0, "completeness_score": 0, "feedback": "无法识别，请再试一次。"}

        except Exception as e:
            print(f"Azure Error: {e}")
            return {"accuracy_score": 0, "fluency_score": 0, "completeness_score": 0, "feedback": f"AI 服务错误: {str(e)}"}

    # ------------------------------------------------------------------ #
    #  Whisper Model Loading (with faster-whisper support)                #
    # ------------------------------------------------------------------ #
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
                 
                 if self.use_faster_whisper:
                     # faster-whisper API: transcribe returns (segments_generator, info)
                     segments, info = self.faster_model.transcribe(dummy_audio, language="en")
                     list(segments)  # Consume generator
                 else:
                     self.whisper_model.transcribe(dummy_audio, fp16=False)
                 
                 print("[AIAssessor] Whisper model ready.")
             except Exception as e:
                 print(f"[AIAssessor] Warmup failed: {e}")

    def _ensure_whisper_loaded(self):
        """Load Whisper model, preferring faster-whisper if available."""
        already_loaded = (
            (hasattr(self, 'whisper_model') and self.whisper_model is not None) or
            (hasattr(self, 'faster_model') and self.faster_model is not None)
        )
        if already_loaded:
            return
        
        # Initialize flags
        self.use_faster_whisper = False
        self.whisper_model = None
        self.faster_model = None
        
        # Try faster-whisper first (CTranslate2 backend, ~4x faster)
        try:
            from faster_whisper import WhisperModel
            import torch
            
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
                print(f"[Whisper] ✅ GPU Detected: {gpu_name} ({gpu_mem:.1f} GB)")
                print("[Whisper] Loading faster-whisper (CTranslate2, GPU)...")
                self.faster_model = WhisperModel("small", device="cuda", compute_type="float16")
            else:
                print("[Whisper] No CUDA GPU, loading faster-whisper (CPU)...")
                self.faster_model = WhisperModel("small", device="cpu", compute_type="int8")
            
            self.use_faster_whisper = True
            print("[Whisper] faster-whisper loaded successfully (4x faster)")
            return
            
        except ImportError:
            print("[Whisper] faster-whisper not installed, falling back to openai-whisper")
            print("[Whisper]   To install: pip install faster-whisper")
        except Exception as e:
            print(f"[Whisper] faster-whisper failed ({e}), falling back to openai-whisper")
        
        # Fallback to original openai-whisper
        import whisper
        import torch
        
        print("[Whisper] Loading Whisper Model (small)...")
        print(f"[Whisper] PyTorch version: {torch.__version__}")
        print(f"[Whisper] CUDA available: {torch.cuda.is_available()}")

        if torch.cuda.is_available():
            device = "cuda"
            gpu_name = torch.cuda.get_device_name(0)
            gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
            print(f"[Whisper] ✅ GPU Detected: {gpu_name} ({gpu_mem:.1f} GB)")
        else:
            device = "cpu"
            print("[Whisper] ⚠️ No CUDA GPU detected, using CPU (slower)")

        self.whisper_model = whisper.load_model("small", device=device)
        print(f"[Whisper] Model loaded on: {device.upper()}")

    # ------------------------------------------------------------------ #
    #  Improved Scoring Functions                                         #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize(text):
        """Normalize text for comparison: lowercase, strip punctuation."""
        return text.translate(str.maketrans('', '', string.punctuation)).lower().strip()

    @staticmethod
    def _weighted_edit_score(ref_text, hyp_text):
        """
        Calculate weighted edit distance score.
        More nuanced than Levenshtein.ratio():
        - Substitution: 1.0 penalty (reduced for phonetically similar pairs)
        - Insertion: 0.8 penalty (extra sounds, lighter)
        - Deletion: 1.2 penalty (missing sounds, heavier)
        """
        import Levenshtein
        
        ref_norm = PronunciationCoach._normalize(ref_text)
        hyp_norm = PronunciationCoach._normalize(hyp_text)
        
        if not ref_norm:
            return 0.0, []
        
        # Phonetic similarity map: common L2 English pronunciation errors
        PHONETIC_SIMILAR = {
            ('th', 'f'): 0.5, ('th', 'd'): 0.5,
            ('f', 'th'): 0.5, ('d', 'th'): 0.5,
            ('r', 'l'): 0.5, ('l', 'r'): 0.5,
            ('v', 'w'): 0.5, ('w', 'v'): 0.5,
            ('b', 'p'): 0.3, ('p', 'b'): 0.3,
            ('d', 't'): 0.3, ('t', 'd'): 0.3,
            ('g', 'k'): 0.3, ('k', 'g'): 0.3,
            ('s', 'z'): 0.3, ('z', 's'): 0.3,
            ('f', 'v'): 0.3, ('v', 'f'): 0.3,
        }
        
        PENALTY_SUB = 1.0
        PENALTY_INS = 0.8
        PENALTY_DEL = 1.2
        
        ops = Levenshtein.editops(ref_norm, hyp_norm)
        
        total_cost = 0.0
        max_len = max(len(ref_norm), len(hyp_norm), 1)
        
        for op_type, src_idx, dest_idx in ops:
            if op_type == 'replace':
                ref_char = ref_norm[src_idx]
                hyp_char = hyp_norm[dest_idx]
                pair = (ref_char, hyp_char)
                if pair in PHONETIC_SIMILAR:
                    total_cost += PENALTY_SUB * PHONETIC_SIMILAR[pair]
                else:
                    total_cost += PENALTY_SUB
            elif op_type == 'insert':
                total_cost += PENALTY_INS
            elif op_type == 'delete':
                total_cost += PENALTY_DEL
        
        similarity = max(0.0, 1.0 - (total_cost / max_len))
        return similarity, ops

    @staticmethod
    def _sentence_score(ref_text, hyp_text):
        """
        Word-level alignment scoring for multi-word utterances.
        Uses SequenceMatcher for word alignment + character-level scoring.
        """
        import Levenshtein
        from difflib import SequenceMatcher
        
        ref_norm = PronunciationCoach._normalize(ref_text)
        hyp_norm = PronunciationCoach._normalize(hyp_text)
        
        ref_words = ref_norm.split()
        hyp_words = hyp_norm.split()
        
        if not ref_words:
            return 0.0, []
        
        # Single word: use character-level weighted scoring
        if len(ref_words) == 1:
            sim, _ = PronunciationCoach._weighted_edit_score(ref_text, hyp_text)
            return sim, [sim]
        
        # Multi-word: word-level alignment
        matcher = SequenceMatcher(None, ref_words, hyp_words)
        word_scores = []
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                word_scores.extend([1.0] * (i2 - i1))
            elif tag == 'replace':
                # Score each replaced word pair
                for k in range(max(i2 - i1, j2 - j1)):
                    ref_w = ref_words[min(i1 + k, i2 - 1)] if i1 + k < i2 else ""
                    hyp_w = hyp_words[min(j1 + k, j2 - j1 + j1 - 1)] if j1 + k < j2 else ""
                    if ref_w and hyp_w:
                        w_score = Levenshtein.ratio(ref_w, hyp_w)
                        word_scores.append(w_score)
                    elif ref_w and not hyp_w:
                        word_scores.append(0.0)  # Missing word
                    # Extra words (hyp_w only) don't penalize
            elif tag == 'delete':
                # Missing words = 0 score each
                word_scores.extend([0.0] * (i2 - i1))
            elif tag == 'insert':
                # Extra words spoken - don't penalize existing words
                pass
        
        if not word_scores:
            return 0.0, []
        
        return sum(word_scores) / len(ref_words), word_scores

    # ------------------------------------------------------------------ #
    #  Hybrid Assessment (STT + Scoring + Rule-based Feedback)            #
    # ------------------------------------------------------------------ #
    def _assess_hybrid(self, audio_file, reference_text):
        """
        1. STT: Google Web Speech OR Local Whisper (with faster-whisper support)
        2. Score: Weighted Edit Distance + Sentence Alignment + Confidence Penalty
        3. Feedback: Rule-Based (fast). Use generate_feedback_async() for LLM.
        """
        import Levenshtein
        
        stt_provider = self.config.get("stt_provider", "Google")
        recognized_text = ""
        confidence = 1.0
        candidates = []
        
        # --- STT SECTION ---
        if "Whisper" in stt_provider:
            try:
                self._ensure_whisper_loaded()
                    
                if self.use_faster_whisper:
                    # faster-whisper API
                    segments, info = self.faster_model.transcribe(
                        audio_file,
                        language="en",
                        initial_prompt=f"The word is {reference_text}. Pronunciation assessment."
                    )
                    # Consume generator
                    segment_list = list(segments)
                    recognized_text = " ".join([s.text for s in segment_list]).strip()
                    confidence = math.exp(info.avg_logprob) if hasattr(info, 'avg_logprob') else 0.5
                else:
                    # openai-whisper API
                    result = self.whisper_model.transcribe(
                        audio_file, 
                        fp16=False, 
                        language="en",
                        initial_prompt=f"The word is {reference_text}. Pronunciation assessment."
                    ) 
                    recognized_text = result["text"].strip()
                    avg_logprob = -1.0
                    if result.get("segments"):
                       avg_logprob = result["segments"][0].get("avg_logprob", -1.0)
                    confidence = math.exp(avg_logprob)
                
                # Remove trailing punctuation for cleaner comparison
                recognized_text = recognized_text.translate(str.maketrans('', '', string.punctuation))
                print(f"Whisper: {recognized_text} (Conf: {confidence:.2f})")
                
            except ImportError as e:
                 print(f"Whisper Import Error: {e}")
                 return {"accuracy_score": 0, "fluency_score": 0, "completeness_score": 0, "feedback": f"Whisper 缺失依赖: {e}"}
            except Exception as e:
                 print(f"Whisper Error: {e}")
                 return {"accuracy_score": 0, "fluency_score": 0, "completeness_score": 0, "feedback": f"Whisper 识别出错: {e}"}

        else:
            # Google Web Speech (Free & Simple)
            import speech_recognition as sr
            r = sr.Recognizer()
            try:
                with sr.AudioFile(audio_file) as source:
                    audio_data = r.record(source)
                    payload = r.recognize_google(audio_data, show_all=True)
                    
                    if not payload:
                         return {"accuracy_score": 0, "fluency_score": 0, "completeness_score": 0, "feedback": "没有检测到清晰的语音。"}

                    alts = payload.get('alternative', [])
                    if not alts:
                         return {"accuracy_score": 0, "fluency_score": 0, "completeness_score": 0, "feedback": "无法识别。"}

                    for item in alts:
                        candidates.append(item.get('transcript', ''))
                    
                    top_transcript = alts[0].get('transcript', '')
                    top_confidence = alts[0].get('confidence', 0.8)
                    
                    recognized_text = top_transcript
                    confidence = top_confidence
            except Exception as e:
                print(f"Google STT Error: {e}")
                return {"accuracy_score": 0, "fluency_score": 0, "completeness_score": 0, "feedback": "语音识别服务连接失败。"}

        # --- IMPROVED SCORE SECTION ---
        ref_words = self._normalize(reference_text).split()
        
        if len(ref_words) > 1:
            # Multi-word: use sentence-level alignment scoring
            similarity, word_scores = self._sentence_score(reference_text, recognized_text)
            # Also compute character-level weighted score and take the average
            weighted_sim, _ = self._weighted_edit_score(reference_text, recognized_text)
            similarity = (similarity + weighted_sim) / 2.0
        else:
            # Single word: use weighted edit distance
            similarity, edit_ops = self._weighted_edit_score(reference_text, recognized_text)
            word_scores = [similarity]
        
        score = int(similarity * 100)
        
        # Scoring Optimization (Configurable)
        threshold = self.config.get("scoring_threshold", 0.80) 
        penalty_factor = self.config.get("scoring_penalty", 100 if "Whisper" in stt_provider else 60)
        enable_cap = self.config.get("scoring_strict_cap", True)
        
        penalty_log = 0.0
        
        # Improved non-linear confidence penalty
        if score > 80:
            if confidence >= threshold:
                penalty = 0  # High confidence, no penalty
            elif confidence >= threshold - 0.2:
                # Middle range: gentle linear penalty
                gap = threshold - confidence
                penalty = gap * penalty_factor * 0.5
                penalty = min(25, max(0, penalty))
                score = max(0, int(score - penalty))
                penalty_log = penalty
                print(f"Confidence Penalty (gentle): -{penalty:.1f}")
            else:
                # Very low confidence: heavier penalty
                gap = threshold - confidence
                penalty = gap * penalty_factor * 1.5
                penalty = min(50, max(0, penalty))
                score = max(0, int(score - penalty))
                penalty_log = penalty
                print(f"Confidence Penalty (heavy): -{penalty:.1f}")
             
            # CRITICAL CAP
            if enable_cap and score > 90 and confidence < threshold: 
                print(f"Quality Cap applied: Score {score} -> 88 (Conf {confidence:.2f} too low)")
                score = 88
                 
            # Hard Cap for Very Low Confidence
            if confidence < 0.4 and score > 85:
                score = 85 
        
        # --- RULE-BASED FEEDBACK (Fast, no LLM) ---
        if score >= 90:
            feedback = "发音很标准！非常棒！"
        elif score >= 80:
            feedback = "发音不错，但还有提升空间。注意元音的饱满度。"
        elif score >= 60:
            feedback = "读音基本准确，但声音太小或不够自信。请大声朗读！"
        else:
            feedback = "听不太清，或者发音偏差较大。请仔细听示范音，再试一次。"

        # Specific feedback for the Quality Cap case
        if score == 88 and confidence < threshold and similarity > 0.95:
            feedback = "读音准确，但不够自信。想拿 90+ 需要更大声、更清晰！"
        
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
                "capped": (score == 88 and enable_cap),
                "word_scores": word_scores,
                "scoring_method": "weighted_edit" if len(ref_words) == 1 else "sentence_aligned"
            }
        }

    # ------------------------------------------------------------------ #
    #  Dummy Assessment (No STT/LLM available)                            #
    # ------------------------------------------------------------------ #
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
