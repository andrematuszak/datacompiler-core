"""
extract.py — Alimente l'objet Document depuis un PDF physique.
Correction des index de blocs et suppression de l'extraction de caractères morts.
"""

from pathlib import Path
import fitz
import pdfplumber

from datacleaner.core.document import (
    Document, Page, Word, Font, BBox, 
    ImageElement, TableElement, GraphicVector
)

def _convertir_couleur(srgb_int):
    if srgb_int is None: return "#000000"
    r, g, b = (srgb_int >> 16) & 255, (srgb_int >> 8) & 255, srgb_int & 255
    return f"#{r:02x}{g:02x}{b:02x}"

def extraire(doc_obj: Document, pdf_path: str) -> Document:
    """Remplit l'objet Document passé en paramètre avec les données brutes."""
    doc_fitz = fitz.open(pdf_path)
    pdf_plumb = pdfplumber.open(pdf_path)

    doc_obj.metadata.filename = Path(pdf_path).name
    doc_obj.metadata.source_pdf = str(Path(pdf_path).resolve())
    doc_obj.metadata.page_count = len(doc_fitz)
    doc_obj.metadata.producer = doc_fitz.metadata.get("producer", "")
    doc_obj.metadata.creator = doc_fitz.metadata.get("creator", "")
    doc_obj.metadata.creation_date = doc_fitz.metadata.get("creationDate", "")
    doc_obj.metadata.modification_date = doc_fitz.metadata.get("modDate", "")
    doc_obj.metadata.pdf_version = doc_fitz.metadata.get("format", "")
    doc_obj.metadata.encrypted = bool(doc_fitz.is_encrypted)

    word_global_id, image_global_id, table_global_id = 1, 1, 1

    for idx in range(len(doc_fitz)):
        page_fitz = doc_fitz[idx]
        page_plumb = pdf_plumb.pages[idx]

        page_obj = Page(
            number=idx + 1,
            width=float(page_fitz.rect.width),
            height=float(page_fitz.rect.height),
            rotation=float(page_fitz.rotation)
        )

        # --- MOTEUR 1 : PyMuPDF ---
        page_dict = page_fitz.get_text("dict")
        words_fitz = page_fitz.get_text("words") # Sorti de la boucle !
        font_map = {}

        # Les indices de bloc retournés par get_text("words") ne comptent que
        # les blocs texte. ``enumerate(page_dict["blocks"])`` est donc faux dès
        # qu'une image précède du texte (cas de test1 : les quatre premiers
        # blocs graphiques faisaient disparaître le haut de page).
        text_block_idx = 0
        for b in page_dict.get("blocks", []):
            if b.get("type") != 0:
                continue

            block_idx = text_block_idx
            text_block_idx += 1

            for line_idx, l in enumerate(b.get("lines", [])):
                font_name, font_size, bold, italic, color_hex = "Unknown", 0.0, False, False, "#000000"
                
                # Récupération du style via le span
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
                            id=word_global_id, text=w[4],
                            bbox=BBox(w[0], w[1], w[2], w[3]),
                            block=int(w[5]), line=int(w[6]), word=int(w[7]),
                            font=font_name, font_size=font_size,
                            bold=bold, italic=italic, color=color_hex,
                            rotation=float(page_fitz.rotation)
                        ))
                        word_global_id += 1

        for name, sizes in font_map.items():
            page_obj.native.fonts.append(Font(name=name, sizes=sorted(list(sizes))))

        # --- MOTEUR 2 : pdfplumber ---
        for img in page_plumb.images:
            page_obj.graphics.images.append(ImageElement(
                id=image_global_id, bbox=BBox(float(img["x0"]), float(img["top"]), float(img["x1"]), float(img["bottom"])),
                width=int(img.get("width", 0)), height=int(img.get("height", 0))
            ))
            image_global_id += 1

        for t in page_plumb.find_tables():
            page_obj.graphics.tables.append(TableElement(
                id=table_global_id, bbox=BBox(float(t.bbox[0]), float(t.bbox[1]), float(t.bbox[2]), float(t.bbox[3])),
                rows=t.extract()
            ))
            table_global_id += 1

        for line in page_plumb.lines:
            page_obj.graphics.lines.append(GraphicVector(bbox=BBox(float(line["x0"]), float(line["top"]), float(line["x1"]), float(line["bottom"]))))

        doc_obj.pages.append(page_obj)

    doc_fitz.close()
    pdf_plumb.close()
    return doc_obj
