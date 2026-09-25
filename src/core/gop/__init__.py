"""
GOP (Goodness of Pronunciation) scoring kernel.

Public API:
    from src.core.gop import GopPipeline, score
"""
from src.core.gop.pipeline import GopPipeline, get_pipeline, score
from src.core.gop.schema import (
    PhonemeScore,
    WordScore,
    GopError,
    GopResult,
)

__all__ = [
    "GopPipeline",
    "get_pipeline",
    "score",
    "PhonemeScore",
    "WordScore",
    "GopError",
    "GopResult",
]
