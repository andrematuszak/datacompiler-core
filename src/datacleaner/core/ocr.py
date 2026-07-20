"""
ocr.py — Appelle Mistral OCR et remplit doc.pages[i].ocr (OcrContainer) en
place. Ne touche jamais native/resolved (cohérent avec resolve.py qui, lui,
ne lit que native+ocr et écrit dans resolved).

Rappel important, déjà vérifié : Mistral ne fournit de bbox qu'au niveau
BLOC (paragraphe), jamais au niveau mot. Donc :
  - page.ocr.blocks porte bbox + contenu texte (granularité paragraphe)
  - page.ocr.words porte texte + confiance par mot, bbox=None (absente de
    l'API)

Usage : python ocr.py document.json --api-key sk-... [-o sortie.json]
(la clé API peut aussi venir de la variable d'environnement MISTRAL_API_KEY)
"""

import os
import sys
import base64
import argparse

from datacleaner.core.document import Document, Word, OcrBlock


def _encoder_base64(pdf_path):
    with open(pdf_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _remplir_page_ocr(page_obj, page_data):
    """Traduit UNE page de la réponse Mistral (objet SDK) vers
    page_obj.ocr. Isolé de l'appel réseau pour être testable avec un objet
    fabriqué (voir le test en session précédente / bas de fichier)."""
    page_obj.ocr.engine = "mistral-ocr-latest"

    conf_scores = getattr(page_data, "confidence_scores", None)
    mots_confiance = getattr(conf_scores, "word_confidence_scores", None) if conf_scores else None
    if mots_confiance:
        for i, w in enumerate(mots_confiance):
            page_obj.ocr.words.append(Word(
                id=i + 1, text=w.text, bbox=None, confidence=w.confidence, source="mistral"
            ))

    if getattr(page_data, "blocks", None):
        for b in page_data.blocks:
            from document import BBox
            page_obj.ocr.blocks.append(OcrBlock(
                bbox=BBox(b.top_left_x, b.top_left_y, b.bottom_right_x, b.bottom_right_y),
                type=b.type,
                content=b.content or "",
            ))


def ocraliser(doc: Document, pdf_path: str, api_key: str) -> Document:
    """Appelle l'API sur le PDF ENTIER (un seul appel, toutes pages), puis
    répartit chaque page de la réponse vers doc.pages[i].ocr correspondant."""
    from mistralai import Mistral  # import ici : évite la dépendance si ocr.py n'est pas utilisé

    client = Mistral(api_key=api_key)
    base64_data = _encoder_base64(pdf_path)

    reponse = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{base64_data}",
        },
        include_blocks=True,
        confidence_scores_granularity="word",
    )

    if not reponse.pages:
        raise RuntimeError("L'API Mistral n'a renvoyé aucune page.")

    for i, page_data in enumerate(reponse.pages):
        if i < len(doc.pages):
            _remplir_page_ocr(doc.pages[i], page_data)

    return doc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Appel Mistral OCR -> remplit doc.pages[].ocr")
    parser.add_argument("document_json", help="document.json produit par extract.py")
    parser.add_argument("pdf", help="PDF source (nécessaire pour l'appel API)")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("-o", "--output", default=None)
    args = parser.parse_args()

    api_key = args.api_key or os.getenv("MISTRAL_API_KEY")
    if not api_key:
        print("Erreur : clé API Mistral introuvable (--api-key ou variable MISTRAL_API_KEY).")
        sys.exit(1)

    doc = Document.load(args.document_json)
    ocraliser(doc, args.pdf, api_key)

    sortie = args.output or args.document_json
    doc.save(sortie)
    for p in doc.pages:
        print(f"Page {p.number} : {len(p.ocr.words)} mots OCR, {len(p.ocr.blocks)} bloc(s)")
    print(f"Écrit : {sortie}")
