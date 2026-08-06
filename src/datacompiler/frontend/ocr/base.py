"""base.py — Interface commune à tous les backends OCR.

Contrat identique à l'actuel ocr.py (Mistral) : un backend remplit
page.ocr (OcrContainer) pour les pages demandées, ne touche JAMAIS
native/resolved. resolve/ (ou le code d'arbitrage existant) continue de
lire page.ocr sans se soucier de quel backend l'a rempli.
"""

from abc import ABC, abstractmethod

from datacompiler.model.document import Document

def ocraliser_zone(self, image, offset: tuple = (0.0, 0.0), **kwargs) -> list:
        """OCR ciblé sur une zone déjà croppée, bbox déjà translatées dans
        le repère page via `offset`. Optionnel : NotImplementedError par
        défaut. Seul un backend donnant une bbox PAR MOT peut l'implémenter
        (Tesseract, pas Mistral -- cf. tesseract.py). L'appelant vérifie la
        capacité (hasattr / try-except) plutôt que de supposer un
        comportement uniforme entre backends."""
        raise NotImplementedError(f"{self.name} ne supporte pas l'OCR de zone ciblée.")


class OcrBackend(ABC):
    name: str = "backend"

    @abstractmethod
    def ocraliser(self, doc: Document, pdf_path: str, pages: list = None, **kwargs) -> Document:
        """Remplit doc.pages[i].ocr pour les pages demandées (toutes les
        pages si pages=None -- liste de numéros de page, 1-indexée, sinon).

        Note : certains backends (Mistral) n'offrent pas de sélection de
        pages côté API -- `pages` y est alors indicatif seulement (tout est
        OCRisé, mais on peut choisir de ne PAS appeler l'API si `pages` est
        vide). D'autres (Tesseract) tournent réellement page par page et
        honorent `pages` comme un vrai filtre. Documenté dans chaque
        implémentation plutôt que supposé uniforme."""
        ...
