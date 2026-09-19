"""
Module de construction de l'arbre de mise en page (LayoutTree).
Instancie les objets LayoutBox et génère le nœud racine page.layout_root.
"""

from typing import List
from datacompiler.model.document import LayoutBox
from datacompiler.model.geometry import BBox
from datacompiler.frontend.layout.detectors import detecter_toutes_les_zones


def construire_boite_depuis_zone(zone_desc: dict, index: int) -> LayoutBox:
    """Instancie une LayoutBox à partir d'un dictionnaire descriptif issu des détecteurs."""
    b_type = zone_desc.get("type", "container")
    bbox = zone_desc.get("bbox")
    
    # Instanciation stricte avec les arguments supportés par LayoutBox.__init__
    boite = LayoutBox(
        type=b_type,
        bbox=bbox,
        reading_order=0,
        children=[]
    )
    
    # Définition des métadonnées comme attributs d'objet
    metadata = {
        "id": f"box_{b_type}_{index}",
        "label": zone_desc.get("label", f"{b_type}_{index}"),
    }
    if "cell_bboxes" in zone_desc:
        metadata["cell_bboxes"] = zone_desc["cell_bboxes"]

    boite.metadata = metadata
    return boite


def construire_arbre_layout(page) -> LayoutBox:
    """Segmenter la page et construire la hiérarchie complète des LayoutBox.
    
    Renseigne page.layout_root avec un conteneur 'page' englobant
    toutes les sous-boîtes ordonnées spatialement.
    """
    zones_detectees = detecter_toutes_les_zones(page)
    boites_enfants: List[LayoutBox] = []

    for idx, zone in enumerate(zones_detectees):
        boite = construire_boite_depuis_zone(zone, idx)
        boites_enfants.append(boite)

    # Tri des boîtes par ordre de lecture naturel (haut en bas, gauche à droite)
    boites_enfants.sort(
        key=lambda b: (
            b.bbox.y0 if b.bbox else 0,
            b.bbox.x0 if b.bbox else 0
        )
    )

    # Affectation du numéro d'ordre de lecture
    for i, boite in enumerate(boites_enfants):
        boite.reading_order = i

    # Définition de la boîte racine de la page
    page_width = getattr(page, "width", 595.0)
    page_height = getattr(page, "height", 842.0)
    
    root_box = LayoutBox(
        type="page",
        bbox=BBox(0.0, 0.0, page_width, page_height),
        reading_order=0,
        children=boites_enfants
    )
    root_box.metadata = {"id": f"page_root_{getattr(page, 'number', 0)}"}

    page.layout_root = root_box
    return root_box
