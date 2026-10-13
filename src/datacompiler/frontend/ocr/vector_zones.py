"""Orchestrate targeted OCR over vector-text regions found by diagnostics. Unlike page-wide OCR, this path renders and processes selected regions only."""

import math
import re
import statistics
from collections import Counter

import pymupdf

from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.frontend.extract.extract_pymupdf import rendre_zone_image
from datacompiler.frontend.ocr.fusion_ocr import fusionner_zone_multi_backend
from datacompiler.model.document import BBox, Document, Word
from datacompiler.utils.font_metrics import ratio_encre_em

MARGE_ZONE = 2.0  # pt -- contexte autour de la bbox détectée ; une zone trop serrée nuit à la reconnaissance OCR
MARGE_PONCTUATION_ISOLEE = 8.0  # pt -- contexte vertical/horizontal pour ponctuation entre mots natifs


def _hex_vers_rgb(hex_color: str) -> tuple:
    """Convert a #rrggbb string to integer RGB values. Kept local to avoid a frontend dependency on backend modules."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _couleur_encre_zone(page, zone: BBox):
    """Read the known fill color of vector elements overlapping a detected region."""
    x0, y0, x1, y1 = zone.x0, zone.y0, zone.x1, zone.y1
    couleurs = []
    for coll in (page.graphics.lines, page.graphics.curves, page.graphics.rects):
        for el in coll:
            if el.bbox is None or el.color is None:
                continue
            b = el.bbox
            ix0, iy0 = max(b.x0, x0), max(b.y0, y0)
            ix1, iy1 = min(b.x1, x1), min(b.y1, y1)
            if ix0 < ix1 and iy0 < iy1:
                couleurs.append(el.color)
    if not couleurs:
        return None
    # Couleur la plus frequente parmi les elements recouvrant la zone --
    # PAS une mediane par canal (un mot peut chevaucher a la marge un
    # element de couleur differente, ex. un trait de bordure de tableau ;
    # le mode resiste mieux a un petit nombre d'intrus que la mediane).
    plus_frequente = Counter(couleurs).most_common(1)[0][0]
    return _hex_vers_rgb(plus_frequente)


def _clipper_marge_sur_natifs(bbox_orig: BBox, marge: float, mots_natifs) -> BBox:
    """Expand a region by a margin, stopping before it overlaps an existing native word."""
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

def _sous_traces_drawing(d: dict) -> list:
    """Reconstruct closed subpaths from the drawing commands returned by PyMuPDF."""
    items = d.get("items", [])
    sous_traces, courant, dernier_point = [], [], None
    for it in items:
        typ = it[0]
        if typ in ("l", "c"):
            p0, p1 = it[1], it[-1]
            if dernier_point is not None and (
                abs(p0.x - dernier_point[0]) > 1e-4 or abs(p0.y - dernier_point[1]) > 1e-4
            ):
                if len(courant) >= 3:
                    sous_traces.append(courant)
                courant = []
            if not courant:
                courant.append((p0.x, p0.y))
            courant.append((p1.x, p1.y))
            dernier_point = (p1.x, p1.y)
        elif typ == "re":
            rect = it[1]
            sous_traces.append([(rect.x0, rect.y0), (rect.x1, rect.y0), (rect.x1, rect.y1), (rect.x0, rect.y1)])
            courant, dernier_point = [], None
    if len(courant) >= 3:
        sous_traces.append(courant)
    return sous_traces


def _aire_signee(points: list) -> float:
    """Formule du lacet (shoelace) -- aire signée d'un polygone fermé."""
    n = len(points)
    return sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    ) / 2.0


def _perimetre(points: list) -> float:
    n = len(points)
    return sum(
        math.hypot(points[(i + 1) % n][0] - points[i][0], points[(i + 1) % n][1] - points[i][1])
        for i in range(n)
    )


def _epaisseur_trait_glyphe(d: dict):
    """Estimate one glyph’s stroke width from its area and perimeter."""
    sous_traces = _sous_traces_drawing(d)
    if not sous_traces:
        return None
    aire = abs(sum(_aire_signee(st) for st in sous_traces))
    perimetre = sum(_perimetre(st) for st in sous_traces)
    return 2 * aire / perimetre if perimetre > 0 else None


def _epaisseur_mediane_zone(page_pymupdf, zone: BBox, seuil_recouvrement: float = 0.5,
                            dessins=None):
    """Estimate the median stroke width of vector glyphs overlapping a region."""
    valeurs = []
    dessins = dessins if dessins is not None else page_pymupdf.get_drawings()
    for d in dessins:
        r = d["rect"]
        ix0, iy0 = max(r.x0, zone.x0), max(r.y0, zone.y0)
        ix1, iy1 = min(r.x1, zone.x1), min(r.y1, zone.y1)
        if ix0 >= ix1 or iy0 >= iy1:
            continue
        aire_rect = (r.x1 - r.x0) * (r.y1 - r.y0)
        if aire_rect <= 0 or (ix1 - ix0) * (iy1 - iy0) / aire_rect < seuil_recouvrement:
            continue
        e = _epaisseur_trait_glyphe(d)
        if e is not None:
            valeurs.append(e)
    if not valeurs:
        return None
    valeurs.sort()
    return valeurs[len(valeurs) // 2]


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
    """Choose a threshold that maximizes between-class variance in a one-dimensional histogram."""
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
    """Estimate relative boldness from median stroke width; this is a geometric proxy, not font recognition."""
    valeurs = [m.stroke_width for m in mots if m.stroke_width is not None]
    if len(valeurs) < NB_MIN_MOTS_POUR_SEUIL:
        return
    seuil = _seuil_otsu(valeurs)
    if seuil is None:
        return
    for m in mots:
        if m.stroke_width is not None:
            m.bold = m.stroke_width > seuil

# à ajouter dans frontend/ocr/vector_zones.py, à côté de _assigner_gras_relatif

TOLERANCE_LIGNE = 2.0  # pt -- écart vertical max entre mots considérés sur la MÊME ligne visuelle


def _ratio_encre_mot(mot):
    texte = (mot.resolved_text or mot.text or "").strip()
    ratio = ratio_encre_em(texte, mot.bold, mot.italic)
    return ratio if ratio is not None and math.isfinite(ratio) and ratio > 0 else None


def _ajuster_ligne_sur_traces(ligne, dessins, zones_par_mot):
    """Calibrate an OCR line against the vector ink that produced it."""
    if not dessins:
        return False

    zones = [zones_par_mot.get(id(m)) for m in ligne]
    zones = [zone for zone in zones if zone is not None]
    if not zones:
        return False
    coords = [
        (zone.x0, zone.y0, zone.x1, zone.y1) if isinstance(zone, BBox) else zone
        for zone in zones
    ]
    zx0 = min(zone[0] for zone in coords)
    zy0 = min(zone[1] for zone in coords)
    zx1 = max(zone[2] for zone in coords)
    zy1 = max(zone[3] for zone in coords)

    # Seuls les mots issus d'une zone OCR (présents dans zones_par_mot) sont recalés sur les
    # tracés. Un mot reconstruit par géométrie (ex. la barre oblique de « 1 / 2 », cf.
    # _barre_oblique_entre_nombres) a déjà sa bbox exacte et n'a pas de zone : l'inclure dans
    # x0_ocr/x1_ocr puis dans la mise à l'échelle l'écrasait contre le dernier tracé OCR de la
    # ligne (page 2 : « / » déplacé de x=530 à x=510, sur l'emplacement du « : »).
    mots_ocr = [m for m in ligne if zones_par_mot.get(id(m)) is not None]
    if not mots_ocr:
        return False

    line_y0 = min(m.bbox.y0 for m in mots_ocr)
    line_y1 = max(m.bbox.y1 for m in mots_ocr)
    traces = []
    for dessin in dessins:
        rect = dessin.get("rect")
        if rect is None or rect.width <= 0 or rect.height <= 0:
            continue
        if rect.width > 30 or rect.height > 30:
            continue
        if rect.x1 <= zx0 or rect.x0 >= zx1 or rect.y1 <= zy0 or rect.y0 >= zy1:
            continue
        if rect.y1 <= line_y0 or rect.y0 >= line_y1:
            continue
        # Le trait doit appartenir à UN des mots de la ligne (centre dans sa bbox) : un simple
        # chevauchement vertical avec la plage de la ligne ramassait aussi l'encre de la ligne
        # voisine. Page 2 : « PARTS » (y0 147,4) est rattaché aux quatre « handicapés » (y0 ~150)
        # par la tolérance de ligne, ce qui étend la plage jusqu'à 147,4 -- et les lettres de
        # « enfants mineurs ou » / « dont enfants » (bas de l'encre à 148,2) y entraient. Leur
        # sommet (142,6) devenait alors le haut de « encre de la ligne », et tous les mots de la
        # ligne étaient remontés sur la ligne du dessus (y0 150,6 -> 142,6, x décalés, ordre
        # de lecture inversé dans les cellules).
        cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        if not any(m.bbox.x0 <= cx <= m.bbox.x1 and m.bbox.y0 <= cy <= m.bbox.y1 for m in mots_ocr):
            continue
        traces.append(rect)

    ratios = [_ratio_encre_mot(m) for m in mots_ocr]
    ratios = [ratio for ratio in ratios if ratio is not None]
    if not traces or not ratios:
        return False

    x0_traces = min(rect.x0 for rect in traces)
    x1_traces = max(rect.x1 for rect in traces)
    y0_traces = min(rect.y0 for rect in traces)
    baseline = statistics.median(rect.y1 for rect in traces)
    taille = (baseline - y0_traces) / max(ratios)
    if taille <= 0:
        return False

    x0_ocr = min(m.bbox.x0 for m in mots_ocr)
    x1_ocr = max(m.bbox.x1 for m in mots_ocr)
    largeur_ocr = x1_ocr - x0_ocr
    largeur_traces = x1_traces - x0_traces
    if largeur_ocr > 0 and largeur_traces > 0:
        echelle_x = largeur_traces / largeur_ocr
        for mot in mots_ocr:
            mot.bbox.x0 = x0_traces + (mot.bbox.x0 - x0_ocr) * echelle_x
            mot.bbox.x1 = x0_traces + (mot.bbox.x1 - x0_ocr) * echelle_x

    for mot in ligne:
        mot.font_size = taille
        if zones_par_mot.get(id(mot)) is None:
            continue   # géométrie déjà exacte : on ne lui donne que la taille de la ligne
        ratio = _ratio_encre_mot(mot)
        if ratio is not None:
            decalage_y = baseline - taille * ratio - mot.bbox.y0
            mot.bbox.y0 += decalage_y
            mot.bbox.y1 += decalage_y
    return True


def _assigner_taille_lissee(mots, dessins=None, zones_par_mot=None):
    """Smooth estimated font size per visual line using source vector geometry."""
    candidats = [m for m in mots if m.is_vectorized and m.bbox is not None]
    if not candidats:
        return
    candidats.sort(key=lambda m: m.bbox.y0)
    zones_par_mot = zones_par_mot or {}

    def _cloturer(ligne):
        if _ajuster_ligne_sur_traces(ligne, dessins, zones_par_mot):
            return

        tailles = []
        for m in ligne:
            ratio = _ratio_encre_mot(m)
            hauteur = m.bbox.y1 - m.bbox.y0
            tailles.append(hauteur / ratio if ratio is not None else hauteur)
        mediane = statistics.median(tailles)
        for m in ligne:
            m.font_size = mediane

    ligne = [candidats[0]]
    for m in candidats[1:]:
        if abs(m.bbox.y0 - ligne[-1].bbox.y0) <= TOLERANCE_LIGNE:
            ligne.append(m)
        else:
            _cloturer(ligne)
            ligne = [m]
    _cloturer(ligne)

def _chevauche_bbox(a, b):
    """AABB overlap entre deux boîtes,
    appliquée ici aux ZONES (après expansion par MARGE_ZONE)."""
    return not (a.x1 <= b.x0 or b.x1 <= a.x0 or a.y1 <= b.y0 or b.y1 <= a.y0)


def _fusionner_zones_chevauchantes(zones):
    """Merge already-expanded regions whose bounding boxes overlap."""
    courantes = list(zones)
    while True:
        fusionnees = _fusionner_une_passe(courantes)
        if len(fusionnees) == len(courantes):
            return fusionnees
        courantes = fusionnees


def _fusionner_une_passe(zones):
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
    """Return whether an OCR word substantially overlaps native text that was already extracted."""
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


def _barre_oblique_entre_nombres(zone: BBox, mots_natifs) -> Word | None:
    """Recognize an isolated vector slash between two native numbers."""
    largeur, hauteur = zone.x1 - zone.x0, zone.y1 - zone.y0
    if not (1.5 <= largeur <= 4.0 and 5.0 <= hauteur <= 10.0):
        return None
    ratio = largeur / hauteur
    if not 0.25 <= ratio <= 0.55:
        return None

    chevauchement_min = 0.6 * hauteur
    gauche = [
        mot for mot in mots_natifs
        if mot.bbox
        and re.fullmatch(r"\d+", (mot.text or "").strip())
        and mot.bbox.x1 <= zone.x0
        and zone.x0 - mot.bbox.x1 <= 8.0
        and min(zone.y1, mot.bbox.y1) - max(zone.y0, mot.bbox.y0) >= chevauchement_min
    ]
    droite = [
        mot for mot in mots_natifs
        if mot.bbox
        and re.fullmatch(r"\d+", (mot.text or "").strip())
        and mot.bbox.x0 >= zone.x1
        and mot.bbox.x0 - zone.x1 <= 8.0
        and min(zone.y1, mot.bbox.y1) - max(zone.y0, mot.bbox.y0) >= chevauchement_min
    ]
    if not gauche or not droite:
        return None
    # Pas de garde « nombre de gauche != nombre de droite » : « Feuillet n° : 2 / 2 » (page 3 de
    # l'avis d'impôt, dernier feuillet = nombre de feuillets) a deux nombres identiques de part
    # et d'autre de la barre, qui était alors perdue.

    return Word(
        id=-1,
        text="/",
        resolved_text="/",
        bbox=zone,
        source="vector_geometry",
        is_vectorized=True,
        reconstructed=True,
        notes=["barre oblique vectorielle entre deux nombres natifs"],
    )


def recuperer_texte_vectorise(doc: Document, pdf_path: str, backends, lang: str = "fra", dpi: int = 300) -> Document:
    """Run targeted OCR on detected vector-text regions and add recovered words to the document."""
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
            zones_ocr = []
            mots_page = []
            for coords in zones:
                zone = BBox(*coords)
                barre = _barre_oblique_entre_nombres(zone, mots_natifs_existants)
                if barre is not None:
                    mots_page.append(barre)
                else:
                    zones_ocr.append(zone)

            zones_marginees = [
                _clipper_marge_sur_natifs(
                    zone,
                    MARGE_PONCTUATION_ISOLEE
                    if zone.x1 - zone.x0 <= 4.0 and zone.y1 - zone.y0 <= 12.0
                    else MARGE_ZONE,
                    mots_natifs_existants,
                )
                for zone in zones_ocr
            ]
            zones_a_traiter = _fusionner_zones_chevauchantes(zones_marginees)

            page_pymupdf = source[i]
            dessins_page = page_pymupdf.get_drawings()
            # Les backends OCR laissent id=-1 sur les
            # mots OCR en promettant une "renumérotation finale par
            # compile/compiler.py" -- vrai UNIQUEMENT pour page.resolved.words
            # (une copie, cf. reading_order.ordonner), JAMAIS pour
            # page.native.words lui-même, où ces mots sont injectés
            # directement. Sans ce correctif, tous les mots OCR d'une même
            # page partagent id=-1 -- inoffensif tant que rien ne s'appuie
            # sur l'unicité de l'id, mais bloquant pour LayoutBox.word_ids
            # (impossible de savoir lequel de plusieurs -1 est référencé).
            prochain_id = max((w.id for w in mots_natifs_existants if w.id and w.id > 0), default=0) + 1
            for mot in mots_page:
                mot.id = prochain_id
                prochain_id += 1
            # accumulés avant extend -- cf. _assigner_gras_relatif (seuil PAR PAGE)
            zones_par_mot = {}
            for zone in zones_a_traiter:
                image, _ = rendre_zone_image(page_pymupdf, zone, dpi=dpi)
                couleur_encre = _couleur_encre_zone(page, zone)
                mots = fusionner_zone_multi_backend(
                    image, offset=(zone.x0, zone.y0), backends=backends_utilisables, dpi=dpi, lang=lang,
                    couleur_encre=couleur_encre,
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
                # Epaisseur de trait calculee UNE FOIS par zone (pas par mot) --
                # tous les mots d'une meme zone partagent la meme mediane, cf.
                # _epaisseur_mediane_zone. Remplace ink_ratio pour la decision
                # `bold` (cf. _assigner_gras_relatif) ; ink_ratio reste calcule
                # cote paddle.py a titre diagnostique (notes du mot) seulement.
                for m in mots_valides:
                    m.id = prochain_id
                    prochain_id += 1
                    epaisseur = _epaisseur_mediane_zone(
                        page_pymupdf, m.bbox, dessins=dessins_page
                    )
                    m.stroke_width = epaisseur
                    m.notes = list(m.notes or []) + [
                        f"stroke_width={epaisseur:.4f}" if epaisseur is not None else "stroke_width=None"
                    ]
                    zones_par_mot[id(m)] = zone
                mots_page.extend(mots_valides)
            _assigner_gras_relatif(mots_page)
            _assigner_taille_lissee(mots_page, dessins_page, zones_par_mot)
            page.native.words.extend(mots_page)
    finally:
        source.close()

    return doc
