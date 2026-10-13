"""Define the shared interface for OCR backends. Implementations populate the requested OCR layer and should leave unrelated document layers unchanged."""

from abc import ABC, abstractmethod

from datacompiler.model.document import Document

def ocraliser_zone(self, image, offset: tuple = (0.0, 0.0), **kwargs) -> list:
        """Run OCR on an already-cropped region and translate its detections into page coordinates using the supplied offset."""
        raise NotImplementedError(f"{self.name} does not support targeted OCR.")


class OcrBackend(ABC):
    name: str = "backend"

    @abstractmethod
    def ocraliser(self, doc: Document, pdf_path: str, pages: list = None, **kwargs) -> Document:
        """Populate OCR layers for the requested pages; backends may override this when they do not support full-page OCR."""
        ...
