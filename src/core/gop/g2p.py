"""
G2P (grapheme-to-phoneme) using g2p_en (ARPABET output).

Phoneme normalization: stress digits stripped (AE1 -> AE).
OOV words: logged once + placeholder ['UNK'].
"""
from __future__ import annotations

import re
from typing import List, Tuple

# Lazy-loaded g2p instance.
_G2P = None
_OOV_LOGGED = set()


def _ensure_nltk_resources():
    """Auto-download NLTK resources required by g2p_en.

    g2p_en depends on NLTK's POS tagger and CMU dict.  NLTK >= 3.9 split the
    English tagger into ``averaged_perceptron_tagger_eng``; older versions used
    ``averaged_perceptron_tagger``.  We try both so the pipeline works for
    any installed NLTK version on first launch.
    """
    try:
        import nltk
    except Exception:
        return  # nltk not available — let g2p_en fail with its own error

    needed = [
        ("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng"),
        ("taggers/averaged_perceptron_tagger", "averaged_perceptron_tagger"),
        ("corpora/cmudict", "cmudict"),
    ]
    for path, pkg in needed:
        try:
            nltk.data.find(path)
        except LookupError:
            try:
                nltk.download(pkg, quiet=True)
            except Exception as e:
                print(f"[gop.g2p] NLTK download '{pkg}' failed: {e}")


def _load_g2p():
    global _G2P
    if _G2P is None:
        _ensure_nltk_resources()
        from g2p_en import G2p
        _G2P = G2p()
    return _G2P


_STRESS_RE = re.compile(r"\d+$")


def normalize_phoneme(p: str) -> str:
    """Strip ARPABET stress digits and uppercase. AE1 -> AE."""
    if not p:
        return ""
    s = p.strip().upper()
    return _STRESS_RE.sub("", s)


_WORD_RE = re.compile(r"[A-Za-z']+")

# 常见英语教学缩写展开（教材中常见）
_ABBREVIATIONS = {
    "sb": "somebody",
    "sth": "something",
    "esp": "especially",
    "etc": "etcetera",
    "govt": "government",
    "dept": "department",
    "info": "information",
    "vs": "versus",
}


def tokenize_words(text: str) -> List[str]:
    """Lower-cased word tokens with apostrophes preserved.

    缩写自动展开（sb->somebody, sth->something 等）。
    """
    raw = [w.lower() for w in _WORD_RE.findall(text or "")]
    out: List[str] = []
    for w in raw:
        expanded = _ABBREVIATIONS.get(w, w)
        out.append(expanded)
    return out


def text_to_phonemes(text: str) -> List[Tuple[str, List[str]]]:
    """
    Convert reference text to per-word ARPABET phoneme lists.

    Returns:
        [(word, [normalized_phonemes...]), ...]

    OOV words yield placeholder ['UNK'].
    Punctuation tokens from g2p_en (e.g. ' ', ',') are dropped.
    """
    g2p = _load_g2p()
    out: List[Tuple[str, List[str]]] = []
    for word in tokenize_words(text):
        try:
            raw = g2p(word)
        except Exception as e:
            print(f"[gop.g2p] g2p_en failed on '{word}': {e}")
            raw = []

        # g2p_en returns a flat list of ARPABET tokens (and possibly punctuation).
        phones: List[str] = []
        for tok in raw:
            if not tok:
                continue
            tok = tok.strip()
            if not tok:
                continue
            # Skip punctuation tokens (g2p_en sometimes returns these).
            if not re.match(r"^[A-Za-z]", tok):
                continue
            n = normalize_phoneme(tok)
            if n:
                phones.append(n)

        if not phones:
            if word not in _OOV_LOGGED:
                print(f"[gop.g2p] OOV word: '{word}' -> [UNK]")
                _OOV_LOGGED.add(word)
            phones = ["UNK"]

        out.append((word, phones))
    return out


def expected_phoneme_count(text: str) -> int:
    """Estimate phoneme count for VAD short-sentence bypass decisions."""
    pairs = text_to_phonemes(text)
    return sum(len(p) for _, p in pairs)
