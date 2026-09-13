"""ocr/ — Registre des backends OCR disponibles.

Usage :
    from datacompiler.frontend.ocr import get_backend, ocraliser
    
    # Via le registre :
    backend = get_backend("paddle", lang="fr")
    backend.ocraliser(doc, pdf_path, pages=[3, 4])

    # Ou via le helper direct :
    ocraliser(doc, pdf_path, backend_name="paddle")
"""

from datacompiler.frontend.ocr.base import OcrBackend

BACKENDS = {}

try:
    from .paddle import PaddleOCRBackend
    BACKENDS["paddle"] = PaddleOCRBackend
except ImportError:
    pass

try:
    from .tesseract import TesseractBackend
    BACKENDS["tesseract"] = TesseractBackend
except ImportError:
    pass

try:
    from .mistral import MistralBackend
    BACKENDS["mistral"] = MistralBackend
except ImportError:
    pass


def get_backend(name: str, **kwargs) -> OcrBackend:
    if name not in BACKENDS:
        raise ValueError(f"Backend OCR inconnu : {name!r} (disponibles : {list(BACKENDS)})")
    return BACKENDS[name](**kwargs)


def ocraliser(doc, pdf_path: str, backend_name: str = "paddle", pages: list = None, **kwargs):
    """Point d'entrée global pour exécuter l'OCR sur un document."""
    backend = get_backend(backend_name, **kwargs)
    return backend.ocraliser(doc, pdf_path, pages=pages, **kwargs)
