"""Detect geometric page containers such as images, tables, and vector-text regions."""

from types import SimpleNamespace
from typing import Any, Dict, List

from datacompiler.utils.heuristics_geometry import dans_un_tableau
from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.model.geometry import BBox


def detecter_boites_tables(page) -> List[Dict[str, Any]]:
    zones = []
    graphics = getattr(page, "graphics", None)
    tables = getattr(graphics, "tables", []) if graphics else []
    for idx, table in enumerate(tables):
        bbox = getattr(table, "bbox", None)
        zones.append({
            "type": "table",
            "label": f"table_{idx}",
            "bbox": bbox,
            "cell_bboxes": getattr(table, "cell_bboxes", [])
        })
    return zones


def detecter_boites_images(page) -> List[Dict[str, Any]]:
    zones = []
    graphics = getattr(page, "graphics", None)
    images = getattr(graphics, "images", []) if graphics else []
    for idx, img in enumerate(images):
        bbox = getattr(img, "bbox", None)
        zones.append({
            "type": "image",
            "label": f"image_{idx}",
            "bbox": bbox,
        })
    return zones


def detecter_boites_vectorielles(page, zones_deja_prises: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Detect vector-text regions that are not already contained in detected tables or images."""
    zones_deja_prises = zones_deja_prises or []
    bboxes_existantes = [
        SimpleNamespace(bbox=z["bbox"]) for z in zones_deja_prises if z.get("bbox")
    ]

    zones = []
    coords_zones = zones_texte_vectorise_probable(page)
    for idx, (x0, y0, x1, y1) in enumerate(coords_zones):
        bbox = BBox(x0, y0, x1, y1)
        if bboxes_existantes and dans_un_tableau(SimpleNamespace(bbox=bbox), bboxes_existantes):
            continue
        zones.append({
            "type": "vector_zone",
            "label": f"vector_zone_{idx}",
            "bbox": bbox,
        })
    return zones


def _couleur_proche(couleur_hex: str, reference_hex: str, tolerance: int = 12) -> bool:
    """Compare two hexadecimal colors channel by channel within a tolerance."""
    if not couleur_hex or not reference_hex:
        return False
    c = couleur_hex.lstrip("#")
    r = reference_hex.lstrip("#")
    if len(c) != 6 or len(r) != 6:
        return False
    for i in (0, 2, 4):
        if abs(int(c[i:i+2], 16) - int(r[i:i+2], 16)) > tolerance:
            return False
    return True


# Bleu caractéristique observé sur le document de test (avis d'impôt) pour
# les encadrés de section ("Vos références", "Vos contacts") et les liens
# ("impots.gouv.fr") -- RGB float (0.365, 0.565, 0.780) converti en hex.
# Volontairement une constante à ce stade (pas de détection générique
# "toute couleur non noire/blanche") : on n'a qu'un seul document réel
# testé, cf. compile/reading_order.py pour la même prudence méthodologique
# ("pas de champs inventés tant qu'un test réel n'en précise le besoin").
COULEUR_ENCADRE_REFERENCE = "#5d90c7"


def detecter_boites_encadres(page, couleur_reference: str = COULEUR_ENCADRE_REFERENCE,
                              taille_min: float = 5.0) -> List[Dict[str, Any]]:
    """Detect framed section boxes whose vector color is close to the configured reference color."""
    zones = []
    rects = getattr(getattr(page, "graphics", None), "rects", []) or []
    idx = 0
    for vector in rects:
        bbox = getattr(vector, "bbox", None)
        if not bbox:
            continue
        largeur = bbox.x1 - bbox.x0
        hauteur = bbox.y1 - bbox.y0
        if largeur < taille_min or hauteur < taille_min:
            continue
        if not _couleur_proche(getattr(vector, "color", None), couleur_reference):
            continue
        zones.append({
            "type": "encadre",
            "label": f"encadre_{idx}",
            "bbox": bbox,
            "color": vector.color,
        })
        idx += 1
    return zones


def detecter_toutes_les_zones(page) -> List[Dict[str, Any]]:
    zones = []
    zones.extend(detecter_boites_images(page))
    zones.extend(detecter_boites_tables(page))
    # Zones vectorielles détectées EN DERNIER et filtrées contre les
    # tables/images déjà trouvées -- cf. docstring de
    # detecter_boites_vectorielles pour le cas exact que ça évite.
    zones.extend(detecter_boites_vectorielles(page, zones_deja_prises=zones))
    return zones
