"""ocr/ — Registre des backends OCR disponibles.

Usage :
    from datacompiler.frontend.ocr import get_backend, ocraliser
    
    # Via le registre :
    backend = get_backend("tesseract", lang="fra")
    backend.ocraliser(doc, pdf_path, pages=[3, 4])

    # Ou via le helper direct :
    ocraliser(doc, pdf_path, backend_name="mistral")
"""

from .base import OcrBackend
from .mistral import MistralBackend

BACKENDS = {"mistral": MistralBackend}

try:
    # 💡 Correction ici : nom du fichier = tesseract (.py)
    from .tesseract import TesseractBackend
    BACKENDS["tesseract"] = TesseractBackend
except ImportError:
    pass  # pytesseract/Pillow non installés, ou binaire tesseract absent


def get_backend(name: str, **kwargs) -> OcrBackend:
    if name not in BACKENDS:
        raise ValueError(f"Backend OCR inconnu : {name!r} (disponibles : {list(BACKENDS)})")
    return BACKENDS[name](**kwargs)


def ocraliser(doc, pdf_path: str, backend_name: str = "mistral", **kwargs):
    """Point d'entrée global pour exécuter l'OCR sur un document."""
    backend = get_backend(backend_name, **kwargs)
    return backend.ocraliser(doc, pdf_path, **kwargs)
