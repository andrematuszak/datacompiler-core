"""Lazy registry of OCR backends.

Importing the registry does not import model frameworks or OCR engines. The
selected backend is imported only when ``get_backend`` is called.
"""

from importlib import import_module
from collections.abc import Mapping

from datacompiler.frontend.ocr.base import OcrBackend

__all__ = ["OcrBackend", "BACKENDS", "get_backend", "ocraliser"]

_BACKEND_MODULES = {
    "paddle": (".paddle", "PaddleOCRBackend"),
    "mistral": (".mistral", "MistralBackend"),
}


class _BackendRegistry(Mapping):
    def __getitem__(self, name):
        try:
            module_name, class_name = _BACKEND_MODULES[name]
        except KeyError:
            raise KeyError(name) from None
        module = import_module(module_name, __name__)
        return getattr(module, class_name)

    def __iter__(self):
        return iter(_BACKEND_MODULES)

    def __len__(self):
        return len(_BACKEND_MODULES)

    def __contains__(self, name):
        return name in _BACKEND_MODULES


BACKENDS = _BackendRegistry()


def get_backend(name: str, **kwargs) -> OcrBackend:
    if name not in BACKENDS:
        raise ValueError(f"Unknown OCR backend: {name!r} (available: {list(BACKENDS)})")
    return BACKENDS[name](**kwargs)


def ocraliser(doc, pdf_path: str, backend_name: str = "paddle", pages: list = None, **kwargs):
    """Run the selected OCR backend on a document and populate its OCR layer."""
    backend = get_backend(backend_name, **kwargs)
    return backend.ocraliser(doc, pdf_path, pages=pages, **kwargs)
