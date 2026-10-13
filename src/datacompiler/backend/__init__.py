"""Lazy registry of renderers from ``page.resolved`` to output formats."""

from importlib import import_module
from pathlib import Path

__all__ = [
    "FORMATS",
    "EXTENSIONS",
    "render_docx",
    "render_html",
    "render_markdown",
    "render_rebuilt_pdf",
    "render_flow_pdf",
    "render_faithful_pdf",
]

_RENDERERS = {
    "render_docx": "datacompiler.backend.rebuilt_docx",
    "render_html": "datacompiler.backend.rebuilt_html",
    "render_markdown": "datacompiler.backend.rebuilt_markdown",
    "render_rebuilt_pdf": "datacompiler.backend.rebuilt_pdf",
    "render_flow_pdf": "datacompiler.backend.flow_pdf",
    "render_faithful_pdf": "datacompiler.backend.faithful_pdf",
}


def __getattr__(name):
    try:
        module_name = _RENDERERS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))


def _renderer(module_name, function_name):
    def call(*args, **kwargs):
        function = getattr(import_module(module_name), function_name)
        return function(*args, **kwargs)
    return call


def _ecrire_texte(fonction_rendu):
    def wrapper(doc, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(fonction_rendu(doc), encoding="utf-8")
        return str(output_path)
    return wrapper


def _rendu_fidele(strategy):
    def render(doc, output_path):
        return _renderer("datacompiler.backend.faithful_pdf", "render_faithful_pdf")(
            doc, output_path, strategy=strategy
        )
    return render


EXTENSIONS = {
    "overlay": "pdf",
    "clean_overlay": "pdf",
    "rasterized": "pdf",
    "flow": "pdf",
    "rebuilt": "pdf",
    "markdown": "md",
    "html": "html",
    "docx": "docx",
    "faithful-pdf": "pdf",
}

FORMATS = {
    "overlay": _rendu_fidele("overlay"),
    "clean_overlay": _rendu_fidele("clean_overlay"),
    "rasterized": _rendu_fidele("rasterized"),
    "flow": _renderer("datacompiler.backend.flow_pdf", "render_flow_pdf"),
    "rebuilt": _renderer("datacompiler.backend.rebuilt_pdf", "render_rebuilt_pdf"),
    "markdown": _ecrire_texte(_renderer("datacompiler.backend.rebuilt_markdown", "render_markdown")),
    "html": _ecrire_texte(_renderer("datacompiler.backend.rebuilt_html", "render_html")),
    "docx": _renderer("datacompiler.backend.rebuilt_docx", "render_docx"),
}

FORMATS["faithful-pdf"] = FORMATS["overlay"]


def _strategy_for_cli_format(output_format, rendering_strategy):
    """Translate the CLI output-format name to the pipeline renderer key."""
    if output_format == "faithful-pdf":
        return rendering_strategy
    return {
        "flow-pdf": "flow",
        "rebuilt-pdf": "rebuilt",
        "markdown": "markdown",
        "html": "html",
        "docx": "docx",
    }[output_format]
