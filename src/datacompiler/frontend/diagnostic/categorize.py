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
    from diagnostic_categorie import categoriser

    diagnostiquer(doc)                       # ton diagnostic.py, inchangé
    doc.diagnostic.categorie = categoriser(doc.diagnostic)
"""

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
