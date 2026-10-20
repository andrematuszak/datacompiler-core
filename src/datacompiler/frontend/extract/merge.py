"""
datacompiler/frontend/extract/merge.py
Module d'assemblage — Fusionne les flux PyMuPDF et pdfplumber dans l'AST Page.
"""

from typing import Dict, Any, List
from datacompiler.model.document import Document, Page


def enrichir_metadonnees(doc_obj: Document, metadata_dict: dict) -> None:
    """Copy extracted metadata into the document object."""
    for key, value in metadata_dict.items():
        if hasattr(doc_obj.metadata, key):
            setattr(doc_obj.metadata, key, value)


def fusionner_page(page_obj: Page, graphics_data: Dict[str, List[Any]]) -> Page:
    """Merge visual elements extracted by pdfplumber into the existing page structure."""
    page_obj.graphics.images.extend(graphics_data.get("images", []))
    page_obj.graphics.tables.extend(graphics_data.get("tables", []))
    page_obj.graphics.lines.extend(graphics_data.get("lines", []))
    return page_obj