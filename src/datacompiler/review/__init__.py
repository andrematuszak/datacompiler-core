"""Human review of competing page transcriptions."""

from datacompiler.review.divergence import (
    align_candidates,
    build_review,
    compose_text,
    decide,
    refresh_state,
)

__all__ = [
    "align_candidates",
    "build_review",
    "compose_text",
    "decide",
    "refresh_state",
]
