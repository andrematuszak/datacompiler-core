"""Arbitrage des sources vers une couche de sortie indépendante."""

from copy import deepcopy

from datacleaner.core.document import Document


def resoudre(doc: Document) -> Document:
    """Initialise la couche résolue sans jamais muter les données sources.

    L'alignement OCR avancé viendra ici. Cette version préserve déjà le
    contrat: un renderer ne consulte que ``resolved``.
    """
    for page in doc.pages:
        page.resolved.words = deepcopy(page.native.words)
        for word in page.resolved.words:
            word.source = word.source or "native"
            word.resolved_text = word.output_text
        page.resolved.images = deepcopy(page.graphics.images)
        page.resolved.tables = deepcopy(page.graphics.tables)
    return doc
