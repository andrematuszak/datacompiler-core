# Diagnostic report
"""Human-readable diagnostic report for terminal inspection.

Kept separate from the pure ``diagnose_document`` calculation so displaying a report remains an optional consumer operation rather than a computation step."""

from datacompiler.model.document import Document

_LABEL_WIDTH = 35


def _format_line(label, value):
    return f"  {label:<{_LABEL_WIDTH}} {value}"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _yes_no_or_unknown(value) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def display_report(doc: Document) -> None:
    d = doc.diagnostic
    print("\n" + "=" * 64)
    print(f"DIAGNOSTIC — {doc.metadata.filename}")
    print("=" * 64)

    print(_format_line("Pages", doc.metadata.page_count))
    print(_format_line("Native text present", _yes_no(d.has_native_text)))
    print(_format_line("Native text quality", d.native_text_quality if d.native_text_quality is not None else "n/a"))
    couverture = f"{d.native_text_coverage:.1%}" if d.native_text_coverage is not None else "n/a"
    print(_format_line("Native text coverage", couverture))
    print(_format_line("Reading-order score", d.reading_order_score if d.reading_order_score is not None else "n/a"))
    print(_format_line("Images", _yes_no(d.has_images)))
    print(_format_line("Tables", _yes_no(d.has_tables)))
    print(_format_line("Vectorized text (glyphs)", _yes_no(d.vectorized_text_detected)))
    print(_format_line("Images containing text", _yes_no_or_unknown(d.has_images_with_text)))
    print(_format_line("Full-page images", _yes_no(d.has_full_page_images)))
    print(_format_line("Embedded OCR detected", _yes_no(d.embedded_ocr_detected)))
    print(_format_line("Low-resolution images", _yes_no(d.low_dpi_images_detected)))
    print(_format_line("Overlapping text", _yes_no(d.overlapping_text_detected)))
    print(_format_line("Out-of-bounds coordinates", _yes_no(d.out_of_bounds_detected)))
    print(_format_line("Encrypted", _yes_no(d.encrypted)))
    if d.suspect_producer:
        print(_format_line("Suspicious producer", d.suspect_producer))
    if d.empty_pages:
        print(_format_line("Empty pages", ", ".join(str(p) for p in d.empty_pages)))
    if d.categorie:
        print(_format_line("Category", d.categorie))

    print("-" * 64)
    print(_format_line("SEGMENTATION RECOMMENDATION", "YES" if getattr(d, "recommend_segmentation", False) else "NO"))
    if getattr(d, "segmentation_reasons", []):
        print(_format_line("Segmentation reasons", ", ".join(d.segmentation_reasons)))

    print("-" * 64)
    print(_format_line("OCR RECOMMENDATION", "YES" if d.recommend_ocr else "NO"))
    print(_format_line("Full-page OCR", "YES" if d.recommend_full_ocr else "NO"))
    if d.ocr_reasons:
        print(_format_line("Reasons", ", ".join(d.ocr_reasons)))

    if d.notes:
        print("-" * 64)
        print("Detailed notes:")
        for note in d.notes:
            print(f"  • {note}")
    print("=" * 64 + "\n")



# Backward-compatible aliases for callers using the original French API.
_oui_non = _yes_no
_oui_non_inconnu = _yes_no_or_unknown
afficher = display_report
