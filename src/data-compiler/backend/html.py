"""html.py — Rendu HTML ("Document Flow" : empilement en ordre de lecture,
hauteur libre), EXCLUSIVEMENT depuis page.resolved. Extrait de l'ancien
render.py, logique inchangée à part l'import de _grouper_mots_en_lignes."""

from document import Document
from .layout import _grouper_mots_en_lignes


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
