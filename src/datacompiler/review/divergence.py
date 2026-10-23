"""Align several transcriptions of one page and expose where they disagree.

The unit of disagreement is a *span* of tokens, not an isolated word, so one
change of word splitting does not produce a cascade of phantom divergences.
No coordinates are needed: alignment works on token sequences only. Decisions
(automatic or human) are stored on the divergences; the validated text is
derived from them and never overwrites the original candidates.
"""

import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Iterable, Optional

from datacompiler.model.document import (
    Divergence,
    OcrCandidate,
    PageReview,
    ReviewDecision,
    ReviewProposal,
)

_TOKEN = re.compile(r"(\S+)(\s*)")
# Spans containing a digit or the illegible marker "[?]" are never decided
# automatically: amounts, dates and dosages are where a shared model error is
# costliest, and a majority of "[?]" is not a reading.
STRICT_PATTERN = re.compile(r"\d|\[\?\]")
CONTEXT_TOKENS = 4


def tokenize(text: str) -> list[tuple[str, str]]:
    """Split into (token, trailing whitespace) pairs, keeping line breaks."""
    return [(m.group(1), m.group(2)) for m in _TOKEN.finditer(text)]


def _keys(tokens) -> list[str]:
    return [unicodedata.normalize("NFC", token) for token, _ in tokens]


def _blocks(ref_keys: list[str], cand_keys: list[str]) -> list[tuple[int, int, int]]:
    matcher = SequenceMatcher(None, ref_keys, cand_keys, autojunk=False)
    return [(0, 0, 0)] + matcher.get_matching_blocks()


def _diff_intervals(blocks) -> list[tuple[int, int]]:
    """Reference intervals [i, j) that differ; i == j for a pure insertion."""
    out, pos_a, pos_b = [], 0, 0
    for a, b, size in blocks:
        if a > pos_a or b > pos_b:
            out.append((pos_a, a))
        pos_a, pos_b = a + size, b + size
    return out


def _project(blocks, pos: int, *, end: bool) -> int:
    """Map a reference boundary to the candidate, picking the right side of an insertion."""
    hits = [(a, b, size) for a, b, size in blocks if a <= pos <= a + size]
    a, b, _ = hits[-1] if end else hits[0]
    return b + (pos - a)


def _merge(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def _join(tokens) -> str:
    return " ".join(token for token, _ in tokens)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def align_candidates(
    candidates: list[OcrCandidate],
    reference_id: Optional[str] = None,
) -> list[Divergence]:
    """Return the divergences between all candidates, relative to a reference."""
    if len(candidates) < 2:
        return []
    ref = next((c for c in candidates if c.id == reference_id), candidates[0])
    others = [c for c in candidates if c is not ref]
    ref_toks = tokenize(ref.text)
    ref_keys = _keys(ref_toks)

    per_candidate = {}
    intervals = []
    for cand in others:
        cand_toks = tokenize(cand.text)
        blocks = _blocks(ref_keys, _keys(cand_toks))
        per_candidate[cand.id] = (cand_toks, blocks)
        intervals.extend(_diff_intervals(blocks))

    divergences = []
    for index, (start, end) in enumerate(_merge(intervals), start=1):
        readings: dict[str, list[str]] = {}
        readings.setdefault(_join(ref_toks[start:end]), []).append(ref.id)
        for cand in others:
            cand_toks, blocks = per_candidate[cand.id]
            a = _project(blocks, start, end=False)
            b = _project(blocks, end, end=True)
            readings.setdefault(_join(cand_toks[a:b]), []).append(cand.id)
        if len(readings) < 2:
            continue
        divergences.append(
            Divergence(
                id=f"d{index}",
                kind="omission" if "" in readings else "substitution",
                ref_start=start,
                ref_end=end,
                context_before=_join(ref_toks[max(0, start - CONTEXT_TOKENS):start]),
                context_after=_join(ref_toks[end:end + CONTEXT_TOKENS]),
                proposals=[ReviewProposal(text=t, candidate_ids=ids) for t, ids in readings.items()],
            )
        )
    return divergences


def auto_decide(divergence: Divergence, n_candidates: int, strict=STRICT_PATTERN) -> bool:
    """Accept a strict-majority reading automatically, unless it is a risky span.

    Agreement is a signal, not proof: models can share the same error, so spans
    with digits stay open for a human. Returns True when a decision was made.
    """
    if any(strict.search(p.text) for p in divergence.proposals):
        return False
    best = max(divergence.proposals, key=lambda p: len(p.candidate_ids))
    if len(best.candidate_ids) * 2 <= n_candidates:
        return False
    divergence.decision = ReviewDecision(
        by="auto",
        choice=best.candidate_ids[0],
        text=best.text,
        reason=f"majority {len(best.candidate_ids)}/{n_candidates}",
        timestamp=_now(),
    )
    return True


def decide(divergence: Divergence, choice: str, text: Optional[str] = None, reason: str = "") -> None:
    """Record a human decision: a candidate id, "custom" (with text) or "pending"."""
    if choice == "custom":
        if text is None:
            raise ValueError("A custom decision needs a text.")
        resolved = text
    elif choice == "pending":
        resolved = ""
    else:
        proposal = next((p for p in divergence.proposals if choice in p.candidate_ids), None)
        if proposal is None:
            raise ValueError(f"{choice!r} did not propose anything for {divergence.id}.")
        resolved = proposal.text
    divergence.decision = ReviewDecision(
        by="human", choice=choice, text=resolved, reason=reason, timestamp=_now()
    )


def compose_text(review: PageReview, candidates: list[OcrCandidate]) -> Optional[str]:
    """Build the validated transcription, or None while a divergence is open."""
    if any(d.status == "open" for d in review.divergences):
        return None
    ref = next(c for c in candidates if c.id == review.reference_candidate_id)
    toks = tokenize(ref.text)
    out, pos = [], 0
    for d in sorted(review.divergences, key=lambda d: d.ref_start):
        out.extend(token + ws for token, ws in toks[pos:d.ref_start])
        replacement = d.decision.text.strip()
        if replacement:
            trailing = toks[d.ref_end - 1][1] if d.ref_end > d.ref_start else " "
            out.append(replacement + (trailing or " "))
        pos = d.ref_end
    out.extend(token + ws for token, ws in toks[pos:])
    return "".join(out).strip()


def build_review(candidates: list[OcrCandidate], reference_id: Optional[str] = None) -> PageReview:
    """Align candidates, apply safe automatic decisions and set the review state."""
    if len(candidates) < 2:
        return PageReview()
    ref = next((c for c in candidates if c.id == reference_id), candidates[0])
    review = PageReview(
        state="in_review",
        reference_candidate_id=ref.id,
        divergences=align_candidates(candidates, ref.id),
    )
    for divergence in review.divergences:
        auto_decide(divergence, len(candidates))
    refresh_state(review, candidates)
    return review


def refresh_state(review: PageReview, candidates: list[OcrCandidate]) -> None:
    """Re-derive state and validated text after any decision change."""
    text = compose_text(review, candidates)
    review.validated_text = text
    review.state = "validated" if text is not None else "in_review"
