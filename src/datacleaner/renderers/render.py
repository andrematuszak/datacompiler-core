"""
render.py — Reconstruit un document lisible EXCLUSIVEMENT à partir de
doc.pages[i].resolved (jamais native/ocr directement, comme demandé).
Ça ne fonctionne aujourd'hui que parce que resolve.py (même minimal, en
passthrough) garantit que resolved existe toujours.

Deux formats : markdown et html (mode "Document Flow", validé en session
précédente : empilement en ordre de lecture, hauteur libre).

Usage : python render.py document.json [--format markdown|html] [-o sortie]
"""

import argparse

from datacleaner.core.document import Document


def _grouper_mots_en_lignes(mots, tolerance_y=3):
    """Regroupe les Word (avec bbox) en lignes par position verticale, trie
    chaque ligne par x. mots doit être une liste de Word avec .bbox (objet
    BBox, pas une liste -- x0/y0/x1/y1 en attributs)."""
    mots_avec_bbox = [w for w in mots if w.bbox]
    mots_tries = sorted(mots_avec_bbox, key=lambda w: (w.bbox.y0, w.bbox.x0))

    lignes = []
    ligne_courante = []
    y_courant = None
    for mot in mots_tries:
        y = mot.bbox.y0
        if y_courant is None or abs(y - y_courant) <= tolerance_y:
            ligne_courante.append(mot)
            y_courant = y if y_courant is None else y_courant
        else:
            lignes.append(sorted(ligne_courante, key=lambda w: w.bbox.x0))
            ligne_courante = [mot]
            y_courant = y
    if ligne_courante:
        lignes.append(sorted(ligne_courante, key=lambda w: w.bbox.x0))
    return lignes


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


def rendre_html(doc: Document, largeur_affichage=700) -> str:
    morceaux = [f'<div style="font-family:Arial,sans-serif;max-width:{largeur_affichage}px;margin:auto;">']
    morceaux.append('<p style="color:#888;font-size:11px;">rendu depuis : resolved</p>')

    for page in doc.pages:
        morceaux.append(f'<h3 style="border-bottom:1px solid #ccc;">Page {page.number}</h3>')
        mots = page.resolved.words
        if mots:
            lignes = _grouper_mots_en_lignes(mots)
            for ligne in lignes:
                texte = " ".join(w.output_text for w in ligne).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                morceaux.append(f'<div style="margin:2px 0; font-size:13px;">{texte}</div>')
        else:
            morceaux.append("<p><em>(page vide)</em></p>")

        for table in page.resolved.tables:
            morceaux.append(_table_en_html(table.rows))

    morceaux.append("</div>")
    return "\n".join(morceaux)


def _table_en_html(rows):
    if not rows:
        return ""
    html = ['<table style="border-collapse:collapse;margin:8px 0;">']
    for row in rows:
        html.append("<tr>" + "".join(
            f'<td style="border:1px solid #ccc;padding:4px;font-size:12px;">{c or ""}</td>' for c in row
        ) + "</tr>")
    html.append("</table>")
    return "".join(html)


FORMATS = {
    "markdown": rendre_markdown,
    "html": rendre_html,
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rendu d'un Document (JSON) depuis resolved uniquement")
    parser.add_argument("document_json", help="Chemin du document.json à rendre")
    parser.add_argument("--format", choices=list(FORMATS.keys()), default="markdown")
    parser.add_argument("-o", "--output", default=None)
    args = parser.parse_args()

    doc = Document.load(args.document_json)
    resultat = FORMATS[args.format](doc)

    extension = {"markdown": "md", "html": "html"}[args.format]
    sortie = args.output or (args.document_json.rsplit(".", 1)[0] + f".{extension}")
    with open(sortie, "w", encoding="utf-8") as f:
        f.write(resultat)
    print(f"Écrit : {sortie}")
