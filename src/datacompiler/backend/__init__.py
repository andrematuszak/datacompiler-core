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
from .html import rendre_html
from .markdown import rendre_markdown
from .rebuilt_pdf import render_rebuilt_pdf


def _ecrire_texte(fonction_rendu):
    def wrapper(doc, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(fonction_rendu(doc), encoding="utf-8")
        return output_path
    return wrapper


FORMATS = {
    "markdown": _ecrire_texte(rendre_markdown),
    "html": _ecrire_texte(rendre_html),
    "docx": render_docx,
    "rebuilt-pdf": render_rebuilt_pdf,
}

EXTENSIONS = {
    "markdown": "md",
    "html": "html",
    "docx": "docx",
    "rebuilt-pdf": "pdf",
}
