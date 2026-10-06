"""
PronunciationCoach: routes assess() to GOP (default), Azure, Omni, or dummy.

GOP (Goodness of Pronunciation) is the recommended scoring kernel —
deterministic, phoneme-level, with the same schema for local and remote
backends.

Omni (MiniCPM-o 4.5) is an opt-in LLM-based scoring alternative that
listens to the student's audio and returns a holistic score. It is less
deterministic than GOP; on timeout/failure it falls back to GOP.

LLM is used only for optional natural-language feedback (post-hoc explanation)
in the GOP path, never for the GOP score itself.
"""
import os
import json
import re
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

try:
    import azure.cognitiveservices.speech as speechsdk
except Exception:
    # PyInstaller raises PyInstallerImportError (not always ImportError subclass)
    # when native DLL is missing from the bundle
    speechsdk = None

from src.core.qt_compat import QObject, pyqtSignal


# ---------------------------------------------------------------------- #
# ARPABET 机器码 → 课本常见 IPA 音标（评分明细/反馈展示给用户）
# 与 gop/aligner.py 的 ARPABET_TO_IPA（模型对齐用，机器视角）分开维护：
# 这里按国内课本的英式音标习惯取形（iː/uː/ɜː/r…），与词卡上的音标一致。
# ---------------------------------------------------------------------- #
_ARPABET_DISPLAY_IPA = {
    # 元音
    "AA": "ɑː", "AE": "æ", "AH": "ʌ", "AO": "ɔː",
    "AW": "aʊ", "AY": "aɪ",
    "EH": "e", "ER": "ɜː", "EY": "eɪ",
    "IH": "ɪ", "IY": "iː",
    "OW": "əʊ", "OY": "ɔɪ",
    "UH": "ʊ", "UW": "uː",
    # 辅音
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð",
    "F": "f", "G": "ɡ", "HH": "h",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n",
    "NG": "ŋ", "P": "p", "R": "r", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "V": "v", "W": "w", "Y": "j",
    "Z": "z", "ZH": "ʒ",
}


def _to_display_ipa(raw: dict) -> None:
    """把 GOP 结果里的 ARPABET 码原地替换为课本 IPA 音标（仅展示层）。

    errors 的 actual 偶尔混入 wav2vec2 vocab 的 IPA 原 token（反查
    ARPABET 失败时原样保留），其中 "Ə"(U+018F) 等变体不在标准 IPA 里，
    一并规范化。
    """
    fix = {"Ə": "ə", "É": "e", "À": "a", "Ò": "o", "Ì": "i", "Û": "u", "Â": "ɐ"}
    for w in raw.get("words") or []:
        for p in w.get("phonemes") or []:
            code = str(p.get("phoneme", ""))
            p["phoneme"] = _ARPABET_DISPLAY_IPA.get(code.upper(), code)
    for e in raw.get("errors") or []:
        for k in ("expected", "actual"):
            code = str(e.get(k, ""))
            e[k] = _ARPABET_DISPLAY_IPA.get(code.upper(), "".join(fix.get(c, c) for c in code))


class AssessorSignals(QObject):
    """Signals for async LLM feedback generation."""
    feedback_ready = pyqtSignal(str, str)   # (reference_word, llm_feedback_text)
    feedback_error = pyqtSignal(str)         # error message


class PronunciationCoach:
    def __init__(self):
        self.signals = AssessorSignals()
        self._current_reference = ""
        self._gop_pipeline = None  # lazy
        self.load_config()

    # ------------------------------------------------------------------ #
    def load_config(self):
        self.config = {}
        self.speech_key = os.getenv("SPEECH_KEY")
        self.speech_region = os.getenv("SPEECH_REGION")

        from src.utils import get_user_data_path
        config_path = get_user_data_path("config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                if self.config.get("azure_key"):
                    self.speech_key = self.config.get("azure_key")
                if self.config.get("azure_region"):
                    self.speech_region = self.config.get("azure_region")
                # 将 HF Token 注入环境变量，让 transformers / huggingface_hub 自动认账
                # （wav2vec2 首次下载、Whisper 下载等都会受益）
                hf_tok = (self.config.get("hf_token") or "").strip()
                if hf_tok and not os.environ.get("HF_TOKEN"):
                    os.environ["HF_TOKEN"] = hf_tok
            except (json.JSONDecodeError, IOError) as e:
                print(f"[AIAssessor] Error loading config: {e}")

        # Reset GOP pipeline so config changes take effect.
        self._gop_pipeline = None

        self.use_dummy = (not self.speech_key or not self.speech_region or speechsdk is None)

    # ------------------------------------------------------------------ #
    #  LLM client (used only for optional async feedback)                  #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize_base_url(url: str) -> str:
        """Ensure base_url ends with /v1 for OpenAI-compatible APIs.

        Common user mistake: omit `/v1` (e.g. http://host:9090), then the SDK
        requests `http://host:9090/chat/completions` and gets 404.
        """
        if not url:
            return url
        url = url.rstrip("/")
        if not url.endswith("/v1"):
            url = url + "/v1"
        return url

    def _get_llm_client(self):
        """Returns (OpenAI_client, model_name) or (None, None)."""
        from openai import OpenAI

        provider = self.config.get("ai_provider", "")
        if "Custom" in provider:
            base_url = self._normalize_base_url(
                self.config.get("custom_base", "http://localhost:8080/v1")
            )
            api_key = self.config.get("custom_key") or "not-needed"
            model = self.config.get("custom_model", "")
            if not model:
                print("[AIAssessor] LLM client: Custom selected but no model configured.")
                return None, None
            print(f"[AIAssessor] LLM client: Custom -> {base_url} | model={model}")
            return OpenAI(base_url=base_url, api_key=api_key), model

        if "Ollama" in provider:
            base_url = self._normalize_base_url(
                self.config.get("ollama_base", "http://localhost:11434/v1")
            )
            model = self.config.get("ollama_model", "qwen2.5")
            print(f"[AIAssessor] LLM client: Ollama -> {base_url} | model={model}")
            return OpenAI(base_url=base_url, api_key="ollama"), model

        if "OpenAI" in provider:
            base_url = self.config.get("openai_base", "https://api.openai.com/v1")
            api_key = self.config.get("openai_key", "")
            model = self.config.get("openai_model", "gpt-4o")
            if not api_key:
                print("[AIAssessor] LLM client: OpenAI selected but no api_key.")
                return None, None
            print(f"[AIAssessor] LLM client: OpenAI -> {base_url} | model={model}")
            return OpenAI(base_url=base_url, api_key=api_key), model

        print(f"[AIAssessor] LLM client: no provider matched (ai_provider={provider!r})")
        return None, None

    def _has_llm(self):
        provider = self.config.get("ai_provider", "")
        return bool(provider and (
            "Ollama" in provider or "OpenAI" in provider or "Custom" in provider
        ))

    # ------------------------------------------------------------------ #
    #  Main entry                                                          #
    # ------------------------------------------------------------------ #
    def assess(self, audio_file, reference_text):
        """Default: GOP scoring. Azure/Omni are opt-in alternatives."""
        engine = (self.config.get("assessor_engine", "gop") or "gop").lower()

        if engine == "azure":
            if speechsdk and self.speech_key and self.speech_region:
                return self._assess_azure(audio_file, reference_text)
            print("[AIAssessor] Azure selected but not configured; falling back to GOP.")
            engine = "gop"

        if engine == "omni":
            try:
                return self._assess_omni(audio_file, reference_text)
            except Exception as e:
                print(f"[AIAssessor] Omni failed: {e}; falling back to GOP.")
                traceback.print_exc()
                engine = "gop"

        if engine == "gop":
            try:
                return self._assess_gop(audio_file, reference_text)
            except Exception as e:
                print(f"[AIAssessor] GOP failed: {e}")
                traceback.print_exc()
                return self._error_result(f"评分引擎错误: {e}")

        return self._dummy_assess(reference_text)

    # ------------------------------------------------------------------ #
    #  GOP assessment                                                      #
    # ------------------------------------------------------------------ #
    def _get_gop_pipeline(self):
        """Lazy-create + cache the GOP pipeline."""
        if self._gop_pipeline is not None:
            return self._gop_pipeline
        from src.core.gop import GopPipeline
        mode = (self.config.get("gop_mode", "local") or "local").lower()
        model = self.config.get("gop_model", "facebook/wav2vec2-lv-60-espeak-cv-ft")
        device = self.config.get("gop_device", "auto")
        remote_url = self.config.get("gop_remote_url", "")
        remote_key = self.config.get("gop_remote_key", "")
        self._gop_pipeline = GopPipeline(
            mode=mode,
            model_name=model,
            device=device,
            remote_url=remote_url,
            remote_key=remote_key,
        )
        return self._gop_pipeline

    def _assess_gop(self, audio_file, reference_text):
        pipeline = self._get_gop_pipeline()
        raw = pipeline.score(audio_file, reference_text)
        _to_display_ipa(raw)
        feedback = self._format_gop_feedback(raw)
        scoring_method = f"gop_{(self.config.get('gop_mode','local') or 'local').lower()}"

        return {
            "accuracy_score": int(raw.get("overall_score", 0)),
            "fluency_score": int(raw.get("fluency_score", 0)),
            "completeness_score": int(raw.get("completeness_score", 0)),
            "feedback": feedback,
            "details": {
                "scoring_method": scoring_method,
                "recognized": raw.get("asr_text", ""),
                "reference": raw.get("text", reference_text),
                "words": raw.get("words", []),
                "errors": raw.get("errors", []),
                "model_fingerprint": raw.get("model_fingerprint", ""),
                "pipeline_version": raw.get("pipeline_version", ""),
                "elapsed_ms": int(raw.get("elapsed_ms", 0)),
                "overall_score": int(raw.get("overall_score", 0)),
            },
        }

    # ------------------------------------------------------------------ #
    def _format_gop_feedback(self, raw):
        """Compose a short Chinese feedback string from GOP errors."""
        score = int(raw.get("overall_score", 0))
        errors = raw.get("errors", []) or []

        if not errors:
            if score >= 90:
                return "发音很棒！每个音都清晰准确。"
            if score >= 75:
                return "整体发音不错，节奏可以再稳一些。"
            if score >= 60:
                return "基本能听懂，再多模仿标准音会更好。"
            return "声音有点小或不太清晰，再大声试一次。"

        # Group by type, then format up to 2 most informative messages.
        msgs = []
        for err in errors[:3]:
            etype = err.get("type", "")
            exp = err.get("expected", "")
            act = err.get("actual", "")
            word = err.get("word", "")
            if etype == "substitution":
                if exp and act:
                    msgs.append(f"{word or '该词'}里 /{exp}/ 读成了 /{act}/")
                elif exp:
                    msgs.append(f"{word or '该词'}里 /{exp}/ 发音不准")
            elif etype == "vowel_confusion":
                msgs.append(f"{word or '该词'}里元音 /{exp}/ 听起来更像 /{act}/")
            elif etype == "deletion":
                msgs.append(f"{word or '该词'}里 /{exp}/ 没读出来")
            elif etype == "insertion":
                if act:
                    msgs.append(f"多了个 /{act}/ 音")
            if len(msgs) >= 2:
                break

        if not msgs:
            return "整体不错，再注意一下细节。"
        prefix = "再加把劲！" if score < 70 else "很接近了，"
        return prefix + "；".join(msgs)

    # ------------------------------------------------------------------ #
    #  Omni assessment (MiniCPM-o 4.5, opt-in LLM-based)                   #
    # ------------------------------------------------------------------ #
    def _get_omni_client(self):
        """Lazy-create + cache the OmniClient from config."""
        if getattr(self, "_omni_client", None) is not None:
            return self._omni_client
        from src.core.omni_client import OmniClient, OmniConfig
        self._omni_client = OmniClient(OmniConfig.from_config(self.config))
        return self._omni_client

    def _has_omni(self) -> bool:
        host = (self.config.get("omni_host") or "").strip()
        return bool(host)

    def _assess_omni(self, audio_file, reference_text):
        """Send audio + reference to MiniCPM-o; parse structured JSON score."""
        client = self._get_omni_client()
        prompt = (
            "你是一个专业的少儿英语发音评分老师。请听这段学生录音，与标准文本对比，评估发音准确性。\n"
            f"标准文本: \"{reference_text}\"\n\n"
            "请严格只回复一个JSON对象（不要markdown、不要其他文字），格式如下：\n"
            '{"score": <0-100的整数>, "recognized": "<你听到的英文>", '
            '"feedback": "<30字以内中文纠音建议>"}'
        )

        # Run in a bounded thread so a slow omni server can't freeze the UI forever.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.chat, prompt, audio_file)
            try:
                raw_text = future.result(timeout=60)
            except FuturesTimeout:
                raise RuntimeError("Omni 评分超时（60秒），已回退到 GOP。")
            except Exception as e:
                raise RuntimeError(f"Omni 评分请求失败: {e}") from e

        data = self._parse_omni_score(raw_text, reference_text)
        score = int(data.get("score", 0))
        feedback = data.get("feedback", "") or "评分完成。"
        recognized = data.get("recognized", "")

        return {
            "accuracy_score": score,
            "fluency_score": score,
            "completeness_score": score,
            "feedback": feedback,
            "details": {
                "scoring_method": "omni",
                "recognized": recognized,
                "reference": reference_text,
                "model": self.config.get("omni_model", "minicpm-o45"),
                "raw": raw_text[:500],
            },
        }

    @staticmethod
    def _parse_omni_score(raw: str, reference_text: str) -> dict:
        """Extract score JSON from the model response, with fallbacks."""
        # 1. Direct JSON parse
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "score" in data:
                return data
        except json.JSONDecodeError:
            pass
        # 2. Regex extract a JSON object containing "score"
        m = re.search(r'\{[^{}]*"score"[^{}]*\}', raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        # 3. Extract any number 0-100 as a last resort
        nums = re.findall(r'\b(\d{1,3})\b', raw)
        for n in nums:
            v = int(n)
            if 0 <= v <= 100:
                return {"score": v, "recognized": "", "feedback": "评分完成。"}
        # 4. Total fallback
        return {"score": 0, "recognized": "", "feedback": "无法解析评分结果。"}

    # ------------------------------------------------------------------ #
    #  Async LLM feedback (optional, post-hoc)                             #
    # ------------------------------------------------------------------ #
    def generate_feedback_async(self, score, confidence, reference_text, recognized_text, candidates=None):
        """
        Optional LLM-generated natural-language explanation. Does NOT change scores.
        No-op if no LLM configured, or score is already near-perfect (>= 95).
        """
        if score >= 95 or not self._has_llm():
            return
        self._current_reference = reference_text
        t = threading.Thread(
            target=self._generate_feedback_worker,
            args=(score, confidence, reference_text, recognized_text, candidates or []),
            daemon=True,
        )
        t.start()

    def _generate_feedback_worker(self, score, confidence, reference_text, recognized_text, candidates):
        client, model = self._get_llm_client()
        if not client:
            return
        provider = self.config.get("ai_provider", "")
        # 根据 provider 选取对应的 base_url，仅用于错误诊断输出
        if "Custom" in provider:
            base_url = self.config.get("custom_base", "http://localhost:8080/v1")
        elif "Ollama" in provider:
            base_url = self.config.get("ollama_base", "http://localhost:11434/v1")
        elif "OpenAI" in provider:
            base_url = self.config.get("openai_base", "https://api.openai.com/v1")
        else:
            base_url = "(none)"
        try:
            context_str = str(candidates) if candidates else f"'{recognized_text}'"
            prompt = (
                f"我是少儿英语老师。\n"
                f"目标单词/句子: \"{reference_text}\"\n"
                f"学生读成: {context_str}\n"
                f"最终评分: {score}\n\n"
                f"请用中文给出一句简短鼓励性的纠音建议（30字以内）。"
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
            )
            llm_feedback = (response.choices[0].message.content or "").strip()
            if llm_feedback and self._current_reference == reference_text:
                self.signals.feedback_ready.emit(reference_text, llm_feedback)
        except Exception as e:
            # 详细输出：类型 + 消息 + provider/base_url/model，便于排查
            err_type = type(e).__name__
            print(f"LLM Async Error [{provider}|{base_url}|{model}] "
                  f"{err_type}: {e}")

    # ------------------------------------------------------------------ #
    #  Azure path (kept for enterprise users)                              #
    # ------------------------------------------------------------------ #
    def _assess_azure(self, audio_file, reference_text):
        if not speechsdk:
            return self._error_result("Azure SDK 未安装。")
        try:
            speech_config = speechsdk.SpeechConfig(subscription=self.speech_key, region=self.speech_region)
            audio_config = speechsdk.audio.AudioConfig(filename=audio_file)
            pronunciation_config = speechsdk.PronunciationAssessmentConfig(
                reference_text=reference_text,
                grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
                granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
                enable_miscue=True,
            )
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config, audio_config=audio_config,
            )
            pronunciation_config.apply_to(speech_recognizer)
            result = speech_recognizer.recognize_once()
            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                pron = speechsdk.PronunciationAssessmentResult(result)
                score = int(pron.accuracy_score)
                feedback = "发音很棒！继续保持！"
                if score < 60:
                    feedback = "声音有点小，或者发音不太清晰，试着大声一点？"
                elif score < 80:
                    feedback = "发音还可以，但有些音节不够饱满，请听听标准发音。"
                elif score < 90:
                    feedback = "非常接近了！注意语调和连读会更完美。"
                return {
                    "accuracy_score": score,
                    "fluency_score": int(pron.fluency_score),
                    "completeness_score": int(pron.completeness_score),
                    "feedback": feedback,
                    "details": {"scoring_method": "azure"},
                }
            if result.reason == speechsdk.ResultReason.NoMatch:
                return self._error_result("没有检测到语音，请大声一点。")
            return self._error_result("无法识别，请再试一次。")
        except Exception as e:
            print(f"Azure Error: {e}")
            return self._error_result(f"AI 服务错误: {e}")

    # ------------------------------------------------------------------ #
    #  Misc helpers                                                        #
    # ------------------------------------------------------------------ #
    def warmup(self):
        """Background-load the GOP aligner so first user click is fast."""
        engine = (self.config.get("assessor_engine", "gop") or "gop").lower()
        if engine != "gop":
            return
        mode = (self.config.get("gop_mode", "local") or "local").lower()
        if mode != "local":
            return  # remote: nothing to preload
        try:
            print("[AIAssessor] Warming up GOP aligner...")
            self._get_gop_pipeline().fingerprint()  # forces model load
            print("[AIAssessor] GOP aligner ready.")
        except Exception as e:
            print(f"[AIAssessor] GOP warmup failed: {e}")

    def _error_result(self, message):
        return {
            "accuracy_score": 0,
            "fluency_score": 0,
            "completeness_score": 0,
            "feedback": message,
            "details": {"scoring_method": "error", "error": message},
        }

    def _dummy_assess(self, reference_text):
        import random
        score = random.randint(50, 100)
        feedbacks = [
            "注意元音的发音要饱满。",
            "试着模仿标准发音的语调。",
            "你的语速适中，继续加油！",
            "注意单词结尾的辅音不要吞掉。",
            "很好的尝试，再来一次会更好！",
        ]
        feedback = "完美！" if score >= 90 else random.choice(feedbacks)
        return {
            "accuracy_score": score,
            "fluency_score": random.randint(60, 100),
            "completeness_score": random.randint(80, 100),
            "feedback": feedback,
            "details": {"scoring_method": "dummy"},
        }
