"""categorize.py — Catégorie unique dérivée d'un Diagnostic déjà rempli.
Calcule un champ catégoriel UNIQUE à partir d'un Diagnostic déjà rempli par ton diagnostic.py existant (peu importe
qu'il soit au niveau Document ou Page).

Pourquoi un fichier séparé plutôt que recalculer dans resolve.py et dans
faithful_pdf.py chacun de leur côté : c'est justement ce qui arriverait
sinon -- deux dérivations indépendantes de "est-ce que cette page est
propre/corrompue/scannée" à partir des mêmes champs bruts
(recommend_ocr, embedded_ocr_detected, has_native_text...), qui peuvent
diverger silencieusement le jour où un seuil change dans un seul des deux
fichiers. Ici, une seule fonction, un seul endroit à modifier.

Usage (ne modifie rien tant que tu ne l'appelles pas explicitement) :
    from .categorize import categoriser

    doc.diagnostic.categorie = categoriser(
        has_native_text=doc.diagnostic.has_native_text,
        embedded_ocr_detected=doc.diagnostic.embedded_ocr_detected,
        native_text_quality=doc.diagnostic.native_text_quality,
        native_text_coverage=doc.diagnostic.native_text_coverage,
    )
"""

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
    """Dérive une catégorie unique depuis les signaux déjà calculés.

    ``natif_propre`` veut dire texte lisible *et* couverture native suffisante,
    pas seulement « du texte natif existe ».
    """
    if not has_native_text:
        return CATEGORIE_SCAN
    if embedded_ocr_detected:
        return CATEGORIE_SCAN
    if native_text_quality is not None and native_text_quality < SEUIL_QUALITE_CORROMPU:
        return CATEGORIE_NATIF_CORROMPU
    if native_text_coverage is not None and native_text_coverage < SEUIL_COUVERTURE_MIXTE:
        return CATEGORIE_NATIF_MIXTE
    return CATEGORIE_NATIF_PROPRE
