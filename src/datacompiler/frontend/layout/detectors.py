"""
detectors.py — Détection géométrique des conteneurs (images, tableaux, zones vectorielles).
"""

from typing import Any, Dict, List
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


def detecter_boites_vectorielles(page) -> List[Dict[str, Any]]:
    """Détecte dynamiquement les zones de texte vectorisé via vector_text.py."""
    zones = []
    coords_zones = zones_texte_vectorise_probable(page)
    for idx, (x0, y0, x1, y1) in enumerate(coords_zones):
        zones.append({
            "type": "vector_zone",
            "label": f"vector_zone_{idx}",
            "bbox": BBox(x0, y0, x1, y1),
        })
    return zones


def detecter_toutes_les_zones(page) -> List[Dict[str, Any]]:
    zones = []
    zones.extend(detecter_boites_images(page))
    zones.extend(detecter_boites_tables(page))
    zones.extend(detecter_boites_vectorielles(page))
    return zones
