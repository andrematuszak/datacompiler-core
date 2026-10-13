"""Determine native-word reading order by grouping words into physical regions and rows. The algorithm supports multi-column layouts and preserves deterministic output."""

import itertools
from copy import deepcopy
from collections import defaultdict

from datacompiler.utils.heuristics_geometry import dans_un_tableau, mot_dans_cellule
from datacompiler.frontend.layout.detectors import detecter_boites_encadres


SEUIL_CHEVAUCHEMENT_RANGEE = 0.3   # fraction de la + petite hauteur, pour dire "même rangée"
DILATATION_CLUSTERING_VECTO = 8.0  # pt, marge de tolérance pour fusionner des mots vectorisés proches
# Un lien (annotation /Link) dont la zone cliquable couvre plus de cette part de la page n'est pas
# un petit encadré de texte (ex. lien sur toute la page, sur une table) : il n'est pas traité comme
# un conteneur de lecture.
PART_PAGE_MAX_CONTENEUR_LIEN = 0.15

TOLERANCE_LIGNE = 3.5              # pt, écart de y0 toléré pour dire "même ligne" (bruit OCR)
# Un partenaire dont le y0 est à moins de ECART_Y0_MEME_LIGNE de celui de l'ancre de sa rangée est
# sur la MÊME LIGNE que l'ancre : c'est la valeur d'un « libellé ....... valeur », pas une annexe.
# Volontairement plus serré que TOLERANCE_LIGNE : l'annexe réelle de la page 1 (AVIS_IR_RG) est à
# 5,2 pt de son ancre, les valeurs de la page 3 sont à 0,0.
ECART_Y0_MEME_LIGNE = 2.0


# _dans_un_tableau extraite vers geometry.py (partagée avec qa.py) --
# réutilisée ici par son nouveau nom pour ne rien changer au reste du
# fichier.
_dans_un_tableau = dans_un_tableau


def _grouper_lignes_par_tolerance(mots, tolerance=TOLERANCE_LIGNE):
    """Group words into visual lines by y-coordinate tolerance without flattening the lines."""
    mots_tries = sorted(mots, key=lambda w: w.bbox.y0)
    lignes = []
    ligne_courante = []
    y_ref = None
    for w in mots_tries:
        y0 = w.bbox.y0
        if ligne_courante and abs(y0 - y_ref) <= tolerance:
            ligne_courante.append(w)
        else:
            if ligne_courante:
                lignes.append(ligne_courante)
            ligne_courante = [w]
            y_ref = y0
    if ligne_courante:
        lignes.append(ligne_courante)
    return lignes


def _grouper_par_ligne_tolerant(mots, tolerance=TOLERANCE_LIGNE):
    """Group words into lines using y tolerance, then sort each line from left to right."""
    lignes = _grouper_lignes_par_tolerance(mots, tolerance)
    resultat = []
    for ligne in lignes:
        resultat.extend(sorted(ligne, key=lambda w: w.bbox.x0))
    return resultat


def _ordonner_items_par_ligne(items, tolerance=TOLERANCE_LIGNE):
    """Merge blocks whose vertical positions differ slightly, then read each line from left to right."""
    items_tries = sorted(items, key=lambda item: item[0])
    lignes = []
    ligne_courante = []
    y_ref = None
    for item in items_tries:
        if ligne_courante and abs(item[0] - y_ref) <= tolerance:
            ligne_courante.append(item)
        else:
            if ligne_courante:
                lignes.append(ligne_courante)
            ligne_courante = [item]
            y_ref = item[0]
    if ligne_courante:
        lignes.append(ligne_courante)

    resultat = []
    for ligne in lignes:
        resultat.extend(sorted(ligne, key=lambda item: item[1]))
    return resultat


class Boite:
    """Represent a physical text region containing words from one native or vectorized line."""
    __slots__ = ("id", "x0", "y0", "x1", "y1", "mots", "origine")

    def __init__(self, id_, mots, origine):
        self.id = id_
        self.mots = mots
        self.origine = origine
        self.x0 = min(w.bbox.x0 for w in mots)
        self.y0 = min(w.bbox.y0 for w in mots)
        self.x1 = max(w.bbox.x1 for w in mots)
        self.y1 = max(w.bbox.y1 for w in mots)

    def __repr__(self):
        apercu = " ".join((w.text or "") for w in self.mots[:5])
        return (f"Boite#{self.id} [{self.origine}] y=({self.y0:.1f}-{self.y1:.1f}) "
                f"x=({self.x0:.1f}-{self.x1:.1f}) n={len(self.mots)} \"{apercu}...\"")


def _construire_boites_natives(mots_natifs, tolerance_ligne=TOLERANCE_LIGNE):
    """Create one region per physical line within each PyMuPDF text block."""
    compteur_repli = itertools.count()
    par_block = defaultdict(list)
    for w in mots_natifs:
        bloc = w.block if getattr(w, "block", None) is not None else f"_sans_block_{next(compteur_repli)}"
        par_block[bloc].append(w)
    boites = []
    for bid, mots in par_block.items():
        lignes = _grouper_lignes_par_tolerance(mots, tolerance_ligne)
        for i, ligne in enumerate(lignes):
            boites.append(Boite(f"N{bid}L{i}", ligne, "native"))
    return boites


class _UnionFind:
    """Implement disjoint-set operations for clustering nearby vectorized words."""
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _chevauche_dilate(a, b, marge):
    """Return whether two bounding boxes overlap after expanding them by a margin."""
    return not (a.bbox.x1 + marge < b.bbox.x0 or
                a.bbox.x0 - marge > b.bbox.x1 or
                a.bbox.y1 + marge < b.bbox.y0 or
                a.bbox.y0 - marge > b.bbox.y1)


def _construire_boites_vectorisees(mots_vecto, marge=DILATATION_CLUSTERING_VECTO,
                                    tolerance_ligne=TOLERANCE_LIGNE):
    """Cluster nearby vectorized words into OCR regions and split oversized regions into physical-line boxes."""
    n = len(mots_vecto)
    if n == 0:
        return []
    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if _chevauche_dilate(mots_vecto[i], mots_vecto[j], marge):
                uf.union(i, j)

    groupes = defaultdict(list)
    for i in range(n):
        groupes[uf.find(i)].append(mots_vecto[i])

    boites = []
    for i, (racine, mots) in enumerate(groupes.items()):
        lignes = _grouper_lignes_par_tolerance(mots, tolerance_ligne)
        for j, ligne in enumerate(lignes):
            boites.append(Boite(f"V{i}L{j}", ligne, "vectorized"))
    return boites


def diagnostiquer_absorption(rangees, seuil_ratio=3.0):
    """Warn when one region is much taller than its peers, indicating a risk that it absorbed an unrelated region."""
    alertes = []
    for i, rangee in enumerate(rangees):
        if len(rangee) < 2:
            continue
        hauteurs = [(b, b.y1 - b.y0) for b in rangee]
        h_max = max(h for _, h in hauteurs)
        h_min = min(h for _, h in hauteurs)
        if h_min > 0 and h_max / h_min >= seuil_ratio:
            grosse = next(b for b, h in hauteurs if h == h_max)
            petite = next(b for b, h in hauteurs if h == h_min)
            alertes.append((i, grosse, petite, h_max / h_min))
    return alertes


def _ordonner_par_boites(boites, seuil=SEUIL_CHEVAUCHEMENT_RANGEE):
    """Group regions into rows by vertical overlap, sort each row horizontally, and return both ordered regions and rows."""
    boites_triees = sorted(boites, key=lambda b: b.y0)
    rangees = []
    rangee_courante = []
    bande_y0 = bande_y1 = None

    def chevauchement_bande(boite):
        inter = min(bande_y1, boite.y1) - max(bande_y0, boite.y0)
        if inter <= 0:
            return 0.0
        plus_petite_hauteur = min(bande_y1 - bande_y0, boite.y1 - boite.y0)
        if plus_petite_hauteur <= 0:
            return 0.0
        return inter / plus_petite_hauteur

    for boite in boites_triees:
        if not rangee_courante:
            rangee_courante = [boite]
            bande_y0, bande_y1 = boite.y0, boite.y1
            continue
        if chevauchement_bande(boite) >= seuil:
            rangee_courante.append(boite)
            bande_y0 = max(bande_y0, boite.y0)
            bande_y1 = min(bande_y1, boite.y1)
        else:
            rangees.append(rangee_courante)
            rangee_courante = [boite]
            bande_y0, bande_y1 = boite.y0, boite.y1
    if rangee_courante:
        rangees.append(rangee_courante)

    resultat = []
    for rangee in rangees:
        resultat.extend(sorted(rangee, key=lambda b: b.x0))
    return resultat, rangees


def _deferer_satellites(rangees, ecart_x0=3.0, seuil_densite=0.5, min_pile=3):
    """Place small satellite regions after their main stack instead of interleaving them by vertical overlap alone."""
    if not rangees:
        return [], {}

    def ancre(r):
        return min(r, key=lambda b: b.x0)

    piles, cur = [], [0]
    for i in range(1, len(rangees)):
        a_prev, a = ancre(rangees[cur[-1]]), ancre(rangees[i])
        ecart = a.y0 - a_prev.y1
        hmin = min(a_prev.y1 - a_prev.y0, a.y1 - a.y0)
        if abs(a.x0 - a_prev.x0) <= ecart_x0 and ecart <= hmin:
            cur.append(i)
        else:
            piles.append(cur)
            cur = [i]
    piles.append(cur)

    resultat = [sorted(r, key=lambda b: b.x0) for r in rangees]
    reperes = {}  # id(boite satellite) -> y0 repère (celui de l'ancre de fin de pile)
    for pile in piles:
        if len(pile) < min_pile:
            continue
        avec_partenaire = [i for i in pile if len(rangees[i]) >= 2]
        if not avec_partenaire or len(avec_partenaire) / len(pile) >= seuil_densite:
            continue
        satellites = []
        for i in avec_partenaire:
            a = ancre(rangees[i])
            annexes = [b for b in rangees[i]
                       if b is not a and abs(b.y0 - a.y0) > ECART_Y0_MEME_LIGNE]
            satellites += annexes
            resultat[i] = [b for b in rangees[i] if b is a or all(b is not x for x in annexes)]
            resultat[i].sort(key=lambda b: b.x0)
        if not satellites:
            continue
        resultat[pile[-1]] = resultat[pile[-1]] + sorted(satellites, key=lambda b: (b.y0, b.x0))
        y0_fin = ancre(rangees[pile[-1]]).y0
        for b in satellites:
            reperes[id(b)] = y0_fin
    return resultat, reperes


def _ordonner_sous_ensemble(mots):
    """Apply region-and-row ordering to an already isolated subset of words."""
    natifs = [w for w in mots if not getattr(w, "is_vectorized", False)]
    vectos = [w for w in mots if getattr(w, "is_vectorized", False)]
    boites_natives = _construire_boites_natives(natifs)
    boites_vectorisees = _construire_boites_vectorisees(vectos)
    toutes_boites = boites_natives + boites_vectorisees
    _boites_plates, _rangees = _ordonner_par_boites(toutes_boites)
    _rangees_def, _reperes = _deferer_satellites(_rangees)
    boites_ordonnees = [b for rangee in _rangees_def for b in rangee]
    resultat = []
    for boite in boites_ordonnees:
        resultat.extend(_grouper_par_ligne_tolerant(boite.mots))
    return resultat


def _conteneurs_liens(page):
    """Identify small clickable regions that should be read as one boxed text block."""
    surface = max(1.0, page.width * page.height)
    conteneurs = []
    for lien in getattr(page, "links", []):
        b = lien.bbox
        if b is not None and (b.x1 - b.x0) * (b.y1 - b.y0) <= PART_PAGE_MAX_CONTENEUR_LIEN * surface:
            conteneurs.append({"bbox": b, "type": "lien"})
    return conteneurs


def _ordonner_lignes_simple(mots, tolerance=TOLERANCE_LIGNE):
    """Read a small text block from top to bottom and each line from left to right."""
    resultat = []
    for ligne in _grouper_lignes_par_tolerance(mots, tolerance):
        resultat.extend(sorted(ligne, key=lambda w: w.bbox.x0))
    return resultat


def _repartir_par_encadre(mots, encadres):
    """Assign non-table words to detected boxes according to their centers."""
    par_encadre = defaultdict(list)
    restants = list(mots)
    for idx, encadre in enumerate(encadres):
        bbox = encadre.get("bbox") if isinstance(encadre, dict) else None
        if bbox is None:
            continue
        captes, non_captes = [], []
        for w in restants:
            (captes if mot_dans_cellule(w, bbox) else non_captes).append(w)
        if captes:
            par_encadre[idx] = captes
        restants = non_captes
    return par_encadre, restants


def _ordonner_mots_table(mots_table, table):
    """Order table words by row and cell using stored cell bounding boxes."""
    if not getattr(table, "cell_bboxes", None):
        return sorted(mots_table, key=lambda w: (w.bbox.y0, w.bbox.x0))

    captes = set()
    resultat = []
    for ligne_bboxes in table.cell_bboxes:
        for cell_bbox in ligne_bboxes:
            if cell_bbox is None:
                continue
            mots_cellule = [
                m for m in mots_table
                if id(m) not in captes and mot_dans_cellule(m, cell_bbox)
            ]
            if mots_cellule:
                for ligne in _grouper_lignes_par_tolerance(mots_cellule):
                    resultat.extend(sorted(ligne, key=lambda w: w.bbox.x0))
                captes.update(id(m) for m in mots_cellule)

    non_captes = [m for m in mots_table if id(m) not in captes]
    non_captes.sort(key=lambda w: (w.bbox.y0, w.bbox.x0))
    resultat.extend(non_captes)
    return resultat


def ordonner(page, simple_sort=False) -> list:
    """Return copies of native page words in reading order, keeping table words out of geometric sorting and then restoring them."""
    tables = page.graphics.tables

    if simple_sort:
    # Tri géographique de base : haut → bas, gauche → droite
        return sorted(page.native.words, key=lambda w: (w.bbox.y0, w.bbox.x0))

    # 1. ENCADRÉS : les mots dans un encadré détecté (rectangle/quad coloré,
    #    cf. frontend/layout/detectors.py) sont retirés du bassin général et
    #    ordonnés À PART, récursivement, par le même algorithme
    #    (_ordonner_sous_ensemble).
    #
    #    PRIORITÉ ENCADRÉ > TABLE (déplacé avant l'exclusion table, qui
    #    était l'étape 1 dans une version précédente) : un mot à la fois
    #    dans un encadré ET dans une "table" détectée par pdfplumber doit
    #    être traité comme un mot d'encadré, jamais comme un mot de table.
    #    Confirmé empiriquement sur le document fiscal réel : la table
    #    détectée par pdfplumber à (223.6,307.0)-(535.9,583.9) est un FAUX
    #    POSITIF -- ses propres bordures d'encadré bleu ("Somme qui vous
    #    est remboursée" + le paragraphe qui suit) sont prises pour une
    #    grille de table par pdfplumber (cf. project notes : "Table
    #    detection is an unsolved problem"). Avant ce réordonnancement, ces
    #    mots étaient exclus du bassin encadré dès l'étape table (l'ancienne
    #    étape 1), geré par `_ordonner_mots_table` via une grille de
    #    cellules qui n'a pas de sens sur une fausse table, et se
    #    retrouvaient plaqués tout à la fin du document, après même le
    #    paragraphe pied de page.
    #
    #    CORRECTIF (première version cassée, cf. historique) : un encadré
    #    NE DOIT JAMAIS participer au tri par CHEVAUCHEMENT de rangées
    #    (_ordonner_par_boites) en tant que boîte unique. Sa hauteur totale
    #    (jusqu'à 190pt pour "Vos références") en fait exactement la
    #    "boîte nettement plus haute que ses voisines" que le RISQUE CONNU
    #    documenté plus haut dans ce fichier décrit déjà : elle n'a besoin
    #    de chevaucher que 30% de la hauteur d'une petite boîte pour
    #    l'absorber dans SA rangée. Confirmé empiriquement sur le document
    #    fiscal réel avec la version précédente de cette intégration :
    #    "DUPONT ..." (hors de tout encadré, mais verticalement
    #    contenu dans la plage y de l'encadré "Vos références") se
    #    retrouvait réinjecté AU MILIEU de ses lignes plutôt qu'après.
    #
    #    Un encadré est donc désormais un ITEM ATOMIQUE, jamais fusionné en
    #    rangée avec quoi que ce soit -- positionné dans la séquence finale
    #    par un simple TRI STABLE sur son propre y0 (cf. section 4), pas par
    #    ré-appariement de chevauchement.
    tous_mots = [deepcopy(w) for w in page.native.words if w.bbox]
    encadres = detecter_boites_encadres(page)
    nb_encadres_detectes = len(encadres)
    # Les liens passent APRÈS les encadrés détectés (un mot déjà pris par un encadré y reste) :
    # le texte d'un encadré-lien est vectorisé, ses mots sont lus ligne par ligne comme un bloc.
    encadres = encadres + _conteneurs_liens(page)
    mots_par_encadre, mots_restants = _repartir_par_encadre(tous_mots, encadres)

    # 2. Séparation, sur le RESTE seulement (hors encadré) : mots hors table
    #    (pour tri complexe) vs mots dans table (sauvegarde) -- même logique
    #    qu'avant, juste appliquée après la priorité encadré ci-dessus.
    mots_hors_encadre = [w for w in mots_restants if not _dans_un_tableau(w, tables)]
    mots_dans_table = [w for w in mots_restants if _dans_un_tableau(w, tables)]

    # 3. Reste de page (hors encadrés, hors tables) : algorithme
    #    boîtes/rangées INCHANGÉ, sans aucune connaissance des encadrés -- exactement le même calcul
    #    que si les encadrés n'existaient pas, sur ce sous-ensemble de mots.
    natifs = [w for w in mots_hors_encadre if not getattr(w, "is_vectorized", False)]
    vectos = [w for w in mots_hors_encadre if getattr(w, "is_vectorized", False)]

    boites_natives = _construire_boites_natives(natifs)
    boites_vectorisees = _construire_boites_vectorisees(vectos)
    _boites_plates, _rangees = _ordonner_par_boites(boites_natives + boites_vectorisees)
    _rangees_def, reperes_satellites = _deferer_satellites(_rangees)
    boites_ordonnees = [b for rangee in _rangees_def for b in rangee]

    # 4. FUSION FINALE : chaque boîte hors-encadré (déjà dans le bon ordre
    #    rangées/x0 entre elles) et chaque encadré (ordonné en interne par
    #    _ordonner_sous_ensemble) devient un ITEM (y0_repere, mots),
    #    positionné par un TRI STABLE sur y0 uniquement -- jamais par
    #    chevauchement. C'est ce qui reproduit le motif "zigzag" de l'ordre
    #    idéal (Vos références y0=167 -> DUPONT y0=181 -> Somme... y0=289
    #    -> Vos contacts y0=368 -> Revenu fiscal... y0=589) sans jamais
    #    réabsorber un encadré dans une rangée voisine : chaque encadré
    #    reste un bloc contigu dans le résultat, quel que soit ce qui le
    #    chevauche verticalement par ailleurs.
    items = []
    for rangee in _rangees_def:
        boites_principales = [
            boite for boite in rangee if id(boite) not in reperes_satellites
        ]
        if boites_principales:
            mots_rangee = [
                mot
                for boite in boites_principales
                for mot in _grouper_par_ligne_tolerant(boite.mots)
            ]
            mots_rangee.sort(key=lambda mot: mot.bbox.x0)
            items.append((
                min(boite.y0 for boite in boites_principales),
                min(boite.x0 for boite in boites_principales),
                mots_rangee,
            ))
        for boite in rangee:
            if id(boite) in reperes_satellites:
                items.append((
                    reperes_satellites[id(boite)],
                    boite.x0,
                    _grouper_par_ligne_tolerant(boite.mots),
                ))
    for idx_encadre, mots_encadre in mots_par_encadre.items():
        y0_repere = min(w.bbox.y0 for w in mots_encadre)
        x0_repere = min(w.bbox.x0 for w in mots_encadre)
        if idx_encadre >= nb_encadres_detectes:           # conteneur issu d'un lien
            ordonnes = _ordonner_lignes_simple(mots_encadre)
        else:
            ordonnes = _ordonner_sous_ensemble(mots_encadre)
        items.append((y0_repere, x0_repere, ordonnes))

    # 5. RÉINTÉGRATION : mots de table, ordonnés PAR TABLE via sa propre grille de
    #    cellules (cf. _ordonner_mots_table) plutôt qu'un tri plat unique
    #    sur l'ensemble des tables mélangées. Chaque table redevient un bloc
    #    de lecture ancré à sa position physique, au lieu d'être ajoutée après
    #    tout le texte hors tableau.
    #
    #    Un mot n'est assigné qu'à la PREMIÈRE table qui le capte (retiré
    #    du bassin avant de passer à la suivante) -- protège contre une
    #    duplication si deux tables détectées ont des bbox qui se
    #    chevauchent (cas non rencontré sur le document de test, mais pas
    #    à exclure sur un autre document).
    mots_tables_natifs = []
    if mots_dans_table:
        tables_triees = sorted(tables, key=lambda t: t.bbox.y0 if t.bbox else 0.0)
        bassin = list(mots_dans_table)
        for table in tables_triees:
            mots_de_cette_table = [w for w in bassin if _dans_un_tableau(w, [table])]
            if mots_de_cette_table:
                mots_ordonnes_table = _ordonner_mots_table(mots_de_cette_table, table)
                if any(getattr(w, "is_vectorized", False) for w in mots_de_cette_table):
                    items.append((
                        min(w.bbox.y0 for w in mots_ordonnes_table),
                        min(w.bbox.x0 for w in mots_ordonnes_table),
                        mots_ordonnes_table,
                    ))
                else:
                    # Conserver l'ordre historique des tableaux purement
                    # natifs; le déplacement à leur ancre physique corrige
                    # ici le cas page 2 où l'OCR vectoriel des en-têtes de
                    # tableau était ajouté après tout le reste de la page.
                    mots_tables_natifs.extend(mots_ordonnes_table)
                dejas_assignes = {id(w) for w in mots_de_cette_table}
                bassin = [w for w in bassin if id(w) not in dejas_assignes]

        if bassin:
            if any(getattr(w, "is_vectorized", False) for w in bassin):
                mots_restants_table = _grouper_par_ligne_tolerant(bassin)
                items.append((
                    min(w.bbox.y0 for w in bassin),
                    min(w.bbox.x0 for w in bassin),
                    mots_restants_table,
                ))
            else:
                mots_tables_natifs.extend(sorted(bassin, key=lambda w: (w.bbox.y0, w.bbox.x0)))

    resultat = []
    for _y0, _x0, mots in _ordonner_items_par_ligne(items):
        resultat.extend(mots)
    resultat.extend(mots_tables_natifs)

    return resultat
