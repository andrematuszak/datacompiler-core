"""mistral_backend.py — Adapte l'existant ocr.py (Mistral) à l'interface
OcrBackend, SANS toucher à ocr.py -- ocr.py reste utilisable directement
comme avant, ce backend n'est qu'une façade pour le routeur (__init__.py).
"""

from ocr import ocraliser as _ocraliser_mistral
from document import Document

from .base import OcrBackend


class MistralBackend(OcrBackend):
    name = "mistral"

    def __init__(self, api_key: str = None):
        self.api_key = api_key

    def ocraliser(self, doc: Document, pdf_path: str, pages: list = None, **kwargs) -> Document:
        # L'API Mistral OCRise le PDF ENTIER en un seul appel -- pas de
        # sélection de pages possible côté API. `pages` n'est donc PAS un
        # vrai filtre ici (contrairement à TesseractBackend) : soit on
        # appelle l'API (et elle traite tout le document), soit on ne
        # l'appelle pas du tout. C'est au code appelant (le routeur, ou
        # pipeline.py) de décider de ne pas appeler ce backend si `pages`
        # est vide -- ce backend ne fait pas ce tri lui-même.
        api_key = kwargs.get("api_key", self.api_key)
        return _ocraliser_mistral(doc, pdf_path, api_key)
