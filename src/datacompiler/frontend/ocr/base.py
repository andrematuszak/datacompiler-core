"""Define the shared interface for OCR backends. Implementations populate the requested OCR layer and should leave unrelated document layers unchanged."""

from abc import ABC, abstractmethod
from typing import Any

from datacompiler.model.document import Document


class OcrBackend(ABC):
    name: str = "backend"

    @abstractmethod
    def ocraliser(
        self,
        doc: Document,
        pdf_path: str,
        pages: list[int] | None = None,
        **kwargs: Any,
    ) -> Document:
        """Populate OCR layers for the requested pages; backends may override this when they do not support full-page OCR."""
        ...

    def ocraliser_zone(
        self,
        image,
        offset: tuple[float, float] = (0.0, 0.0),
        **kwargs: Any,
    ) -> list:
        """OCR a cropped region and return detections in page coordinates."""
        raise NotImplementedError(f"{self.name} does not support targeted OCR.")
