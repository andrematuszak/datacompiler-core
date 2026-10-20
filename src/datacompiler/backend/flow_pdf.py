"""Render a new, selectable PDF from ``page.resolved`` using a linear reading order and flowing layout. This renderer prioritizes readable text flow over reproducing the source geometry."""

from pathlib import Path
import pymupdf
from datacompiler.model.document import Document
from datacompiler.compile.layout import grouper_par_ligne
from .faithful_pdf import _FALLBACK_FONTNAME, _FALLBACK_FONTFILE, _font_objet

MARGE = 50.0
TAILLE_POLICE = 10.5
TAILLE_TITRE = 13.0
INTERLIGNE = 14.0
_LARGEUR_PAGE, _HAUTEUR_PAGE = pymupdf.paper_size("a4")


def render_flow_pdf(doc: Document, output_path: str) -> str:
    output = pymupdf.open()
    _font_objet(_FALLBACK_FONTNAME, _FALLBACK_FONTFILE)  # charge/vérifie la police avant d'écrire

    etat = {"page": output.new_page(width=_LARGEUR_PAGE, height=_HAUTEUR_PAGE), "y": MARGE}

    def nouvelle_page():
        etat["page"] = output.new_page(width=_LARGEUR_PAGE, height=_HAUTEUR_PAGE)
        etat["y"] = MARGE

    def ecrire(texte, fontsize=TAILLE_POLICE):
        if not texte.strip():
            return
        if etat["y"] > _HAUTEUR_PAGE - MARGE:
            nouvelle_page()
        etat["page"].insert_text((MARGE, etat["y"]), texte, fontsize=fontsize,
                                 fontname=_FALLBACK_FONTNAME, fontfile=_FALLBACK_FONTFILE)
        etat["y"] += INTERLIGNE if fontsize <= TAILLE_POLICE else INTERLIGNE * 1.4

    for page in doc.pages:
        ecrire(f"Page {page.number}", fontsize=TAILLE_TITRE)
        etat["y"] += INTERLIGNE * 0.4

        for ligne in grouper_par_ligne(page.resolved.words):
            ecrire(" ".join(m.output_text for m in ligne))

        for table in page.resolved.tables:
            etat["y"] += INTERLIGNE * 0.4
            for row in table.rows:
                ecrire(" | ".join(str(c) if c is not None else "" for c in row))

        etat["y"] += INTERLIGNE

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    output.set_metadata({"producer": "DataCompiler rebuilt_pdf", "title": doc.metadata.filename})
    output.save(output_path, garbage=4, deflate=True)
    output.close()
    return output_path
