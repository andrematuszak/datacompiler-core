"""Select page-level OCR strategies from diagnostic evidence.

This module consumes diagnostics rather than producing them. New backends and
user overrides can be added here without weakening the diagnostic record.
"""

from datacompiler.model.document import Document, Page
from datacompiler.model.metadata import RoutingDecision


def route_page(page: Page) -> RoutingDecision:
    """Return the default OCR route for one diagnosed page."""
    diagnostic = page.diagnostic

    if diagnostic.has_full_page_images and not diagnostic.has_native_text:
        category = (
            "full_page_scan_handwriting_likely"
            if diagnostic.handwritten_likely
            else "full_page_scan"
        )
        return RoutingDecision(
            category=category,
            strategy="full_page_mistral_ocr",
            backend="mistral",
            reasons=["full_page_image", "no_native_text"],
        )

    if diagnostic.has_native_text and diagnostic.vectorized_text_detected:
        return RoutingDecision(
            category="mixed_native_and_glyphs",
            strategy="targeted_paddle_ocr",
            backend="paddle",
            reasons=["native_text", "vectorized_text"],
        )

    if diagnostic.has_native_text:
        return RoutingDecision(
            category="native_text",
            strategy="preserve_native",
            reasons=["native_text"],
        )

    return RoutingDecision(
        category="needs_review",
        strategy="fallback_or_manual_review",
        reasons=["no_native_text", "no_full_page_image"],
    )


def route_document(document: Document) -> Document:
    """Attach a default routing decision to every page in ``document``."""
    for page in document.pages:
        page.routing = route_page(page)
    return document
