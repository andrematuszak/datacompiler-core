"""frontend/layout/ — Façade du sous-module de macro-segmentation.

Expose les fonctions de détection et d'assemblage de l'arbre de mise en page
(LayoutBox) exécutées lors de l'étape 3 du pipeline (avant l'OCR et la compilation).
"""

from datacompiler.frontend.layout.builder import (
    construire_arbre_layout,
    construire_boite_depuis_zone,
)
from datacompiler.frontend.layout.detectors import (
    detecter_boites_images,
    detecter_boites_tables,
    detecter_boites_vectorielles,
    detecter_toutes_les_zones,
)

# Alias d'entrée principal pour le pipeline
segmenter_page = construire_arbre_layout

__all__ = [
    "segmenter_page",
    "construire_arbre_layout",
    "construire_boite_depuis_zone",
    "detecter_boites_images",
    "detecter_boites_tableaux",
    "detecter_boites_vectorielles",
    "detecter_toutes_les_zones",
]
