"""Select an OCR strategy independently for each diagnosed page."""

from datacompiler.model.document import OcrRouting

NATIVE_TEXT = "native_text"
MIXED_NATIVE_AND_GLYPHS = "mixed_native_and_glyphs"
FULL_PAGE_SCAN_HANDWRITING_LIKELY = "full_page_scan_handwriting_likely"
NEEDS_REVIEW = "needs_review"

NO_OCR = "no_ocr"
TARGETED_PADDLE_OCR = "targeted_paddle_ocr"
FULL_PAGE_MISTRAL_OCR = "full_page_mistral_ocr"
FALLBACK_OR_MANUAL_REVIEW = "fallback_or_manual_review"
SKIP_OCR = "skip_ocr"


def _automatic_route(page) -> OcrRouting:
    diagnostic = page.diagnostic
    if (
        not diagnostic.has_native_text
        and diagnostic.has_full_page_images
        and diagnostic.handwritten_likely
    ):
        return OcrRouting(
            category=FULL_PAGE_SCAN_HANDWRITING_LIKELY,
            strategy=FULL_PAGE_MISTRAL_OCR,
            backend="mistral",
            reasons=["full-page image scan without native text or detected tables"],
        )

    if diagnostic.has_native_text and diagnostic.vectorized_text_detected:
        return OcrRouting(
            category=MIXED_NATIVE_AND_GLYPHS,
            strategy=TARGETED_PADDLE_OCR,
            backend="paddle",
            reasons=["native text and vectorized glyphs are both present"],
        )

    if (
        diagnostic.has_native_text
        and not diagnostic.embedded_ocr_detected
        and (diagnostic.native_text_quality is None or diagnostic.native_text_quality >= 0.9)
        and (diagnostic.native_text_coverage is None or diagnostic.native_text_coverage >= 0.9)
        and not diagnostic.vectorized_text_detected
        and diagnostic.has_images_with_text is not True
    ):
        return OcrRouting(
            category=NATIVE_TEXT,
            strategy=NO_OCR,
            reasons=["native text is present and no OCR concern was detected"],
        )

    return OcrRouting(
        category=NEEDS_REVIEW,
        strategy=FALLBACK_OR_MANUAL_REVIEW,
        reasons=["available page evidence does not match a supported automatic strategy"],
    )


def route_page(page, *, ocr_mode: str = "auto") -> OcrRouting:
    """Apply explicit OCR mode before selecting a strategy from page evidence."""
    if ocr_mode == "skip":
        automatic = _automatic_route(page)
        return OcrRouting(
            category=automatic.category,
            strategy=SKIP_OCR,
            reasons=["OCR disabled by user request"],
        )
    if ocr_mode not in {"auto", "vector"}:
        raise ValueError(f"Unsupported routing OCR mode: {ocr_mode!r}")

    automatic = _automatic_route(page)
    if ocr_mode == "vector":
        diagnostic = page.diagnostic
        if diagnostic.has_native_text and diagnostic.vectorized_text_detected:
            return automatic
        return OcrRouting(
            category=automatic.category,
            strategy=NO_OCR,
            reasons=["vector-only mode found no eligible native/vector page"],
        )
    return automatic


def format_page_routes(pages) -> list[str]:
    """Format adjacent identical route decisions for concise CLI logging."""
    groups = []
    for page in pages:
        route = page.routing
        if route is None:
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
