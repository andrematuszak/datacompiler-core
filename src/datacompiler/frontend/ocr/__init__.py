"""ocr_backends/ — Registre des backends OCR disponibles.

Usage :
    from ocr_backends import get_backend
    backend = get_backend("tesseract", lang="fra")
    backend.ocraliser(doc, pdf_path, pages=[3, 4])

N'importe ni ne casse rien dans ocr.py existant -- get_backend("mistral")
appelle en interne la même fonction ocraliser() qu'avant, juste via
l'interface commune.
"""

from .base import OcrBackend
from .mistral_backend import MistralBackend

BACKENDS = {"mistral": MistralBackend}

try:
    from .tesseract_backend import TesseractBackend
    BACKENDS["tesseract"] = TesseractBackend
except ImportError:
    pass  # pytesseract/Pillow non installés, ou binaire tesseract absent du
          # système -- le backend est simplement absent du registre plutôt
          # que de faire planter tout le reste au premier import.


def get_backend(name: str, **kwargs) -> OcrBackend:
    if name not in BACKENDS:
        raise ValueError(f"Backend OCR inconnu : {name!r} (disponibles : {list(BACKENDS)})")
    return BACKENDS[name](**kwargs)
