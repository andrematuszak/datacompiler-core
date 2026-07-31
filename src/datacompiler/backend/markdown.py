"""markdown.py — Rendu Markdown, EXCLUSIVEMENT depuis page.resolved (jamais
native/ocr directement). Extrait de l'ancien render.py, logique inchangée à
part l'import de _grouper_mots_en_lignes (désormais output/layout.py, avec
le correctif de tri décrit dans ce module)."""

from document import Document
from .layout import _grouper_mots_en_lignes


def rendre_markdown(doc: Document) -> str:
    morceaux = ["<!-- rendu depuis : resolved -->\n"]

    for page in doc.pages:
        morceaux.append(f"\n## Page {page.number}\n")
        mots = page.resolved.words
        if mots:
            lignes = _grouper_mots_en_lignes(mots)
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
