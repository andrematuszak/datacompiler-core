"""compiler.py — Arbitrage des sources (natif + OCR) vers une couche de
sortie indépendante (page.resolved). Package plutôt que module unique : le
passthrough minimal de l'ancien resolve.py ne suffit plus dès qu'on gère
l'ordre de lecture, la typographie et les conflits natif/OCR -- chaque
préoccupation vit dans son propre fichier plutôt que dans une fonction
fourre-tout.


Pipeline par page, dans cet ordre (chaque étape suppose la précédente déjà
faite) :
  1. reading_order.ordonner            : ordre de lecture réel (colonnes,
                                          tableaux exclus) ; copie les mots
                                          natifs, ne les mute jamais en place.
  2. typography.normaliser             : ligatures, fusion des césures de
                                          fin de ligne.
  3. alignment.aligner                 : diff natif <-> OCR (si OCR dispo).
  4. conflict_resolution.resoudre_page : texte final par unité alignée.


`resoudre(doc)` garde la même signature que l'ancien resolve.py -- le futur
__init__.py racine peut continuer à faire `from compile import resoudre`
sans aucun changement.
"""


from copy import deepcopy


from model import Document


from . import alignment, conflict_resolution, layout, reading_order, typography




def _resoudre_page(page):
    mots_ordonnes = reading_order.ordonner(page)            # copies, ordre correct
    mots_normalises = typography.normaliser(mots_ordonnes)   # ligatures + césures


    if page.ocr.words:
        unites = alignment.aligner(mots_normalises, page.ocr.words)
        mots_resolus = conflict_resolution.resoudre_page(unites)
    else:
        mots_resolus = mots_normalises


    for mot in mots_resolus:
        mot.source = mot.source or "native"
        if not mot.resolved_text:
            mot.resolved_text = mot.output_text


    for i, mot in enumerate(mots_resolus, start=1):
        mot.id = i


    layout.assigner_lignes(mots_resolus)   # <-- nouveau


    return mots_resolus




def resoudre(doc: Document) -> Document:
    """Remplit page.resolved pour chaque page. Ne mute jamais page.native ni
    page.ocr (cf. reading_order.ordonner, qui copie dès le premier maillon)."""
    for page in doc.pages:
        page.resolved.words = _resoudre_page(page)
        page.resolved.images = deepcopy(page.graphics.images)
        page.resolved.tables = deepcopy(page.graphics.tables)
    return doc
