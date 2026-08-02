"""visual_integrity.py — Couverture image pleine page + DPI effectif."""

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
    """DPI = pixels / pouces. La bbox PDF est en points (1/72 pouce)."""
    if not img.bbox or not img.width:
        return None
    largeur_pouces = (img.bbox.x1 - img.bbox.x0) / 72.0
    return img.width / largeur_pouces if largeur_pouces else None


def images_basse_resolution(page) -> list:
    """Images significatives (>10% de la page, pour ignorer les icônes)
    dont le DPI effectif est bas -- signal d'alerte pour la fiabilité
    d'un futur OCR."""
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
    """True si au moins une image de la page est signalée comme contenant
    du texte, False si toutes sont signalées comme n'en contenant pas,
    None si l'information n'est disponible pour aucune image (champ pas
    encore peuplé côté extraction, ou aucune image sur la page)."""
    statuts = [getattr(img, "contains_text", None) for img in page.graphics.images]
    statuts = [s for s in statuts if s is not None]
    if not statuts:
        return None
    return any(statuts)

