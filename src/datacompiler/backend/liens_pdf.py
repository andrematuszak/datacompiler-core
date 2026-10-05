"""liens_pdf.py -- remet les liens cliquables du modèle dans une page PDF de sortie.

Partagé par rebuilt_pdf et faithful_pdf. La zone cliquable est celle du PDF source (link.bbox) :
elle ne bouge pas avec le texte reconstruit. Les liens d'un autre genre que « uri » et « goto »
(lancement de fichier, nom nommé...) ne sont pas recréés.
"""
import logging

import pymupdf

logger = logging.getLogger(__name__)


def reinserer_liens(dst_page, model_page) -> int:
    """Recrée les annotations /Link de model_page.links sur dst_page. Retourne le nombre inséré."""
    inseres = 0
    for lien in getattr(model_page, "links", []):
        if lien.bbox is None:
            continue
        rect = pymupdf.Rect(lien.bbox.x0, lien.bbox.y0, lien.bbox.x1, lien.bbox.y1)
        if lien.kind == "uri" and lien.uri:
            dst_page.insert_link({"kind": pymupdf.LINK_URI, "from": rect, "uri": lien.uri})
        elif lien.kind == "goto" and lien.target_page:
            dst_page.insert_link({"kind": pymupdf.LINK_GOTO, "from": rect, "page": lien.target_page - 1})
        else:
            logger.warning("page %s : lien %s (%s) non recréé", model_page.number, lien.id, lien.kind)
            continue
        inseres += 1
    return inseres
