"""Resolve native and OCR sources into the independent ``page.resolved`` layer. The per-page pipeline normalizes typography, establishes reading order, aligns sources, resolves conflicts, and runs quality checks."""


from collections import Counter
from copy import deepcopy
import logging


from datacompiler.model.document import Document


from . import alignment, conflict_resolution, layout, links, qa, reading_order, typography

logger = logging.getLogger(__name__)


def _cle_valeur_mot(mot):
    """Build a duplicate-detection key from a word’s text and rounded bounding box."""
    bbox = getattr(mot, "bbox", None)
    bbox_cle = None
    if bbox is not None:
        try:
            bbox_cle = (round(bbox.x0, 2), round(bbox.y0, 2), round(bbox.x1, 2), round(bbox.y1, 2))
        except AttributeError:
            try:
                bbox_cle = tuple(round(v, 2) for v in bbox)
            except TypeError:
                bbox_cle = repr(bbox)
    texte = (getattr(mot, "resolved_text", None) or getattr(mot, "output_text", None)
             or getattr(mot, "text", None) or "")
    return (texte, bbox_cle)


def _snapshot(etape, page, mots, max_exemples=6):
    n_page = getattr(page, "number", "?")
    total = len(mots)

    cles = [_cle_valeur_mot(m) for m in mots]
    compte_valeur = Counter(cles)
    doublons_valeur = {c: cnt for c, cnt in compte_valeur.items() if cnt > 1}
    n_mots_touches_valeur = sum(doublons_valeur.values())

    ids_objets = [id(m) for m in mots]
    compte_identite = Counter(ids_objets)
    doublons_identite = {i: cnt for i, cnt in compte_identite.items() if cnt > 1}
    n_mots_touches_identite = sum(doublons_identite.values())

    if doublons_valeur or doublons_identite:
        logger.warning(
            "[DUPLICATE] page %s, stage '%s': total=%d, "
            "value_duplicates=%d affected word(s) across %d group(s), "
            "identity_duplicates=%d affected word(s) across %d object(s)",
            n_page, etape, total,
            n_mots_touches_valeur, len(doublons_valeur),
            n_mots_touches_identite, len(doublons_identite),
        )
        for i, ((texte, bbox_cle), cnt) in enumerate(doublons_valeur.items()):
            if i >= max_exemples:
                logger.warning("  ... (%d additional group(s) omitted)",
                                len(doublons_valeur) - max_exemples)
                break
            logger.warning("  value x%d: text=%r bbox=%s", cnt, texte, bbox_cle)

    return mots


def _resoudre_page(page):
    n_page = getattr(page, "number", "?")
    mots_ordonnes = reading_order.ordonner(page)
    _snapshot("reading_order.ordonner", page, mots_ordonnes)

    mots_normalises = typography.normaliser(mots_ordonnes)    # ligatures + césures
    _snapshot("typography.normaliser", page, mots_normalises)

    if page.ocr.words and page.diagnostic.recommend_ocr:
        unites = alignment.aligner(mots_normalises, page.ocr.words)
        mots_resolus = conflict_resolution.resoudre_page(unites)
        _snapshot("conflict_resolution.resoudre_page (branche OCR)", page, mots_resolus)
    else:
        mots_resolus = mots_normalises

    for mot in mots_resolus:
        mot.source = mot.source or "native"
        if not mot.resolved_text:
            mot.resolved_text = mot.output_text

    for i, mot in enumerate(mots_resolus, start=1):
        mot.id = i

    layout.assigner_lignes(mots_resolus)
    _snapshot("layout.assigner_lignes", page, mots_resolus)

    qa.annoter(mots_resolus, page.graphics.tables)
    _snapshot("qa.annoter (sortie finale de _resoudre_page)", page, mots_resolus)

    return mots_resolus


def resoudre(doc: Document) -> Document:
    """Populate ``page.resolved`` without mutating the native or OCR layers."""
    for page in doc.pages:
        page.resolved.words = _resoudre_page(page)
        page.resolved.images = deepcopy(page.graphics.images)
        page.resolved.tables = deepcopy(page.graphics.tables)
        links.associer_liens(page)
    return doc