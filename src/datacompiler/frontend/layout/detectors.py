"""
detectors.py — Détection géométrique des conteneurs (images, tableaux, zones vectorielles).
"""

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
    """Détecte dynamiquement les zones de texte vectorisé via
    vector_text.py -- EXCLUT les zones dont le centre tombe déjà dans une
    table ou une image détectée (`zones_deja_prises`), pour ne pas
    représenter deux fois le même contenu physique dans l'arbre (table +
    zone vectorielle qui se chevauchent, ex. une ligne d'en-tête de table
    partiellement composée de texte vectorisé -- exactement le cas de la
    table d'en-têtes page 2 du document de test).

    Réutilise dans_un_tableau (geometry.py, même test centre-dans-bbox
    déjà utilisé ailleurs dans le projet) via un petit adaptateur --
    dans_un_tableau attend des objets avec un attribut .bbox, pas des
    dicts bruts comme ceux manipulés ici. Éviter de réimplémenter ce test
    une deuxième fois : c'est exactement le genre de duplication qui a
    fini par diverger ailleurs dans ce projet."""
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


def detecter_toutes_les_zones(page) -> List[Dict[str, Any]]:
    zones = []
    zones.extend(detecter_boites_images(page))
    zones.extend(detecter_boites_tables(page))
    # Zones vectorielles détectées EN DERNIER et filtrées contre les
    # tables/images déjà trouvées -- cf. docstring de
    # detecter_boites_vectorielles pour le cas exact que ça évite.
    zones.extend(detecter_boites_vectorielles(page, zones_deja_prises=zones))
    return zones
