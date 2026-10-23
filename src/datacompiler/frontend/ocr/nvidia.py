"""Run full-page OCR with NVIDIA Nemotron through the OpenRouter chat API."""

import logging
import os
import time

import pymupdf

from datacompiler.frontend.ocr.base import OcrBackend
from datacompiler.frontend.ocr import vlm
from datacompiler.model.document import Document

logger = logging.getLogger(__name__)

MODEL_NAME = vlm.NVIDIA_MODEL_NAME
OPENROUTER_BASE_URL = vlm.OPENROUTER_BASE_URL
RENDER_DPI = vlm.RENDER_DPI
MAX_TOKENS = vlm.MAX_TOKENS
RETRYABLE_STATUS_CODES = {429}
RETRY_DELAY_SECONDS = vlm.RETRY_DELAY_SECONDS
OCR_PROMPT = vlm.OCR_PROMPT


class NvidiaBackend(OcrBackend):
    """Use OpenRouter's free Nemotron vision-language model for page OCR."""

    name = "nvidia"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")

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

        client, APIStatusError = vlm.openrouter_client(api_key)
        with pymupdf.open(pdf_path) as source:
            for page_number in page_numbers:
                image_data_url = vlm.render_page_png_data_url(source[page_number - 1])
                try:
                    candidate = vlm.transcribe_image(
                        client,
                        image_data_url,
                        MODEL_NAME,
                        OCR_PROMPT,
                        status_error_type=APIStatusError,
                        retry_429=False,
                        request_logprobs=False,
                    )
                except APIStatusError as error:
                    if vlm.status_code(error) not in RETRYABLE_STATUS_CODES:
                        raise
                    logger.warning(
                        "OpenRouter rate/payment limit reached; retrying once in %s seconds.",
                        RETRY_DELAY_SECONDS,
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                    candidate = vlm.transcribe_image(
                        client,
                        image_data_url,
                        MODEL_NAME,
                        OCR_PROMPT,
                        status_error_type=APIStatusError,
                        retry_429=False,
                        request_logprobs=False,
                    )

                page_obj = doc.pages[page_number - 1]
                vlm.apply_single_model_ocr(page_obj, candidate)
                logger.debug("Completed NVIDIA OCR for page %s", page_number)

        return doc
