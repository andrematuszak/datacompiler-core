"""DataCompiler - PDF extraction, compilation, and rendering."""

__version__ = "0.1.0"

from .model import Document, Word, BBox, Font, Metadata, Diagnostic
from .frontend import extraire, diagnostiquer, ocraliser
from .compile import resoudre
from .backend import FORMATS, EXTENSIONS

__all__ = [
    "Document", "Word", "BBox", "Font", "Metadata", "Diagnostic",
    "extraire", "diagnostiquer", "ocraliser", "resoudre",
    "FORMATS", "EXTENSIONS",
]
