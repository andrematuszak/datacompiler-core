"""
datacompiler/frontend/extract/pdfplumber.py
Moteur 2 — Extraction des éléments visuels et vectoriels via pdfplumber.
"""

from . import table_reconstruction
from typing import Tuple, List, Dict, Any
import pdfplumber

from datacompiler.model.document import BBox, ImageElement, TableElement, GraphicVector


def extraire_page_pdfplumber(
    page_plumb: Any,
    start_image_id: int,
    start_table_id: int
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

    # 1. Images
    for img in page_plumb.images:
        images.append(ImageElement(
            id=image_id,
            bbox=BBox(float(img["x0"]), float(img["top"]), float(img["x1"]), float(img["bottom"])),
            width=int(img.get("width", 0)),
            height=int(img.get("height", 0))
        ))
        image_id += 1

    # 2. Tableaux (Délégation de la reconstruction)
    for t in page_plumb.find_tables():
        tables.append(TableElement(
            id=table_id,
            bbox=BBox(float(t.bbox[0]), float(t.bbox[1]), float(t.bbox[2]), float(t.bbox[3])),
            rows=table_reconstruction.extraire_lignes(page_plumb, t)
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
