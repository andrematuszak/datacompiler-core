"""
datacompiler/frontend/extract/pymupdf.py
Moteur 1 — Extraction des données textuelles et métadonnées via PyMuPDF.
"""

from pathlib import Path
from typing import Dict, Tuple, Set, Any
import fitz

from datacompiler.model.document import Page, Word, Font, BBox


def _convertir_couleur(srgb_int: int | None) -> str:
    """Convertit un entier sRGB en format Hexadécimal."""
    if srgb_int is None:
        return "#000000"
    r = (srgb_int >> 16) & 255
    g = (srgb_int >> 8) & 255
    b = srgb_int & 255
    return f"#{r:02x}{g:02x}{b:02x}"


def extraire_metadonnees(doc_fitz: fitz.Document, pdf_path: str) -> dict:
    """Extrait l'ensemble des métadonnées système du fichier PDF."""
    return {
        "filename": Path(pdf_path).name,
        "source_pdf": str(Path(pdf_path).resolve()),
        "page_count": len(doc_fitz),
        "producer": doc_fitz.metadata.get("producer", ""),
        "creator": doc_fitz.metadata.get("creator", ""),
        "creation_date": doc_fitz.metadata.get("creationDate", ""),
        "modification_date": doc_fitz.metadata.get("modDate", ""),
        "pdf_version": doc_fitz.metadata.get("format", ""),
        "encrypted": bool(doc_fitz.is_encrypted),
    }


def extraire_page_pymupdf(
    page_fitz: fitz.Page, 
    page_number: int, 
    start_word_id: int
) -> Tuple[Page, int]:
    """
    Extrait le texte natif, les Bounding Boxes et la typographie d'une page.
    Gère la ré-indexation des blocs de texte pour éliminer les décalages avec les images.
    """
    page_obj = Page(
        number=page_number,
        width=float(page_fitz.rect.width),
        height=float(page_fitz.rect.height),
        rotation=float(page_fitz.rotation)
    )

    page_dict = page_fitz.get_text("dict")
    words_fitz = page_fitz.get_text("words")
    font_map: Dict[str, Set[float]] = {}
    word_global_id = start_word_id

    # Alignement d'index : ignorer les blocs non-texte (images)
    text_block_idx = 0
    for b in page_dict.get("blocks", []):
        if b.get("type") != 0:
            continue

        block_idx = text_block_idx
        text_block_idx += 1

        for line_idx, l in enumerate(b.get("lines", [])):
            font_name, font_size, bold, italic, color_hex = "Unknown", 0.0, False, False, "#000000"
            
            # Récupération de la typographie via les spans
            for s in l.get("spans", []):
                font_name = s.get("font", "Unknown")
                font_size = float(s.get("size", 0.0))
                bold = bool(s.get("flags", 0) & 4)
                italic = bool(s.get("flags", 0) & 2)
                color_hex = _convertir_couleur(s.get("color"))
                font_map.setdefault(font_name, set()).add(round(font_size, 1))

            # Récupération géométrique des mots
            for w in words_fitz:
                if w[5] == block_idx and w[6] == line_idx:
                    page_obj.native.words.append(Word(
                        id=word_global_id,
                        text=w[4],
                        bbox=BBox(w[0], w[1], w[2], w[3]),
                        block=int(w[5]),
                        line=int(w[6]),
                        word=int(w[7]),
                        font=font_name,
                        font_size=font_size,
                        bold=bold,
                        italic=italic,
                        color=color_hex,
                        rotation=float(page_fitz.rotation)
                    ))
                    word_global_id += 1

    # Ingestion des polices recensées
    for name, sizes in font_map.items():
        page_obj.native.fonts.append(Font(name=name, sizes=sorted(list(sizes))))

    return page_obj, word_global_id