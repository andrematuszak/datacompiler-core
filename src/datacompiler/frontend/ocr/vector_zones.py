"""vector_zones.py — Orchestration de l'OCR ciblé sur les zones de texte
vectorisé détectées par diagnostic/vector_text.py.

Différence avec ocr/tesseract.py et ocr/mistral.py en mode page entière :
ceux-là remplissent page.ocr, en attente d'un arbitrage dans compile/
(alignment.py + conflict_resolution.py) contre page.native.words existant.
Ici il n'y a RIEN à arbitrer -- pas de désaccord, un vide géométrique à
combler. Les mots produits sont donc injectés directement dans
page.native.words (is_vectorized=True, source="ocr_vectoriel"), EN AMONT
du pipeline compile/ : ils traversent reading_order/typography comme
n'importe quel mot natif, sans jamais passer par alignment.py.

Nécessite un backend exposant ocraliser_zone() (cf. ocr/base.py) --
aujourd'hui seul TesseractBackend le fait (bbox par mot). Fonctionne donc
indépendamment de MISTRAL_API_KEY.
"""

import fitz

from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.frontend.extract.pymupdf import rendre_zone_image
from datacompiler.model.document import BBox, Document

MARGE_ZONE = 2.0  # pt -- contexte autour de la bbox détectée ; une zone trop serrée nuit à Tesseract


def recuperer_texte_vectorise(doc: Document, pdf_path: str, backend, lang: str = "fra", dpi: int = 300) -> Document:
    """Pour chaque page où vector_text détecte des zones suspectes : crop +
    OCR ciblé de chaque zone, fusion directe dans page.native.words.
    No-op silencieux si `backend` n'implémente pas ocraliser_zone."""
    if not hasattr(backend, "ocraliser_zone"):
        return doc

    source = fitz.open(pdf_path)
    try:
        for i, page in enumerate(doc.pages):
            zones = zones_texte_vectorise_probable(page)
            if not zones:
                continue

            page_fitz = source[i]
            for x0, y0, x1, y1 in zones:
                zone = BBox(x0 - MARGE_ZONE, y0 - MARGE_ZONE, x1 + MARGE_ZONE, y1 + MARGE_ZONE)
                image, _ = rendre_zone_image(page_fitz, zone, dpi=dpi)
                try:
                    mots = backend.ocraliser_zone(image, offset=(zone.x0, zone.y0), lang=lang, dpi=dpi)
                except NotImplementedError:
                    continue
                page.native.words.extend(mots)
    finally:
        source.close()

    return doc