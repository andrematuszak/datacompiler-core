"""
datacompiler/frontend/extract/__init__.py
Point d'entrée de l'étape d'extraction brute.
"""

import pymupdf
# 1. On donne un alias à la vraie librairie PyPI
import pdfplumber as pdfplumber_lib

from datacompiler.model.document import Document
from .extract_pymupdf import extraire_metadonnees, extraire_page_pymupdf
from .pdfplumber import extraire_page_pdfplumber
from .merge import enrichir_metadonnees, fusionner_page
from .image_text_probe import sonder_images_page


def extraire(doc_obj: Document, pdf_path: str) -> Document:
    """
    Orchestre l'extraction brute d'un document PDF :
    1. Ingestion des métadonnées
    2. Extraction parallèle des deux moteurs (PyMuPDF & pdfplumber)
    3. Fusion des couches textuelle et graphique
    """
    doc_pymupdf = pymupdf.open(pdf_path)
    # 2. On utilise l'alias pour faire appel à l'API publique
    pdf_plumb = pdfplumber_lib.open(pdf_path)

    # 1. Ingestion des métadonnées globales
    metadata_dict = extraire_metadonnees(doc_pymupdf, pdf_path)
    enrichir_metadonnees(doc_obj, metadata_dict)

    word_global_id, image_global_id, table_global_id = 1, 1, 1

    # 2. Ingestion page par page
    for idx in range(len(doc_pymupdf)):
        page_pymupdf = doc_pymupdf[idx]
        page_plumb = pdf_plumb.pages[idx]
        image_text_signals = sonder_images_page(doc_pymupdf, page_pymupdf)

        # Ingestion Moteur 1 (Texte & Typographie)
        page_obj, word_global_id = extraire_page_pymupdf(
            page_pymupdf, 
            page_number=idx + 1, 
            start_word_id=word_global_id
        )

        # Ingestion Moteur 2 (Graphiques & Vecteurs)
        graphics_data, image_global_id, table_global_id = extraire_page_pdfplumber(
            page_plumb, 
            start_image_id=image_global_id, 
            start_table_id=table_global_id,
            image_text_signals=image_text_signals,
        )

        # 3. Assemblage final dans la Page
        page_complete = fusionner_page(page_obj, graphics_data)
        doc_obj.pages.append(page_complete)

    doc_pymupdf.close()
    pdf_plumb.close()
    return doc_obj
