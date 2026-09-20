"""
Module de construction de l'arbre de mise en page (LayoutTree).
Instancie les objets LayoutBox et génère le nœud racine page.layout_root.
"""

from typing import List
from datacompiler.model.document import LayoutBox
from datacompiler.model.geometry import BBox
from datacompiler.utils.heuristics_geometry import ordonner_par_lignes
from datacompiler.frontend.layout.detectors import detecter_toutes_les_zones


def construire_boite_depuis_zone(zone_desc: dict, index: int) -> LayoutBox:
    """Instancie une LayoutBox à partir d'un dictionnaire descriptif issu des détecteurs."""
    b_type = zone_desc.get("type", "container")
    bbox = zone_desc.get("bbox")

    metadata = {
        "id": f"box_{b_type}_{index}",
        "label": zone_desc.get("label", f"{b_type}_{index}"),
    }
    if "cell_bboxes" in zone_desc:
        metadata["cell_bboxes"] = zone_desc["cell_bboxes"]

    # metadata passé au CONSTRUCTEUR, pas assigné après coup en attribut
    # libre -- LayoutBox.metadata est maintenant un champ déclaré du
    # dataclass (cf. model/document.py), donc dataclasses.asdict() (utilisé
    # par Document.save()) le sérialise correctement. Avant ce fix,
    # `boite.metadata = metadata` assignait un attribut hors dataclass :
    # jamais une erreur, mais cell_bboxes disparaissait silencieusement au
    # premier doc.save() -- perdu sans qu'aucun test ne le signale.
    return LayoutBox(
        type=b_type,
        bbox=bbox,
        reading_order=0,
        children=[],
        metadata=metadata,
    )


def construire_arbre_layout(page) -> LayoutBox:
    """Segmenter la page et construire la hiérarchie complète des LayoutBox.
    
    Renseigne page.layout_root avec un conteneur 'page' englobant
    toutes les sous-boîtes ordonnées spatialement.
    """
    zones_detectees = detecter_toutes_les_zones(page)
    boites_enfants: List[LayoutBox] = [
        construire_boite_depuis_zone(zone, idx) for idx, zone in enumerate(zones_detectees)
    ]

    # Ordonnancement par rangées (bande commune qui rétrécit), PAS un tri
    # plat (y0, x0) -- cf. geometry.py::ordonner_par_lignes pour le détail
    # du bug que ça évite (déjà rencontré et corrigé ailleurs dans ce
    # projet : "Feuillet 1 2", "situation" mélangé à "C"/"T"). Des boîtes
    # hétérogènes (image/table/zone vectorielle) à des y0 légèrement
    # différents mais sur la même bande visuelle auraient pu se faire
    # trier dans un ordre qui ne reflète pas la lecture réelle avec un tri
    # plat.
    boites_enfants = ordonner_par_lignes(boites_enfants)

    for i, boite in enumerate(boites_enfants):
        boite.reading_order = i

    page_width = getattr(page, "width", 595.0)
    page_height = getattr(page, "height", 842.0)

    root_box = LayoutBox(
        type="page",
        bbox=BBox(0.0, 0.0, page_width, page_height),
        reading_order=0,
        children=boites_enfants,
        metadata={"id": f"page_root_{getattr(page, 'number', 0)}"},
    )

    page.layout_root = root_box
    return root_box
