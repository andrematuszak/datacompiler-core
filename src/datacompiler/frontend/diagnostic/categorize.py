"""categorize.py — Catégorie unique dérivée d'un Diagnostic déjà rempli."""

from datacompiler.model.metadata import Diagnostic

SEUIL_HAUT = 0.9

CATEGORIE_NATIF_PROPRE = "natif_propre"
CATEGORIE_NATIF_CORROMPU = "natif_corrompu"
CATEGORIE_SCAN = "scan"


def categoriser(diagnostic: Diagnostic) -> str:
    """Dérive la catégorie depuis les champs déjà calculés par diagnostiquer()."""
    if not diagnostic.has_native_text:
        return CATEGORIE_SCAN
    if diagnostic.embedded_ocr_detected:
        return CATEGORIE_SCAN
    if diagnostic.native_text_quality is not None and diagnostic.native_text_quality < SEUIL_HAUT:
        return CATEGORIE_NATIF_CORROMPU
    return CATEGORIE_NATIF_PROPRE
