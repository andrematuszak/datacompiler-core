"""DataCompiler - PDF extraction, diagnostic, OCR, compilation, and rendering."""

__version__ = "0.1.0"

from datacompiler.model import Document, Word, BBox, Font, Metadata, Diagnostic
from datacompiler.frontend import extraire, diagnostiquer, ocraliser
from datacompiler.compile import resoudre
from datacompiler.backend import FORMATS, EXTENSIONS
from datacompiler.pipeline import executer_pipeline

__all__ = [
    "Document",
    "Word",
    "BBox",
    "Font",
    "Metadata",
    "Diagnostic",
    "extraire",
    "diagnostiquer",
    "ocraliser",
    "resoudre",
    "executer_pipeline",
    "FORMATS",
    "EXTENSIONS",
]
