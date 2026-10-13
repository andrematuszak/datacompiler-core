"""DataCompiler public API.

The package root stays lightweight: public objects are imported only when first
accessed, so importing :mod:`datacompiler` does not initialize OCR engines.
"""

from importlib import import_module

from datacompiler._version import __version__

__all__ = [
    "__version__",
    "extract_document",
    "diagnose_document",
    "run_ocr",
    "resolve_document",
    "run_pipeline",
    "display_report",
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

_EXPORTS = {
    "extract_document": ("datacompiler.frontend", "extract_document"),
    "diagnose_document": ("datacompiler.frontend", "diagnose_document"),
    "run_ocr": ("datacompiler.frontend", "run_ocr"),
    "resolve_document": ("datacompiler.compile", "resolve_document"),
    "run_pipeline": ("datacompiler.pipeline", "run_pipeline"),
    "display_report": ("datacompiler.frontend", "display_report"),
    "Document": ("datacompiler.model", "Document"),
    "Word": ("datacompiler.model", "Word"),
    "BBox": ("datacompiler.model", "BBox"),
    "Font": ("datacompiler.model", "Font"),
    "Metadata": ("datacompiler.model", "Metadata"),
    "Diagnostic": ("datacompiler.model", "Diagnostic"),
    "extraire": ("datacompiler.frontend", "extraire"),
    "diagnostiquer": ("datacompiler.frontend", "diagnostiquer"),
    "ocraliser": ("datacompiler.frontend", "ocraliser"),
    "resoudre": ("datacompiler.compile", "resoudre"),
    "executer_pipeline": ("datacompiler.pipeline", "executer_pipeline"),
    "FORMATS": ("datacompiler.backend", "FORMATS"),
    "EXTENSIONS": ("datacompiler.backend", "EXTENSIONS"),
}


def __getattr__(name):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
