"""markdown.py — Rendu Markdown, EXCLUSIVEMENT depuis page.resolved (jamais
native/ocr directement). Extrait de l'ancien render.py, logique inchangée à
part l'import de grouper_par_ligne (désormais output/layout.py, avec
le correctif de tri décrit dans ce module)."""

from datacompiler.model.document import Document
from datacompiler.compile.layout import grouper_par_ligne


def render_markdown(doc: Document) -> str:
    morceaux = ["<!-- rendu depuis : resolved -->\n"]

    for page in doc.pages:
        morceaux.append(f"\n## Page {page.number}\n")
        mots = page.resolved.words
        if mots:
            lignes = grouper_par_ligne(mots)
            for ligne in lignes:
                morceaux.append(" ".join(w.output_text for w in ligne))
            morceaux.append("")
        else:
            morceaux.append("*(page vide)*\n")

        for table in page.resolved.tables:
            morceaux.append("\n" + _table_en_markdown(table.rows))

    return "\n".join(morceaux)


def _table_en_markdown(rows):
    if not rows:
        return ""
    lignes_md = []
    for i, row in enumerate(rows):
        cellules = [str(c) if c is not None else "" for c in row]
        lignes_md.append("| " + " | ".join(cellules) + " |")
        if i == 0:
            lignes_md.append("|" + "|".join(["---"] * len(cellules)) + "|")
    return "\n".join(lignes_md) + "\n"
