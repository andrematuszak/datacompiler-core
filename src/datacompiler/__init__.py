"""DataCompiler - PDF extraction, compilation, and rendering."""

__version__ = "0.1.0"

from datacompiler.model import Document, Word, BBox, Font, Metadata, Diagnostic
from datacompiler.frontend import extraire, diagnostiquer, ocraliser
from datacompiler.compile import resoudre
from datacompiler.backend import FORMATS, EXTENSIONS

__all__ = [
    "Document", "Word", "BBox", "Font", "Metadata", "Diagnostic",
    "extraire", "diagnostiquer", "ocraliser", "resoudre",
    "FORMATS", "EXTENSIONS",
]
