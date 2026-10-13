"""Measure image coverage and effective resolution, and report whether extracted images are known to contain text."""

from typing import Optional

SEUIL_COUVERTURE_PLEINE_PAGE = 0.85
SEUIL_DPI_BAS = 150
COUVERTURE_MIN_POUR_DPI = 0.10  # ignore les petites icônes/logos


def couverture_image_max(page) -> float:
    surface_page = page.width * page.height
    if not surface_page:
        return 0.0
    couverture = 0.0
    for img in page.graphics.images:
        if not img.bbox:
            continue
        largeur = img.bbox.x1 - img.bbox.x0
        hauteur = img.bbox.y1 - img.bbox.y0
        couverture = max(couverture, (largeur * hauteur) / surface_page)
    return couverture


def dpi_effectif(img) -> Optional[float]:
    """Compute effective image resolution from pixel dimensions and PDF-point bounds."""
    if not img.bbox or not img.width:
        return None
    largeur_pouces = (img.bbox.x1 - img.bbox.x0) / 72.0
    return img.width / largeur_pouces if largeur_pouces else None


def images_basse_resolution(page) -> list:
    """Return significant page images whose effective resolution is low."""
    surface_page = page.width * page.height
    resultat = []
    for img in page.graphics.images:
        if not img.bbox or not surface_page:
            continue
        couverture = ((img.bbox.x1 - img.bbox.x0) * (img.bbox.y1 - img.bbox.y0)) / surface_page
        if couverture < COUVERTURE_MIN_POUR_DPI:
            continue
        dpi = dpi_effectif(img)
        if dpi is not None and dpi < SEUIL_DPI_BAS:
            resultat.append((img, dpi))
    return resultat


# --- Images avec texte --------------------------------------------------
# NE CALCULE RIEN À PARTIR DES PIXELS ICI -- cette fonction lit un champ
# déjà peuplé côté extraction (ImageElement.contains_text: Optional[bool],
# None = pas encore analysé/inconnu). diagnostic.py ne rouvre jamais le
# PDF (cf. container.py, ce fichier ci-dessus) ; détecter du texte dans une
# image nécessite d'inspecter les pixels, donc ce calcul doit se faire
# PENDANT l'extraction (le PDF est encore ouvert à ce moment-là), pas ici.
# Tant que ce champ n'existe pas côté extraction, cette fonction retourne
# toujours None (inconnu) pour chaque image -- comportement explicite
# plutôt qu'un faux "non" qui masquerait l'absence de données.

def images_avec_texte(page) -> Optional[bool]:
    """Return True, False, or None depending on whether image text presence is known."""
    statuts = [getattr(img, "contains_text", None) for img in page.graphics.images]
    statuts = [s for s in statuts if s is not None]
    if not statuts:
        return None
    return any(statuts)

