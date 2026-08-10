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


---------------------------------------------------------------------------
INSTRUMENTATION TEMPORAIRE (à retirer une fois le doublon localisé) :
_snapshot() prend une photo de la liste de mots à un point donné et logue
le compte total + les doublons détectés selon deux axes différents :

  - doublon "par valeur"   : deux mots (objets Python DIFFÉRENTS) qui ont
                              exactement le même texte affiché et le même
                              bbox (arrondi à 0.01pt, pour ignorer le bruit
                              flottant). Signature d'un mot recréé/recopié
                              deux fois quelque part.
  - doublon "par identité" : le MÊME objet Python présent deux fois dans
                              la liste (id() identique). Signature d'un
                              append/extend du même mot sans copie -- un
                              bug de nature différente du précédent, plus
                              probable si une étape construit sa liste de
                              sortie en réutilisant des références vers
                              l'entrée au lieu d'itérer proprement.

Les deux ne s'excluent pas : un doublon par identité EST forcément aussi
un doublon par valeur (même objet = mêmes attributs), mais l'inverse est
faux -- deux objets distincts peuvent coïncidemment avoir la même valeur
sans bug (rare avec un bbox à 2 décimales, mais pas impossible sur un mot
très court comme "1" ou "-"). D'où l'intérêt de loguer les deux séparément
plutôt qu'un seul chiffre agrégé.
---------------------------------------------------------------------------
"""


from collections import Counter
from copy import deepcopy


from datacompiler.model.document import Document


from . import alignment, conflict_resolution, layout, qa, reading_order, typography


def _cle_valeur_mot(mot):
    """(texte, bbox arrondi) -- clé pour détecter les doublons par valeur."""
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
    n = getattr(page, "number", "?")
    total = len(mots)

    cles = [_cle_valeur_mot(m) for m in mots]
    compte_valeur = Counter(cles)
    doublons_valeur = {c: cnt for c, cnt in compte_valeur.items() if cnt > 1}
    n_mots_touches_valeur = sum(doublons_valeur.values())

    ids_objets = [id(m) for m in mots]
    compte_identite = Counter(ids_objets)
    doublons_identite = {i: cnt for i, cnt in compte_identite.items() if cnt > 1}
    n_mots_touches_identite = sum(doublons_identite.values())

    print(f"[DEBUG] page {n} : {total} mots après {etape}"
          f"  |  doublons valeur: {len(doublons_valeur)} groupe(s) / {n_mots_touches_valeur} mot(s)"
          f"  |  doublons identité objet: {len(doublons_identite)} groupe(s) / {n_mots_touches_identite} mot(s)")

    if doublons_valeur:
        print(f"         exemples doublons VALEUR (objets distincts, même texte+bbox) :")
        for (texte, bbox), cnt in list(doublons_valeur.items())[:max_exemples]:
            print(f"           x{cnt}  texte={texte!r}  bbox={bbox}")

    if doublons_identite:
        print(f"         exemples doublons IDENTITÉ (même objet Python répété dans la liste) :")
        for obj_id, cnt in list(doublons_identite.items())[:max_exemples]:
            exemple_mot = next(m for m in mots if id(m) == obj_id)
            print(f"           x{cnt}  id={obj_id}  texte={_cle_valeur_mot(exemple_mot)[0]!r}")

    return mots


def _resoudre_page(page):
    n_page = getattr(page, "number", "?")
    print(f"[DEBUG] === page {n_page} : {len(page.native.words)} mots dans page.native.words (entrée) ===")

    mots_ordonnes = reading_order.ordonner(page)              # copies, ordre correct
    _snapshot("reading_order.ordonner", page, mots_ordonnes)

    mots_normalises = typography.normaliser(mots_ordonnes)    # ligatures + césures
    _snapshot("typography.normaliser", page, mots_normalises)

    if page.ocr.words and page.diagnostic.recommend_ocr:
        unites = alignment.aligner(mots_normalises, page.ocr.words)
        print(f"[DEBUG] page {n_page} : {len(unites)} unités après alignment.aligner "
              f"(pas de dédup value/identité ici -- structure différente d'un Word)")

        mots_resolus = conflict_resolution.resoudre_page(unites)
        _snapshot("conflict_resolution.resoudre_page (branche OCR)", page, mots_resolus)
    else:
        mots_resolus = mots_normalises
        print(f"[DEBUG] page {n_page} : branche SANS OCR -- mots_resolus = mots_normalises directement "
              f"({len(mots_resolus)} mots, page.ocr.words={bool(page.ocr.words)}, "
              f"page.diagnostic.recommend_ocr={page.diagnostic.recommend_ocr})")

    for mot in mots_resolus:
        mot.source = mot.source or "native"
        if not mot.resolved_text:
            mot.resolved_text = mot.output_text

    for i, mot in enumerate(mots_resolus, start=1):
        mot.id = i

    layout.assigner_lignes(mots_resolus)
    _snapshot("layout.assigner_lignes", page, mots_resolus)

    qa.annoter(mots_resolus)
    _snapshot("qa.annoter (sortie finale de _resoudre_page)", page, mots_resolus)

    return mots_resolus


def resoudre(doc: Document) -> Document:
    """Remplit page.resolved pour chaque page. Ne mute jamais page.native ni
    page.ocr (cf. reading_order.ordonner, qui copie dès le premier maillon)."""
    for page in doc.pages:
        page.resolved.words = _resoudre_page(page)
        page.resolved.images = deepcopy(page.graphics.images)
        page.resolved.tables = deepcopy(page.graphics.tables)
    return doc