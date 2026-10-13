"""Frontend APIs, imported on demand to keep package discovery lightweight."""

from importlib import import_module

__all__ = [
    "extract_document",
    "diagnose_document",
    "run_ocr",
    "extraire",
    "diagnostiquer",
    "report",
    "display_report",
    "ocraliser",
    "segmenter_page",
]

_EXPORTS = {
    "extract_document": ("datacompiler.frontend.extract", "extraire"),
    "diagnose_document": ("datacompiler.frontend.diagnostic", "diagnostiquer"),
    "run_ocr": ("datacompiler.frontend.ocr", "ocraliser"),
    "extraire": ("datacompiler.frontend.extract", "extraire"),
    "diagnostiquer": ("datacompiler.frontend.diagnostic", "diagnostiquer"),
    "report": ("datacompiler.frontend.diagnostic.report", None),
    "display_report": ("datacompiler.frontend.diagnostic.report", "display_report"),
    "ocraliser": ("datacompiler.frontend.ocr", "ocraliser"),
    "segmenter_page": ("datacompiler.frontend.layout", "segmenter_page"),
}


def __getattr__(name):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_name)
    value = module if attribute is None else getattr(module, attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
