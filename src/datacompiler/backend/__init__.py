"""backend/ — Renderers de page.resolved vers différents formats de sortie.

Deux formes d'interface selon le format :
  - "texte" (markdown, html) : la fonction retourne une chaîne ; FORMATS
    l'encapsule pour l'écrire directement sur disque (_ecrire_texte).
  - "fichier direct" (docx, rebuilt-pdf) : la fonction écrit elle-même sur
    disque et retourne le chemin -- nécessaire pour docx/pdf, qui ne sont
    pas de simples chaînes de caractères.

faithful-pdf n'est PAS dans FORMATS : sa signature a des paramètres
supplémentaires (source_pdf, strategy, dpi) que les autres formats n'ont
pas -- pipeline.py continue à l'appeler à part, comme avant.
"""

from pathlib import Path

from .docx import render_docx
from .html import render_html
from .markdown import render_markdown
from .rebuilt_pdf import render_rebuilt_pdf
from .flow_pdf import render_flow_pdf
from .rebuilt_pdf import render_rebuilt_pdf

def _ecrire_texte(fonction_rendu):
    def wrapper(doc, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(fonction_rendu(doc), encoding="utf-8")
        return output_path
    return wrapper


EXTENSIONS = {
    "overlay": "pdf",
    "clean_overlay": "pdf",
    "rasterized": "pdf",
    "flow": "pdf",
    "rebuilt": "pdf",
    "markdown": "md",
    "html": "html",
    "docx": "docx",
}

FORMATS = {
    "overlay": lambda doc, path: render_faithful_pdf(doc, path, strategy="overlay"),
    "clean_overlay": lambda doc, path: render_faithful_pdf(doc, path, strategy="clean_overlay"),
    "rasterized": lambda doc, path: render_faithful_pdf(doc, path, strategy="rasterized"),
    "flow": render_flow_pdf,
    "rebuilt": render_rebuilt_pdf,
    "markdown": render_markdown,
    "html": render_html,
    "docx": render_docx,
}

FORMATS["faithful-pdf"] = FORMATS["overlay"]
