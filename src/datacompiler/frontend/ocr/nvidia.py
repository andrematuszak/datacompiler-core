"""Run full-page OCR with NVIDIA Nemotron through the OpenRouter chat API."""

import base64
import logging
import os
import time

import pymupdf

from datacompiler.frontend.ocr.base import OcrBackend
from datacompiler.model.document import Document, OcrBlock, Word

logger = logging.getLogger(__name__)

MODEL_NAME = "nvidia/nemotron-3.5-super-vl:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
RENDER_DPI = 200
MAX_TOKENS = 4096
RETRYABLE_STATUS_CODES = {402, 429}
RETRY_DELAY_SECONDS = 10
OCR_PROMPT = (
    "Transcribe all text in this document image exactly as written. "
    "Preserve the original language, line breaks, and paragraph structure. "
    "Output only the transcription, with no explanation."
)


def _response_text(response) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        raise RuntimeError("OpenRouter returned no OCR completion choices.")
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


def _status_code(error) -> int | None:
    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        return status_code
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None)


class NvidiaBackend(OcrBackend):
    """Use OpenRouter's free Nemotron vision-language model for page OCR."""

    name = "nvidia"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")

    def _transcribe_page(
        self,
        client,
        image_data_url: str,
        status_error_type: type[Exception],
    ) -> str:
        request = {
            "model": MODEL_NAME,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url},
                        },
                        {"type": "text", "text": OCR_PROMPT},
                    ],
                }
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        }

        try:
            response = client.chat.completions.create(**request)
        except status_error_type as error:
            if _status_code(error) not in RETRYABLE_STATUS_CODES:
                raise
            logger.warning(
                "OpenRouter rate/payment limit reached; retrying once in %s seconds.",
                RETRY_DELAY_SECONDS,
            )
            time.sleep(RETRY_DELAY_SECONDS)
            response = client.chat.completions.create(**request)
        return _response_text(response)

    def ocraliser(
        self,
        doc: Document,
        pdf_path: str,
        pages: list[int] | None = None,
        **kwargs,
    ) -> Document:
        api_key = kwargs.get("api_key") or self.api_key
        if not api_key:
            raise ValueError(
                "Missing OpenRouter API key. Set OPENROUTER_API_KEY or pass "
                "api_key when creating the NVIDIA OCR backend."
            )

        page_numbers = sorted(set(pages)) if pages is not None else [
            page.number for page in doc.pages
        ]
        if not page_numbers:
            return doc
        if any(number < 1 or number > len(doc.pages) for number in page_numbers):
            raise ValueError(
                "OCR page numbers must be within the document's 1-based page range."
            )

        try:
            from openai import APIStatusError, OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "NVIDIA OCR requires the OpenAI client; install datacompiler[openai]."
            ) from exc

        client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            max_retries=0,
        )
        with pymupdf.open(pdf_path) as source:
            for page_number in page_numbers:
                page = source[page_number - 1]
                pixmap = page.get_pixmap(dpi=RENDER_DPI, alpha=False)
                image_data = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
                transcription = self._transcribe_page(
                    client,
                    f"data:image/png;base64,{image_data}",
                    APIStatusError,
                )

                page_obj = doc.pages[page_number - 1]
                page_obj.ocr.engine = MODEL_NAME
                page_obj.ocr.words = [
                    Word(
                        id=token_id,
                        text=token,
                        resolved_text=token,
                        source="ocr",
                    )
                    for token_id, token in enumerate(transcription.split(), start=1)
                ]
                page_obj.ocr.blocks = [
                    OcrBlock(
                        type="markdown",
                        content=transcription,
                        metadata={
                            "source": "openrouter",
                            "model": MODEL_NAME,
                            "render_dpi": RENDER_DPI,
                        },
                    )
                ]
                logger.debug("Completed NVIDIA OCR for page %s", page_number)

        return doc
