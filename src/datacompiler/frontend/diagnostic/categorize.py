"""Derive a single page category and segmentation recommendation from already-computed diagnostic signals. This module does not reopen or reprocess the PDF."""

from typing import Optional

SEUIL_QUALITE_CORROMPU = 0.9

CATEGORIE_NATIF_PROPRE = "natif_propre"
CATEGORIE_NATIF_CORROMPU = "natif_corrompu"
CATEGORIE_NATIF_MIXTE = "natif_mixte"
CATEGORIE_SCAN = "scan"

SEUIL_COUVERTURE_MIXTE = 0.9


def categoriser(
    has_native_text: bool,
    embedded_ocr_detected: bool,
    native_text_quality: Optional[float],
    native_text_coverage: Optional[float] = None,
) -> str:
    """Derive one page category from already-computed diagnostic signals."""
    if not has_native_text:
        return CATEGORIE_SCAN
    if embedded_ocr_detected:
        return CATEGORIE_SCAN
    if native_text_quality is not None and native_text_quality < SEUIL_QUALITE_CORROMPU:
        return CATEGORIE_NATIF_CORROMPU
    if native_text_coverage is not None and native_text_coverage < SEUIL_COUVERTURE_MIXTE:
        return CATEGORIE_NATIF_MIXTE
    return CATEGORIE_NATIF_PROPRE


def evaluer_segmentation_page(page, diag_page):
    """Decide whether an individual page needs macro-segmentation."""
    reasons = []

    graphics = getattr(page, "graphics", None)
    tables = getattr(graphics, "tables", []) if graphics else []
    if len(tables) > 0:
        reasons.append("tables detected")

    vector_zones = getattr(page, "vector_zones", [])
    if getattr(diag_page, "vectorized_text_detected", False) or len(vector_zones) > 0:
        reasons.append("vectorized text present")

    images = getattr(graphics, "images", []) if graphics else []
    if images:
        reasons.append("images detected")

    reading_score = getattr(diag_page, "reading_order_score", None)
    if reading_score is not None and reading_score < 0.8:
        reasons.append("native text has spatial disorder")

    if reasons:
        diag_page.recommend_segmentation = True
        diag_page.segmentation_reasons = reasons
    else:
        diag_page.recommend_segmentation = False
        diag_page.segmentation_reasons = []
