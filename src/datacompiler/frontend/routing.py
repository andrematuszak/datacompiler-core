"""Select page-level OCR strategies from diagnostic evidence."""

from datacompiler.model.document import Document, Page
from datacompiler.model.metadata import RoutingDecision

NATIVE_TEXT = "native_text"
MIXED_NATIVE_AND_GLYPHS = "mixed_native_and_glyphs"
FULL_PAGE_SCAN = "full_page_scan"
FULL_PAGE_SCAN_HANDWRITING_LIKELY = "full_page_scan_handwriting_likely"
NEEDS_REVIEW = "needs_review"

PRESERVE_NATIVE = "preserve_native"
TARGETED_PADDLE_OCR = "targeted_paddle_ocr"
FULL_PAGE_NVIDIA_OCR = "full_page_nvidia_ocr"
FALLBACK_OR_MANUAL_REVIEW = "fallback_or_manual_review"
SKIP_OCR = "skip_ocr"


def _automatic_route(page: Page) -> RoutingDecision:
    diagnostic = page.diagnostic

    if diagnostic.has_full_page_images and not diagnostic.has_native_text:
        category = (
            FULL_PAGE_SCAN_HANDWRITING_LIKELY
            if diagnostic.handwritten_likely
            else FULL_PAGE_SCAN
        )
        return RoutingDecision(
            category=category,
            strategy=FULL_PAGE_NVIDIA_OCR,
            backend="nvidia",
            reasons=["full_page_image", "no_native_text"],
        )

    if diagnostic.has_native_text and diagnostic.vectorized_text_detected:
        return RoutingDecision(
            category=MIXED_NATIVE_AND_GLYPHS,
            strategy=TARGETED_PADDLE_OCR,
            backend="paddle",
            reasons=["native_text", "vectorized_text"],
        )

    native_text_is_healthy = (
        diagnostic.native_text_quality is None
        or diagnostic.native_text_quality >= 0.9
    ) and (
        diagnostic.native_text_coverage is None
        or diagnostic.native_text_coverage >= 0.9
    )
    if (
        diagnostic.has_native_text
        and native_text_is_healthy
        and not diagnostic.embedded_ocr_detected
        and diagnostic.has_images_with_text is not True
    ):
        return RoutingDecision(
            category=NATIVE_TEXT,
            strategy=PRESERVE_NATIVE,
            reasons=["native_text"],
        )

    return RoutingDecision(
        category=NEEDS_REVIEW,
        strategy=FALLBACK_OR_MANUAL_REVIEW,
        reasons=["available_page_evidence_needs_review"],
    )


def route_page(page: Page, *, ocr_mode: str = "auto") -> RoutingDecision:
    """Apply explicit OCR mode before selecting a strategy from page evidence."""
    if ocr_mode not in {"auto", "skip", "vector"}:
        raise ValueError(f"Unsupported routing OCR mode: {ocr_mode!r}")

    decision = _automatic_route(page)
    if ocr_mode == "skip":
        decision.strategy = SKIP_OCR
        decision.backend = None
        decision.reasons = ["OCR disabled by user request"]
    elif ocr_mode == "vector" and decision.strategy != TARGETED_PADDLE_OCR:
        decision.strategy = PRESERVE_NATIVE
        decision.backend = None
        decision.reasons = ["vector-only mode found no eligible native/vector page"]
    return decision


def route_document(document: Document, *, ocr_mode: str = "auto") -> Document:
    """Attach an OCR routing decision independently to every page."""
    for page in document.pages:
        page.routing = route_page(page, ocr_mode=ocr_mode)
    return document


def format_page_routes(pages) -> list[str]:
    """Format adjacent identical route decisions for concise CLI logging."""
    groups = []
    for page in pages:
        route = page.routing
        if route.category is None or route.strategy is None:
            continue
        label = (route.category, route.strategy)
        if groups and groups[-1][0] == label and groups[-1][2] + 1 == page.number:
            groups[-1][2] = page.number
        else:
            groups.append([label, page.number, page.number])

    lines = []
    for (category, strategy), first, last in groups:
        page_label = f"Page {first}" if first == last else f"Page {first}-{last}"
        lines.append(f"{page_label}: Category: {category}\n          Strategy: {strategy}")
    return lines
