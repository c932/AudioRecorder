"""
Model fingerprint computation.

Used to gate cross-instance score comparisons (local vs remote): if fingerprints
differ, scores from the two instances are not directly comparable.
"""
from __future__ import annotations

import hashlib
import json


def compute_fingerprint(model_name: str, vocab: dict, revision: str = "") -> str:
    """
    sha256(model_name + revision + sorted(vocab))[:16]

    Args:
        model_name: HF model identifier (e.g. 'facebook/wav2vec2-lv-60-espeak-cv-ft')
        vocab: token -> id mapping from the processor's tokenizer
        revision: optional commit hash / tag from HF Hub (defaults to empty)

    Returns:
        16-character hex digest (deterministic for given inputs).
    """
    h = hashlib.sha256()
    h.update((model_name or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((revision or "").encode("utf-8"))
    h.update(b"\x00")
    if vocab:
        sorted_items = sorted(vocab.items(), key=lambda kv: str(kv[0]))
        h.update(json.dumps(sorted_items, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return h.hexdigest()[:16]
