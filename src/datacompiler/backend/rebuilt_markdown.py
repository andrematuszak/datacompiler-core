"""Render Markdown from ``page.resolved`` only. Native and OCR layers are consumed through the resolved output model."""

from datacompiler.model.document import Document
from datacompiler.compile.layout import grouper_par_ligne


def render_markdown(doc: Document) -> str:
    morceaux = ["<!-- rendu depuis : resolved -->\n"]

    for page in doc.pages:
        morceaux.append(f"\n## Page {page.number}\n")
        full_page_markdown = next(
            (
                block.content
                for block in page.ocr.blocks
                if block.type == "markdown" and block.content
            ),
            None,
        )
        if (
            full_page_markdown
            and page.routing
            and page.routing.strategy
            in {"full_page_mistral_ocr", "full_page_nvidia_ocr"}
        ):
            morceaux.append(full_page_markdown)
            morceaux.append("")
            continue

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
