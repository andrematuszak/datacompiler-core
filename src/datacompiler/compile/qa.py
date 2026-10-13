"""Detect post-resolution anomalies and annotate ``resolved.words`` with flags. Checks do not modify word text or bounding boxes."""

from datacompiler.model.document import Flag

from datacompiler.utils.heuristics_geometry import dans_un_tableau

# Valeur de départ arbitraire, non calibrée -- cf. roadmap (étape
# calibration confidence vs exactitude réelle sur échantillon annoté).
SEUIL_CONFIANCE_A_VERIFIER = 0.6


def _confiance_basse(mots: list) -> None:
    """Add a low-confidence flag to words with a confidence score below the configured threshold."""
    for mot in mots:
        if mot.confidence is not None and mot.confidence < SEUIL_CONFIANCE_A_VERIFIER:
            mot.flags.append(Flag(
                type="confiance_basse",
                detail=f"confidence={mot.confidence:.2f} < seuil {SEUIL_CONFIANCE_A_VERIFIER}",
                severity="warning",
            ))

def _ordre_suspect(mots: list, tables: list, seuil_regression: float = 50.0) -> None:
    """Flag significant backward jumps in the final vertical reading order."""
    max_y_vu = None
    for mot in mots:
        if not mot.bbox or dans_un_tableau(mot, tables):
            continue
        if max_y_vu is not None and mot.bbox.y0 < max_y_vu - seuil_regression:
            mot.flags.append(Flag(
                type="ordre_suspect",
                detail=f"y0={mot.bbox.y0:.0f} après un maximum déjà atteint de {max_y_vu:.0f} "
                       f"-- saut arrière possible dans l'ordre de lecture",
                severity="warning",
            ))
        max_y_vu = mot.bbox.y0 if max_y_vu is None else max(max_y_vu, mot.bbox.y0)


def annoter(mots: list, tables: list) -> list:
    """Annotate resolved words in place with quality flags and return the same list."""
    _confiance_basse(mots)
    _ordre_suspect(mots, tables)
    return mots