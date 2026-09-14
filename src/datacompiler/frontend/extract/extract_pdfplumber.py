"""
datacompiler/frontend/extract/pdfplumber.py
Moteur 2 — Extraction des éléments visuels et vectoriels via pdfplumber.
"""

from . import table_reconstruction
from typing import Tuple, List, Dict, Any, Optional
import pdfplumber

from datacompiler.model.document import BBox, ImageElement, TableElement, GraphicVector


def extraire_page_pdfplumber(
    page_plumb: Any,
    start_image_id: int,
    start_table_id: int,
    image_text_signals: Optional[list] = None,
) -> Tuple[Dict[str, List[Any]], int, int]:
    """
    Extrait les images, tableaux (avec reconstruction avancée) 
    et lignes vectorielles d'une page.
    """
    images: List[ImageElement] = []
    tables: List[TableElement] = []
    lines: List[GraphicVector] = []

    image_id = start_image_id
    table_id = start_table_id

    def texte_dans_image(img) -> Optional[bool]:
        """Rattache la bbox pdfplumber au placement PyMuPDF correspondant."""
        if not image_text_signals:
            return None
        bbox = BBox(float(img["x0"]), float(img["top"]), float(img["x1"]), float(img["bottom"]))
        for rect, signal in image_text_signals:
            if all(abs(a - b) < 0.1 for a, b in zip((bbox.x0, bbox.y0, bbox.x1, bbox.y1), rect)):
                return signal
        return None

    # 1. Images
    for img in page_plumb.images:
        images.append(ImageElement(
            id=image_id,
            bbox=BBox(float(img["x0"]), float(img["top"]), float(img["x1"]), float(img["bottom"])),
            width=int(img.get("width", 0)),
            height=int(img.get("height", 0)),
            contains_text=texte_dans_image(img),
        ))
        image_id += 1

    # 2. Tableaux (Délégation de la reconstruction)
    #
    # FIX (session du 16/08) : find_tables() nu (stratégie par défaut
    # "lines") produit des bbox de table CONTAMINÉES par le texte
    # vectorisé de la page -- vérifié directement via
    # page_plumb.debug_tablefinder() : un "rect_edge" rapportait x0=55.81,
    # une valeur qui ne correspond à AUCUN objet géométrique réel (son
    # propre champ `pts` montre les vrais coins du rectangle, 14.17 à
    # 121.21 -- x0=55.81 est une valeur fantôme). Cause : au même endroit,
    # des dizaines de `curve_edge` (le texte OCR vectorisé, dessiné en
    # courbes) se mélangent aux vrais bords de rect dans la stratégie
    # "lines" par défaut. Confirmé empiriquement (test-impots-revenu.pdf,
    # page 2) : ce bord fantôme excluait "situation" du tableau alors que
    # son centre tombait à 1.6pt seulement du vrai bord.
    #
    # Correctif : stratégie "explicit", alimentée UNIQUEMENT par les rects
    # et lignes réels de la page -- les courbes (texte vectorisé, tracés
    # de glyphes OCR) n'y contribuent jamais. Revérifié après coup :
    # produit aussi 2 tables SUPPLÉMENTAIRES sur la page 1 du même
    # document (petits encarts "Vos contacts"-like), jamais détectées par
    # la stratégie par défaut -- semble être une amélioration, pas un
    # faux positif, mais pas revérifié sur le reste du corpus de test
    # (14+ PDF, cf. mémoire du projet) -- À FAIRE avant de considérer ce
    # correctif définitivement sûr partout.
    geometrie_fiable = page_plumb.rects + page_plumb.lines
    table_settings = {
        "vertical_strategy": "explicit",
        "horizontal_strategy": "explicit",
        "explicit_vertical_lines": geometrie_fiable,
        "explicit_horizontal_lines": geometrie_fiable,
    }
    for t in page_plumb.find_tables(table_settings=table_settings):
        rows, cellules = table_reconstruction.extraire_lignes_et_cellules(page_plumb, t)
        tables.append(TableElement(
            id=table_id,
            bbox=BBox(float(t.bbox[0]), float(t.bbox[1]), float(t.bbox[2]), float(t.bbox[3])),
            rows=rows,
            # Géométrie par cellule, persistée séparément du texte --
            # cf. table_reconstruction.extraire_lignes_et_cellules (appel
            # combiné, garantit rows/cell_bboxes cohérents). Le bucketing
            # mots<->cellules se fait plus tard, dans layout_tree.py, une
            # fois native.words complet (OCR ciblé inclus, étape 4/6 du
            # pipeline -- après celle-ci).
            cell_bboxes=[
                [BBox(*cell) if cell else None for cell in ligne]
                for ligne in cellules
            ],
        ))
        table_id += 1

    # 3. Lignes et tracés vectoriels
    for line in page_plumb.lines:
        lines.append(GraphicVector(
            bbox=BBox(float(line["x0"]), float(line["top"]), float(line["x1"]), float(line["bottom"]))
        ))

    graphics_data = {
        "images": images,
        "tables": tables,
        "lines": lines
    }

    return graphics_data, image_id, table_id
