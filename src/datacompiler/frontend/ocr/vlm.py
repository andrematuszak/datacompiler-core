"""Coordinate full-page transcriptions from one or more OpenRouter VLMs.

This module returns OCR candidates and a review state. It does not own a
single-model ``OcrBackend`` slot: NVIDIA keeps that adapter for compatibility.
Confidence is recorded only when the provider returns token logprobs.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Optional

import pymupdf

from datacompiler.model.document import Document, OcrBlock, OcrCandidate, Word
from datacompiler.review.divergence import build_review

logger = logging.getLogger(__name__)

NVIDIA_MODEL_NAME = "nvidia/nemotron-3.5-super-vl:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
RENDER_DPI = 200
MAX_TOKENS = 4096
RETRY_DELAY_SECONDS = 10
# Free OpenRouter models are often saturated: wait 10 s, then 30 s, before giving up.
RETRY_DELAYS_SECONDS = (RETRY_DELAY_SECONDS, 3 * RETRY_DELAY_SECONDS)
# Provider-side hiccups worth retrying (free models often answer 502/503).
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
# Errors that concern one model only: skip it and keep the other models running.
# 401/403 (bad key) are deliberately absent: they affect every model and abort.
SKIPPABLE_STATUS_CODES = TRANSIENT_STATUS_CODES | {400, 402, 404, 422}
ILLEGIBLE_MARKER = "[?]"

OCR_PROMPT = (
    "Transcribe all text in this document image exactly as written. "
    "Preserve the original language, line breaks, and paragraph structure. "
    "Output only the transcription, with no explanation."
)
HANDWRITING_PROMPT = (
    "Transcribe all handwritten and printed text in this document image "
    "exactly as written. "
    "Preserve the original language, line breaks, and paragraph structure. "
    f"If a word is unreadable, write {ILLEGIBLE_MARKER} instead of guessing. "
    "Output only the transcription, with no explanation."
)


def default_vlm_models() -> list[str]:
    """NVIDIA by default; override with comma-separated DATACOMPILER_VLM_MODELS."""
    configured = os.getenv("DATACOMPILER_VLM_MODELS", "")
    models = [item.strip() for item in configured.split(",") if item.strip()]
    return models or [NVIDIA_MODEL_NAME]


def prompt_for_page(*, handwriting: bool = False) -> str:
    return HANDWRITING_PROMPT if handwriting else OCR_PROMPT


def status_code(error) -> int | None:
    code = getattr(error, "status_code", None)
    if code is not None:
        return code
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None)


def openrouter_client(api_key: str):
    """Return ``(client, APIStatusError)`` talking to OpenRouter."""
    try:
        from openai import APIStatusError, OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "VLM OCR requires the OpenAI client; install datacompiler[openai]."
        ) from exc
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key,
        max_retries=0,
    )
    return client, APIStatusError


def render_page_png_data_url(page, dpi: int = RENDER_DPI) -> str:
    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    image_data = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
    return f"data:image/png;base64,{image_data}"


class EmptyCompletionError(RuntimeError):
    """OpenRouter answered without any completion choice (often an upstream error)."""


def upstream_error_detail(response) -> str:
    """Return the provider error OpenRouter put in the body of a choice-less reply."""
    error = getattr(response, "error", None)
    if error is None:
        error = (getattr(response, "model_extra", None) or {}).get("error")
    return str(error) if error else ""


def response_text(response) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        detail = upstream_error_detail(response)
        raise EmptyCompletionError(
            "OpenRouter returned no OCR completion choices."
            + (f" Upstream error: {detail}" if detail else "")
        )
    content = getattr(getattr(choices[0], "message", None), "content", None)
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
    else:
        text = ""
    if not text:
        raise RuntimeError("OpenRouter returned an empty OCR transcription.")
    return text


def _raw_payload(response) -> str:
    dump = getattr(response, "model_dump_json", None)
    if callable(dump):
        return dump()
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        return repr(dump())
    return response_text(response)


def raw_sha256(response) -> str:
    return hashlib.sha256(_raw_payload(response).encode("utf-8")).hexdigest()


def _token_logprob(token) -> Optional[float]:
    if token is None:
        return None
    if isinstance(token, dict):
        value = token.get("logprob")
    else:
        value = getattr(token, "logprob", None)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def logprob_confidence(response) -> tuple[Optional[float], Optional[str]]:
    """Mean token logprob when the provider returned it; never a guessed score."""
    choices = getattr(response, "choices", None)
    if not choices:
        return None, None
    logprobs = getattr(choices[0], "logprobs", None)
    if not logprobs:
        return None, None
    content = getattr(logprobs, "content", None)
    if isinstance(logprobs, dict):
        content = logprobs.get("content", content)
    values = [_token_logprob(token) for token in content or []]
    values = [value for value in values if value is not None]
    if not values:
        return None, None
    return sum(values) / len(values), "mean_token_logprob"


def _candidate_id(model: str) -> str:
    name = model.split("/")[-1].split(":")[0]
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return slug or "model"


def _completion_request(model: str, image_data_url: str, prompt: str, *, logprobs: bool) -> dict[str, Any]:
    request: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
    }
    if logprobs:
        request["logprobs"] = True
        request["top_logprobs"] = 5
    return request


def _looks_like_logprob_rejection(error) -> bool:
    code = status_code(error)
    if code in {400, 422}:
        return True
    message = str(error).lower()
    return "logprob" in message


def transcribe_image(
    client,
    image_data_url: str,
    model: str,
    prompt: str,
    *,
    status_error_type: type[Exception],
    retry_429: bool = False,
    request_logprobs: bool = True,
    candidate_id: Optional[str] = None,
) -> OcrCandidate:
    """Call one VLM. ``402`` is never retried.

    Recovers from the failures seen with free OpenRouter models: a transient error such as 429 or
    502 (two retries with growing pauses when asked), a provider that rejects ``logprobs``, and an HTTP 200
    reply that carries an upstream error and no choices (retried once without
    logprobs, then after growing pauses when ``retry_429``).
    """
    use_logprobs = request_logprobs
    waits = 0
    for _ in range(6):
        request = _completion_request(model, image_data_url, prompt, logprobs=use_logprobs)
        try:
            response = client.chat.completions.create(**request)
        except status_error_type as error:
            code = status_code(error)
            if code == 402:
                raise
            if code in TRANSIENT_STATUS_CODES and retry_429 and waits < len(RETRY_DELAYS_SECONDS):
                delay = RETRY_DELAYS_SECONDS[waits]
                waits += 1
                logger.warning(
                    "OpenRouter error %s on %s; retrying in %s seconds (%s/%s).",
                    code,
                    model,
                    delay,
                    waits,
                    len(RETRY_DELAYS_SECONDS),
                )
                time.sleep(delay)
                continue
            if use_logprobs and _looks_like_logprob_rejection(error):
                use_logprobs = False
                continue
            raise
        if getattr(response, "choices", None):
            break
        detail = upstream_error_detail(response)
        logger.warning("%s returned no completion choices. %s", model, detail)
        if use_logprobs:
            use_logprobs = False
            continue
        if retry_429 and waits < len(RETRY_DELAYS_SECONDS):
            time.sleep(RETRY_DELAYS_SECONDS[waits])
            waits += 1
            continue
        break
    else:
        raise EmptyCompletionError(f"{model} kept failing without a completion.")

    text = response_text(response)
    confidence, confidence_kind = logprob_confidence(response)
    return OcrCandidate(
        id=candidate_id or _candidate_id(model),
        model=model,
        text=text,
        confidence=confidence,
        confidence_kind=confidence_kind,
        raw_sha256=raw_sha256(response),
        metadata={
            "prompt_kind": "handwriting" if prompt == HANDWRITING_PROMPT else "print",
            "logprobs_requested": use_logprobs,
        },
    )


def transcribe_with_models(
    client,
    image_data_url: str,
    models: Iterable[str],
    prompt: str,
    *,
    status_error_type: type[Exception],
    report: Optional[list[dict[str, Any]]] = None,
) -> list[OcrCandidate]:
    """Run every configured model. A 402 skips immediately to the next model.

    When ``report`` is given, one entry per model records ``ok`` or ``failed``
    with the reason, so a silently skipped model is visible afterwards.
    """
    report = report if report is not None else []
    candidates: list[OcrCandidate] = []
    used_ids: set[str] = set()
    for model in models:
        base_id = _candidate_id(model)
        candidate_id = base_id
        suffix = 2
        while candidate_id in used_ids:
            candidate_id = f"{base_id}-{suffix}"
            suffix += 1
        try:
            candidate = transcribe_image(
                client,
                image_data_url,
                model,
                prompt,
                status_error_type=status_error_type,
                retry_429=True,
                candidate_id=candidate_id,
            )
        except status_error_type as error:
            code = status_code(error)
            if code in SKIPPABLE_STATUS_CODES:
                logger.warning(
                    "OpenRouter error %s on %s; trying the next model: %s",
                    code, model, str(error)[:300],
                )
                report.append({"model": model, "status": "failed", "error": f"HTTP {code}: {error}"[:500]})
                continue
            report.append({"model": model, "status": "failed", "error": f"HTTP {code}: {error}"[:500]})
            raise
        except RuntimeError as error:
            logger.warning("Model %s returned no transcription: %s", model, error)
            report.append({"model": model, "status": "failed", "error": str(error)[:500]})
            continue
        used_ids.add(candidate.id)
        candidates.append(candidate)
        report.append({"model": model, "status": "ok", "candidate_id": candidate.id})
    if not candidates:
        failures = "; ".join(
            f"{item['model']}: {item.get('error', '')}"
            for item in report
            if item["status"] == "failed"
        )
        raise RuntimeError(
            "No VLM produced a transcription for this page."
            + (f" Failures: {failures}" if failures else "")
        )
    return candidates


def fill_provisional_ocr(
    page,
    text: str,
    *,
    engine: str,
    extra_metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Populate ``words``/``blocks`` for downstream language detection and export."""
    page.ocr.engine = engine
    page.ocr.words = [
        Word(id=token_id, text=token, resolved_text=token, source="ocr")
        for token_id, token in enumerate(text.split(), start=1)
    ]
    metadata = {
        "source": "openrouter",
        "model": engine,
        "render_dpi": RENDER_DPI,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    page.ocr.blocks = [
        OcrBlock(type="markdown", content=text, metadata=metadata)
    ]


def apply_single_model_ocr(page, candidate: OcrCandidate) -> None:
    """NVIDIA-compatible write: one engine, split words, markdown block, one candidate."""
    page.ocr.candidates = [candidate]
    page.review = build_review(page.ocr.candidates)
    fill_provisional_ocr(page, candidate.text, engine=candidate.model)


def apply_candidates(page, candidates: list[OcrCandidate]) -> None:
    """Store candidates, build the review, and fill a provisional OCR layer."""
    page.ocr.candidates = list(candidates)
    if not candidates:
        return
    page.review = build_review(candidates)
    text = page.review.validated_text
    if text is None:
        reference_id = page.review.reference_candidate_id or candidates[0].id
        text = next(
            (item.text for item in candidates if item.id == reference_id),
            candidates[0].text,
        )
    engine = candidates[0].model if len(candidates) == 1 else "openrouter-vlm"
    fill_provisional_ocr(
        page,
        text,
        engine=engine,
        extra_metadata={
            "review_state": page.review.state,
            "provisional": page.review.state == "in_review",
            "models": [item.model for item in candidates],
        },
    )


def write_debug_report(
    debug_dir: str | os.PathLike,
    page_number: int,
    *,
    configured_models: list[str],
    models_source: str,
    report: list[dict[str, Any]],
    candidates: list[OcrCandidate],
    review,
) -> Path:
    """Write what each model returned and how the review state was derived.

    Produces ``page<N>_report.json`` and one ``page<N>_<candidate>.txt`` per
    candidate (raw text, line breaks preserved) so two models can be diffed.
    """
    folder = Path(debug_dir)
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "page": page_number,
        "configured_models": configured_models,
        "models_source": models_source,
        "model_results": report,
        "candidates": [
            {**dataclasses.asdict(item), "word_count": len(item.text.split())}
            for item in candidates
        ],
        "review": dataclasses.asdict(review) if review is not None else None,
    }
    path = folder / f"page{page_number}_report.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for item in candidates:
        (folder / f"page{page_number}_{item.id}.txt").write_text(item.text, encoding="utf-8")
    return path


def resolve_api_key(api_key: Optional[str] = None) -> str:
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise ValueError(
            "Missing OpenRouter API key. Set OPENROUTER_API_KEY or pass "
            "api_key when creating the VLM OCR backend."
        )
    return key


def ocraliser_pages(
    doc: Document,
    pdf_path: str,
    pages: list[int] | None = None,
    *,
    models: Optional[Iterable[str]] = None,
    api_key: Optional[str] = None,
    handwriting_pages: Optional[Iterable[int]] = None,
) -> Document:
    """Transcribe selected pages with every configured VLM and attach a review."""
    api_key = resolve_api_key(api_key)
    models_source = (
        "argument" if models is not None
        else "env" if os.getenv("DATACOMPILER_VLM_MODELS", "").strip()
        else "default"
    )
    model_list = list(models) if models is not None else default_vlm_models()
    debug_dir = os.getenv("DATACOMPILER_VLM_DEBUG_DIR")
    if not model_list:
        raise ValueError("At least one VLM model identifier is required.")
    handwritten = set(handwriting_pages or ())
    page_numbers = sorted(set(pages)) if pages is not None else [
        page.number for page in doc.pages
    ]
    if not page_numbers:
        return doc
    if any(number < 1 or number > len(doc.pages) for number in page_numbers):
        raise ValueError(
            "OCR page numbers must be within the document's 1-based page range."
        )

    client, status_error_type = openrouter_client(api_key)
    with pymupdf.open(pdf_path) as source:
        for page_number in page_numbers:
            image_data_url = render_page_png_data_url(source[page_number - 1])
            page = doc.pages[page_number - 1]
            prompt = prompt_for_page(handwriting=page_number in handwritten)
            report: list[dict[str, Any]] = []
            try:
                candidates = transcribe_with_models(
                    client,
                    image_data_url,
                    model_list,
                    prompt,
                    status_error_type=status_error_type,
                    report=report,
                )
            except Exception:
                if debug_dir:
                    failed = write_debug_report(
                        debug_dir,
                        page_number,
                        configured_models=model_list,
                        models_source=models_source,
                        report=report,
                        candidates=[],
                        review=None,
                    )
                    logger.warning("VLM debug report (failure) written to %s", failed)
                raise
            apply_candidates(page, candidates)
            if len(candidates) < len(model_list):
                logger.warning(
                    "Page %s: only %s of %s configured VLMs produced a transcription.",
                    page_number, len(candidates), len(model_list),
                )
            if models_source == "default" and len(model_list) == 1:
                logger.warning(
                    "Only one VLM is configured (%s); set DATACOMPILER_VLM_MODELS "
                    "to compare several models and enable review.",
                    model_list[0],
                )
            if debug_dir:
                written = write_debug_report(
                    debug_dir,
                    page_number,
                    configured_models=model_list,
                    models_source=models_source,
                    report=report,
                    candidates=candidates,
                    review=page.review,
                )
                logger.warning("VLM debug report written to %s", written)
            logger.debug(
                "Completed VLM OCR for page %s with %s candidate(s), review=%s",
                page_number,
                len(candidates),
                page.review.state,
            )
    return doc
