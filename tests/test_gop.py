"""
Phase A unit tests for the GOP scoring kernel.

Tests are split into:
  * Pure logic tests (always run): schema, normalization, sigmoid, fingerprint, vad bypass.
  * Heavy tests (skipped unless RUN_HEAVY_GOP_TESTS=1): aligner + scorer end-to-end.

Run pure tests:
    python -m pytest tests/test_gop.py -q

Run heavy tests (requires torch + transformers + a sample wav at samples/cat.wav):
    set RUN_HEAVY_GOP_TESTS=1
    python -m pytest tests/test_gop.py -q
"""
from __future__ import annotations

import math
import os
import sys
import unittest

# Ensure project root on path when running directly.
_PROJ_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from src.core.gop.schema import (
    PhonemeScore, WordScore, GopError, GopResult, PIPELINE_VERSION, is_vowel,
)
from src.core.gop.fingerprint import compute_fingerprint
from src.core.gop.g2p import normalize_phoneme
from src.core.gop.vad import should_bypass_vad
from src.core.gop.scorer import sigmoid_score, SIGMOID_MID


HEAVY = os.environ.get("RUN_HEAVY_GOP_TESTS", "0") == "1"


# ====================================================================== #
# Pure logic tests
# ====================================================================== #
class SchemaTests(unittest.TestCase):
    def test_phoneme_round_trip(self):
        p = PhonemeScore(phoneme="AE", score=80, start=0.0, end=0.1,
                         alignment_confidence=0.9, low_confidence=False)
        d = p.to_dict()
        p2 = PhonemeScore.from_dict(d)
        self.assertEqual(p, p2)

    def test_gop_result_round_trip(self):
        ph = PhonemeScore(phoneme="K", score=90, start=0.0, end=0.05,
                          alignment_confidence=0.95)
        w = WordScore(word="cat", score=88, phonemes=[ph])
        e = GopError(type="substitution", expected="TH", actual="S", word="think", position=0)
        r = GopResult(text="cat", asr_text="k a t", words=[w], errors=[e],
                      overall_score=88, fluency_score=80, completeness_score=100,
                      model_fingerprint="abcd1234abcd1234")
        d = r.to_dict()
        r2 = GopResult.from_dict(d)
        self.assertEqual(r2.overall_score, 88)
        self.assertEqual(r2.pipeline_version, PIPELINE_VERSION)
        self.assertEqual(r2.errors[0].type, "substitution")
        self.assertEqual(r2.words[0].phonemes[0].phoneme, "K")

    def test_from_dict_strict(self):
        with self.assertRaises(ValueError):
            GopResult.from_dict({"text": "x"})  # missing nearly all fields


class PhonemeNormalizationTests(unittest.TestCase):
    def test_strip_stress_digit(self):
        self.assertEqual(normalize_phoneme("AE1"), "AE")
        self.assertEqual(normalize_phoneme("AE0"), "AE")
        self.assertEqual(normalize_phoneme("AE"), "AE")
        self.assertEqual(normalize_phoneme("ah2"), "AH")

    def test_vowel_table(self):
        self.assertTrue(is_vowel("AE"))
        self.assertTrue(is_vowel("IY"))
        self.assertFalse(is_vowel("K"))
        self.assertFalse(is_vowel("TH"))


class SigmoidTests(unittest.TestCase):
    def test_monotonic(self):
        scores = [sigmoid_score(g) for g in (-10, -5, -2, 0, 2, 5, 10)]
        for a, b in zip(scores, scores[1:]):
            self.assertLessEqual(a, b)

    def test_midpoint_is_50(self):
        # GOP == SIGMOID_MID -> 50
        self.assertEqual(sigmoid_score(SIGMOID_MID), 50)

    def test_clamps(self):
        self.assertEqual(sigmoid_score(-1e9), 0)
        self.assertEqual(sigmoid_score(1e9), 100)


class FingerprintTests(unittest.TestCase):
    def test_stable(self):
        vocab = {"a": 1, "b": 2, "c": 3}
        f1 = compute_fingerprint("m", vocab, "rev1")
        f2 = compute_fingerprint("m", vocab, "rev1")
        self.assertEqual(f1, f2)
        self.assertEqual(len(f1), 16)

    def test_changes_on_input_change(self):
        v = {"a": 1}
        self.assertNotEqual(compute_fingerprint("m", v), compute_fingerprint("m2", v))
        self.assertNotEqual(compute_fingerprint("m", v, "r1"), compute_fingerprint("m", v, "r2"))
        self.assertNotEqual(compute_fingerprint("m", {"a": 1}), compute_fingerprint("m", {"a": 2}))


class VadBypassTests(unittest.TestCase):
    def test_bypass_few_phonemes(self):
        # No file needed when phoneme count <= threshold.
        self.assertTrue(should_bypass_vad("does_not_exist.wav", expected_phoneme_count=2))
        self.assertTrue(should_bypass_vad("does_not_exist.wav", expected_phoneme_count=4))

    def test_no_bypass_for_long_text(self):
        # File missing (duration -> 0), but phoneme count is large.
        self.assertFalse(should_bypass_vad("does_not_exist.wav", expected_phoneme_count=20))


# ====================================================================== #
# Heavy tests (require torch / transformers / a sample wav)
# ====================================================================== #
@unittest.skipUnless(HEAVY, "Set RUN_HEAVY_GOP_TESTS=1 to enable end-to-end tests")
class HeavyPipelineTests(unittest.TestCase):
    """End-to-end smoke tests. Require model download (~315MB) on first run."""

    SAMPLE = os.path.join(_PROJ_ROOT, "samples", "cat.wav")

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(cls.SAMPLE):
            raise unittest.SkipTest(f"sample wav not found: {cls.SAMPLE}")

    def test_score_returns_schema(self):
        from src.core.gop.pipeline import GopPipeline
        p = GopPipeline(mode="local")
        out = p.score(self.SAMPLE, "the cat sat")
        # Strict schema (raises if any field missing).
        GopResult.from_dict(out)
        self.assertIn("words", out)
        self.assertEqual(out["pipeline_version"], PIPELINE_VERSION)

    def test_score_stability(self):
        from src.core.gop.pipeline import GopPipeline
        p = GopPipeline(mode="local")
        scores = []
        for _ in range(5):
            out = p.score(self.SAMPLE, "the cat sat")
            scores.append(out["overall_score"])
        self.assertLessEqual(max(scores) - min(scores), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
