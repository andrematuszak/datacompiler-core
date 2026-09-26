"""vector_zones.py — Orchestration de l'OCR ciblé sur les zones de texte
vectorisé détectées par diagnostic/vector_text.py.

Différence avec ocr/tesseract.py et ocr/mistral.py en mode page entière :
ceux-là remplissent page.ocr, en attente d'un arbitrage dans compile/
(alignment.py + conflict_resolution.py) contre page.native.words existant.
Ici il n'y a RIEN à arbitrer -- pas de désaccord, un vide géométrique à
combler. Les mots produits sont donc injectés directement dans
page.native.words (is_vectorized=True, source="ocr_vectoriel"), EN AMONT
du pipeline compile/ : ils traversent reading_order/typography comme
n'importe quel mot natif, sans jamais passer par alignment.py.

Accepte PLUSIEURS backends (dict nom -> instance) exposant ocraliser_zone()
(cf. ocr/base.py) -- fusionnés zone par zone via fusion_ocr.py quand
plusieurs sont fournis et disponibles (ex. Tesseract + PaddleOCR). Un seul
backend dans le dict reste un cas valide (fusion_ocr.fusionner_candidats_ocr
sur un seul candidat = pas d'arbitrage à faire, comportement inchangé).
Fonctionne indépendamment de MISTRAL_API_KEY -- Mistral n'expose pas
ocraliser_zone (bbox bloc, pas par mot) et serait simplement ignoré s'il
apparaissait dans le dict (cf. fusion_ocr.fusionner_zone_multi_backend,
qui journalise et saute tout backend en échec plutôt que de planter).
"""

import pymupdf

from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.frontend.extract.extract_pymupdf import rendre_zone_image
from datacompiler.frontend.ocr.fusion_ocr import fusionner_zone_multi_backend
from datacompiler.model.document import BBox, Document

MARGE_ZONE = 2.0  # pt -- contexte autour de la bbox détectée ; une zone trop serrée nuit à Tesseract


def _clipper_marge_sur_natifs(bbox_orig: BBox, marge: float, mots_natifs) -> BBox:
    """Etend `bbox_orig` de `marge` de chaque cote, SAUF si ca empieterait
    sur un mot NATIF existant -- la marge est alors coupee juste avant ce
    mot au lieu de l'empieter aveuglement.

    Cause reelle identifiee (session du 25/09/2026, test-impots-
    revenu.pdf) : la zone vectorisee "DIRECTION" (bas a y=28.7pt) + marge
    aveugle (30.7pt) mangeait 2.8pt dans le mot natif "Impôt" juste en
    dessous (haut a y=27.9pt, meme colonne x) -- le crop envoye a l'OCR
    contenait donc un fragment du mot natif voisin, contaminant la
    mesure d'ink_ratio (cf. paddle.py) et vraisemblablement la
    segmentation elle-meme (Andre : "impossible de saisir DIRECTION sans
    saisir Impôt" sur le PDF reconstruit -- signe d'une boite fusionnee).
    """
    x0, y0, x1, y1 = bbox_orig.x0, bbox_orig.y0, bbox_orig.x1, bbox_orig.y1
    mx0, my0, mx1, my1 = x0 - marge, y0 - marge, x1 + marge, y1 + marge
    for w in mots_natifs:
        b = w.bbox
        if b is None:
            continue
        chevauche_x = min(x1, b.x1) - max(x0, b.x0)  # ampleur du recouvrement horizontal (negatif = aucun)
        chevauche_y = min(y1, b.y1) - max(y0, b.y0)  # ampleur du recouvrement vertical
        if chevauche_x <= 0 and chevauche_y <= 0:
            continue  # pas de recouvrement du tout -- ni ligne ni colonne commune, pas un voisin direct
        # Un seul axe est coupe par mot natif : celui du PLUS PETIT
        # recouvrement -- un grand recouvrement horizontal + un tout petit
        # recouvrement vertical (ex. DIRECTION/Impôt : 37.8pt vs 0.8pt)
        # signifie "empile verticalement", pas "voisin de chaque cote a
        # la fois". Sans ce choix, un chevauchement marginal sur l'axe
        # perpendiculaire declenchait aussi (a tort) la coupe de l'autre
        # axe (bug identifie en test unitaire, session du 25/09/2026).
        if chevauche_y < chevauche_x:  # empilement vertical -> coupe my0 ou my1
            if (b.y0 + b.y1) / 2 < (y0 + y1) / 2:
                my0 = max(my0, b.y1)
            else:
                my1 = min(my1, b.y0)
        else:  # voisinage horizontal -> coupe mx0 ou mx1
            if (b.x0 + b.x1) / 2 < (x0 + x1) / 2:
                mx0 = max(mx0, b.x1)
            else:
                mx1 = min(mx1, b.x0)
    return BBox(mx0, my0, mx1, my1)

# EMPIRIQUE, teste sur test-impots-revenu.pdf uniquement (session du
# 25/09/2026) -- pas de validation sur corpus elargi.
#
# v1 (abandonnee) : bold = ink_ratio > 1.15 * MEDIANE de la page. Rejetee
# apres test reel : sur une page ou la plupart des mots vectorises sont
# DEJA en gras (ex. section "Vos references", quasi tous les libelles),
# la mediane elle-meme se retrouve proche du cluster "gras" -- le seuil
# relatif ne laisse alors passer que les quelques mots les PLUS au-dessus
# du lot, et la majorite des mots pourtant gras repasse sous le seuil.
# Un multiplicateur fixe suppose implicitement un melange ~50/50 gras/
# non-gras par page, faux ici.
#
# v2 (celle-ci) : seuil d'Otsu (1D) sur la distribution des ink_ratio de
# la page -- cherche le seuil qui MAXIMISE la separation entre les deux
# classes plutot que de supposer leur proportion. S'adapte, en principe,
# a une page tres majoritairement grasse ou tres majoritairement non-
# grasse -- pas verifie sur un nouveau cas reel, cf. ink_ratio maintenant
# journalise dans Word.notes (ocr/paddle.py) pour objectiver le prochain
# test au lieu de deviner sur rendu visuel seul.
NB_MIN_MOTS_POUR_SEUIL = 3
NB_BINS_OTSU = 16


def _seuil_otsu(valeurs, nb_bins=NB_BINS_OTSU):
    """Seuil qui maximise la variance INTER-classe d'un histogramme a
    `nb_bins` de `valeurs` (methode d'Otsu, 1D) -- s'adapte au
    desequilibre des classes, contrairement a un multiplicateur fixe de
    la mediane (cf. note v1/v2 ci-dessus). Retourne None si `valeurs` est
    degenere (toutes identiques)."""
    vmin, vmax = min(valeurs), max(valeurs)
    if vmax <= vmin:
        return None
    largeur = (vmax - vmin) / nb_bins
    bornes = [vmin + k * largeur for k in range(nb_bins + 1)]
    effectifs = [0] * nb_bins
    for v in valeurs:
        k = min(int((v - vmin) / largeur), nb_bins - 1)
        effectifs[k] += 1
    centres = [(bornes[k] + bornes[k + 1]) / 2 for k in range(nb_bins)]
    total = sum(effectifs)
    somme_totale = sum(e * c for e, c in zip(effectifs, centres))

    poids_fond = 0
    somme_fond = 0.0
    meilleure_variance = -1.0
    meilleur_seuil = None
    for k in range(nb_bins):
        poids_fond += effectifs[k]
        if poids_fond == 0:
            continue
        poids_avant = total - poids_fond
        if poids_avant == 0:
            break
        somme_fond += effectifs[k] * centres[k]
        moyenne_fond = somme_fond / poids_fond
        moyenne_avant = (somme_totale - somme_fond) / poids_avant
        variance_inter = poids_fond * poids_avant * (moyenne_fond - moyenne_avant) ** 2
        if variance_inter > meilleure_variance:
            meilleure_variance = variance_inter
            meilleur_seuil = bornes[k + 1]
    return meilleur_seuil


def _assigner_gras_relatif(mots):
    """Decide `bold`, par mot, a partir de `ink_ratio` -- PROXY
    GEOMETRIQUE, PAS UNE DETECTION DE POLICE. Modifie `mots` en place."""
    ratios = [m.ink_ratio for m in mots if m.ink_ratio is not None]
    if len(ratios) < NB_MIN_MOTS_POUR_SEUIL:
        return
    seuil = _seuil_otsu(ratios)
    if seuil is None:
        return
    for m in mots:
        if m.ink_ratio is not None:
            m.bold = m.ink_ratio > seuil

def _chevauche_bbox(a, b):
    """AABB overlap -- même logique que _chevauche dans tesseract.py,
    appliquée ici aux ZONES (après expansion par MARGE_ZONE)."""
    return not (a.x1 <= b.x0 or b.x1 <= a.x0 or a.y1 <= b.y0 or b.y1 <= a.y0)


def _fusionner_zones_chevauchantes(zones):
    """Fusionne par composantes connexes les zones (déjà marginées) dont
    les bbox se chevauchent -- même principe que
    vector_text._grouper_par_proximite, appliqué aux zones plutôt qu'aux
    éléments vectoriels bruts."""
    n = len(zones)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _chevauche_bbox(zones[i], zones[j]):
                union(i, j)

    composantes = {}
    for i, z in enumerate(zones):
        composantes.setdefault(find(i), []).append(z)

    return [
        BBox(
            min(z.x0 for z in membres),
            min(z.y0 for z in membres),
            max(z.x1 for z in membres),
            max(z.y1 for z in membres),
        )
        for membres in composantes.values()
    ]

def _chevauche_natif(mot, mots_natifs, seuil_recouvrement=0.5):
    """True si `mot` (produit par OCR de zone) recouvre significativement un
    mot déjà natif -- signe qu'il duplique du texte déjà bien extrait par
    PyMuPDF plutôt que de combler un vrai vide.

    Nécessaire depuis l'ajout de _fusionner_zones_chevauchantes : la fusion
    produit un rectangle ENGLOBANT plusieurs zones individuellement validées
    par vector_text._mot_natif_present, mais ce rectangle peut avaler une
    portion de texte natif située ENTRE deux zones fusionnées -- jamais
    couverte par aucune zone individuelle, donc jamais testée en amont. Le
    crop+OCR du rectangle plus large relit alors ce texte natif et produit un
    doublon -- pas un faux positif de détection de zone, un effet de bord de
    la fusion géométrique elle-même."""
    if not mot.bbox:
        return False
    for nat in mots_natifs:
        if not nat.bbox:
            continue
        x0 = max(mot.bbox.x0, nat.bbox.x0)
        y0 = max(mot.bbox.y0, nat.bbox.y0)
        x1 = min(mot.bbox.x1, nat.bbox.x1)
        y1 = min(mot.bbox.y1, nat.bbox.y1)
        if x0 < x1 and y0 < y1:
            intersection = (x1 - x0) * (y1 - y0)
            aire_mot = (mot.bbox.x1 - mot.bbox.x0) * (mot.bbox.y1 - mot.bbox.y0)
            if aire_mot > 0 and intersection / aire_mot >= seuil_recouvrement:
                return True
    return False


def recuperer_texte_vectorise(doc: Document, pdf_path: str, backends, lang: str = "fra", dpi: int = 300) -> Document:
    """
    backends : dict {nom: instance_de_backend}, ex.
        {"tesseract": TesseractBackend(...)}
        {"tesseract": TesseractBackend(...), "paddleocr": PaddleOCRBackend(...)}
    Un backend UNIQUE (pas dans un dict) est aussi accepté, par souplesse --
    pratique pour un appelant qui n'a qu'un seul moteur à passer (ex.
    pipeline.py avant que PaddleOCR ne soit branché) sans avoir à
    construire un dict à un seul élément à chaque appel.

    Chaque backend doit exposer ocraliser_zone() (cf. ocr/base.py) pour être
    utilisable ici -- les autres (Mistral) sont ignorés silencieusement par
    fusion_ocr.fusionner_zone_multi_backend, pas par ce module.
    """
    if not isinstance(backends, dict):
        if hasattr(backends, "ocraliser_zone"):
            backends = {"default": backends}
        else:
            return doc

    backends_utilisables = {nom: b for nom, b in backends.items() if hasattr(b, "ocraliser_zone")}
    if not backends_utilisables:
        return doc

    source = pymupdf.open(pdf_path)
    try:
        for i, page in enumerate(doc.pages):
            zones = zones_texte_vectorise_probable(page)
            if not zones:
                continue

            mots_natifs_existants = page.native.words  # référence avant tout ajout, pour cette page -- deplacé avant zones_marginees, cf. _clipper_marge_sur_natifs
            zones_marginees = [
                _clipper_marge_sur_natifs(BBox(x0, y0, x1, y1), MARGE_ZONE, mots_natifs_existants)
                for x0, y0, x1, y1 in zones
            ]
            zones_a_traiter = _fusionner_zones_chevauchantes(zones_marginees)

            page_pymupdf = source[i]
            # Les backends (tesseract.py, paddle.py) laissent id=-1 sur les
            # mots OCR en promettant une "renumérotation finale par
            # compile/compiler.py" -- vrai UNIQUEMENT pour page.resolved.words
            # (une copie, cf. reading_order.ordonner), JAMAIS pour
            # page.native.words lui-même, où ces mots sont injectés
            # directement. Sans ce correctif, tous les mots OCR d'une même
            # page partagent id=-1 -- inoffensif tant que rien ne s'appuie
            # sur l'unicité de l'id, mais bloquant pour LayoutBox.word_ids
            # (impossible de savoir lequel de plusieurs -1 est référencé).
            prochain_id = max((w.id for w in mots_natifs_existants if w.id and w.id > 0), default=0) + 1
            mots_page = []  # accumulés avant extend -- cf. _assigner_gras_relatif (seuil PAR PAGE)
            for zone in zones_a_traiter:
                image, _ = rendre_zone_image(page_pymupdf, zone, dpi=dpi)
                mots = fusionner_zone_multi_backend(
                    image, offset=(zone.x0, zone.y0), backends=backends_utilisables, dpi=dpi, lang=lang
                )
                if not mots:
                    continue
                # Filtre AVANT ajout : un mot OCR qui recouvre significativement
                # du natif existant est un doublon dû à la fusion de zones
                # (cf. _chevauche_natif), pas une vraie récupération. S'applique
                # de la même façon quel que soit le backend d'origine du mot,
                # puisque fusion_ocr a déjà réduit à un seul candidat par zone
                # de chevauchement avant qu'on arrive ici.
                mots_valides = [m for m in mots if not _chevauche_natif(m, mots_natifs_existants)]
                for m in mots_valides:
                    m.id = prochain_id
                    prochain_id += 1
                mots_page.extend(mots_valides)
            _assigner_gras_relatif(mots_page)
            page.native.words.extend(mots_page)
    finally:
        source.close()

    return doc
