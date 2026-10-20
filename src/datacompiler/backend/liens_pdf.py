"""Copy supported clickable links from the document model to an output PDF page. URI and internal-page links are supported; other link kinds are skipped."""
import logging

import pymupdf

logger = logging.getLogger(__name__)


def reinserer_liens(dst_page, model_page) -> int:
    """Recreate supported link annotations from the model page on the destination page and return the number inserted."""
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
            logger.warning("Page %s: link %s (%s) was not recreated", model_page.number, lien.id, lien.kind)
            continue
        inseres += 1
    return inseres
