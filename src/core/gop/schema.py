"""
Single source of truth for GOP result schema.

Both local pipeline and remote service must serialize/deserialize through these dataclasses.
Any field name or type change here is a breaking change for the wire protocol.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional


PIPELINE_VERSION = "gop-1.0"

# ARPABET vowels (used for vowel_confusion classification).
# All vowel symbols, normalized (no stress digits).
ARPABET_VOWELS = frozenset({
    "AA", "AE", "AH", "AO", "AW", "AY",
    "EH", "ER", "EY",
    "IH", "IY",
    "OW", "OY",
    "UH", "UW",
})


@dataclass
class PhonemeScore:
    """Per-phoneme score with alignment metadata."""
    phoneme: str                         # normalized ARPABET (no stress digit)
    score: int                           # 0-100
    start: float                         # seconds (in original audio)
    end: float                           # seconds
    alignment_confidence: float          # 0-1 (avg posterior over its frames)
    low_confidence: bool = False         # set by scorer when confidence < gating threshold

    def to_dict(self) -> dict:
        return {
            "phoneme": self.phoneme,
            "score": int(self.score),
            "start": float(self.start),
            "end": float(self.end),
            "alignment_confidence": float(self.alignment_confidence),
            "low_confidence": bool(self.low_confidence),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PhonemeScore":
        return cls(
            phoneme=str(d["phoneme"]),
            score=int(d["score"]),
            start=float(d["start"]),
            end=float(d["end"]),
            alignment_confidence=float(d["alignment_confidence"]),
            low_confidence=bool(d.get("low_confidence", False)),
        )


@dataclass
class WordScore:
    word: str
    score: int                            # 0-100
    phonemes: List[PhonemeScore] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "word": self.word,
            "score": int(self.score),
            "phonemes": [p.to_dict() for p in self.phonemes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WordScore":
        return cls(
            word=str(d["word"]),
            score=int(d["score"]),
            phonemes=[PhonemeScore.from_dict(p) for p in d.get("phonemes", [])],
        )


@dataclass
class GopError:
    """Pronunciation error classification."""
    type: str          # substitution | deletion | insertion | vowel_confusion
    expected: str      # ARPABET (may be empty for insertion)
    actual: str        # ARPABET (may be empty for deletion)
    word: str          # word the error belongs to
    position: int      # phoneme index inside the word

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "expected": self.expected,
            "actual": self.actual,
            "word": self.word,
            "position": int(self.position),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GopError":
        return cls(
            type=str(d["type"]),
            expected=str(d.get("expected", "")),
            actual=str(d.get("actual", "")),
            word=str(d.get("word", "")),
            position=int(d.get("position", 0)),
        )


@dataclass
class GopResult:
    text: str                                # reference text (NOT ASR output)
    asr_text: str                            # wav2vec2 greedy decode (debug only)
    words: List[WordScore]
    errors: List[GopError]
    overall_score: int                       # 0-100
    fluency_score: int                       # 0-100
    completeness_score: int                  # 0-100
    model_fingerprint: str                   # 16-char hex
    pipeline_version: str = PIPELINE_VERSION
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "asr_text": self.asr_text,
            "words": [w.to_dict() for w in self.words],
            "errors": [e.to_dict() for e in self.errors],
            "overall_score": int(self.overall_score),
            "fluency_score": int(self.fluency_score),
            "completeness_score": int(self.completeness_score),
            "model_fingerprint": self.model_fingerprint,
            "pipeline_version": self.pipeline_version,
            "elapsed_ms": int(self.elapsed_ms),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GopResult":
        # Strict deserialization: required fields must exist.
        required = ("text", "asr_text", "words", "errors",
                    "overall_score", "fluency_score", "completeness_score",
                    "model_fingerprint", "pipeline_version")
        for key in required:
            if key not in d:
                raise ValueError(f"GopResult.from_dict: missing required field '{key}'")
        return cls(
            text=str(d["text"]),
            asr_text=str(d["asr_text"]),
            words=[WordScore.from_dict(w) for w in d["words"]],
            errors=[GopError.from_dict(e) for e in d["errors"]],
            overall_score=int(d["overall_score"]),
            fluency_score=int(d["fluency_score"]),
            completeness_score=int(d["completeness_score"]),
            model_fingerprint=str(d["model_fingerprint"]),
            pipeline_version=str(d["pipeline_version"]),
            elapsed_ms=int(d.get("elapsed_ms", 0)),
        )


def is_vowel(phoneme: str) -> bool:
    """Test whether a normalized ARPABET symbol is a vowel."""
    return phoneme.upper() in ARPABET_VOWELS
