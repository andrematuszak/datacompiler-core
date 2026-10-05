"""reading_order.py — Détermine l'ordre de lecture réel des mots natifs
d'une page, en construisant des BOÎTES (régions rectangulaires physiques),
en les regroupant en RANGÉES par chevauchement vertical, puis en triant
chaque rangée gauche -> droite.

Ne modifie ni texte ni bbox -- uniquement l'ORDRE. typography.py (césures)
et alignment.py (natif<->OCR) supposent tous les deux que cet ordre est déjà
correct quand ils s'exécutent.

Remplace l'ancien moteur par détection de colonnes globales
(SEUIL_GAP / _colonnes_depuis_fragments / pleine largeur), qui s'est révélé
structurellement incapable de gérer un layout "libellé aligné à gauche /
valeur alignée à droite sur la même ligne" (ex. "Détail des revenus" du
document fiscal : bloc PyMuPDF multi-lignes de libellés vs colonne de
montants une-ligne chacun -- les deux tombaient dans deux "colonnes"
distinctes, triées indépendamment, perdant l'appariement). Confirmé aussi
fragile sur un layout de lettre/formulaire (page 1 du même document,
plusieurs encarts à x0 différents mais pas de vraies colonnes de lecture
parallèle) : l'ancien moteur dépendait d'un seuil "pleine largeur" (90% de
la ligne la plus large observée) pour décider quand vider les tampons de
colonne -- un seuil qui basculait entre correct et cassé pour des écarts de
largeur de bbox de quelques points, preuve empirique à l'appui.

PRINCIPE (aucune notion de "colonne globale") :

1. Construire des BOÎTES :
   - natif : le champ `.block` de PyMuPDF donne un découpage gratuit, mais
     un bloc peut couvrir un paragraphe multi-lignes entier (ex. 90pt,
     7 lignes empilées) -- laissé en une seule boîte, il absorbe dans sa
     rangée plusieurs petites boîtes concurrentes en face (ex. une colonne
     de montants, une ligne par valeur), perdant l'info verticale pour les
     remettre dans le bon ordre. Confirmé empiriquement (bug N5/N21-N26 :
     "Salaires" vs "30050" etc.). (block, line) de PyMuPDF a été testé
     comme fix et écarté : line=0 uniforme même sur un bloc normal dès
     qu'il y a des pointillés de tabulation sur ce document. Fix retenu :
     redécoupage par tolérance géométrique sur y0
     (`_grouper_lignes_par_tolerance`), une boîte par LIGNE physique.
   - vectorisé (`.is_vectorized`) : pas de `.block` exploitable -> les mots
     sont clusterisés par proximité géométrique (union-find sur
     chevauchement de bbox dilatée), puis chaque cluster est lui aussi
     redécoupé en lignes par la même tolérance géométrique (même bug que
     N5, côté vectorisé : cas V12, "Numéro FIP / Numéro rôle / Date
     d'établissement / Date mise en recouvrement" fusionnés à tort en une
     seule boîte de 40pt par le clustering).
   - Repli défensif : un mot natif sans `.block` (cas non rencontré sur le
     document de test, mais pas garanti sur un autre) devient sa propre
     boîte à un seul mot plutôt que d'être silencieusement perdu.

2. Regrouper les boîtes en RANGÉES par chevauchement vertical significatif
   (tri par y0, extension de plage tant que le chevauchement dépasse
   SEUIL_CHEVAUCHEMENT_RANGEE). Une rangée à 1 boîte = comportement page
   normale ; une rangée à N boîtes = les N boîtes sont lues côte à côte,
   peu importe qu'elles fassent partie d'un "vrai" système de colonnes de
   texte ou soient juste deux encarts positionnés l'un à côté de l'autre.

3. Trier chaque rangée par x0 croissant (gauche -> droite), concaténer les
   rangées dans l'ordre (haut -> bas).

RISQUE CONNU, NON ÉLIMINÉ : une boîte nettement plus haute que ses voisines
de rangée n'a besoin de chevaucher que SEUIL_CHEVAUCHEMENT_RANGEE (30%) de
la hauteur d'une petite boîte pour l'absorber dans sa rangée -- et
transitivement, tout ce qui touche cette petite boîte aussi, même sans
jamais toucher la grosse boîte directement. `diagnostiquer_absorption` sert
à repérer ce risque a posteriori (rangées où le ratio hauteur max/min
dépasse 3x) ; ce n'est PAS branché automatiquement dans `ordonner()` (qui
reste une fonction pure, sans log) -- à appeler explicitement depuis les
tests ou le pipeline si besoin d'une alerte QA.

LIMITE CONNUE, NON RETESTÉE dans cette version : le papier IEEE deux
colonnes qui avait motivé l'ancien moteur colonnes n'a pas été revérifié
avec cette nouvelle approche -- risque de régression non écarté (choix
explicite : "on reste sur mon premier test, on bosse test par test").

L'exclusion des mots de table (`_dans_un_tableau`/`graphics.tables`) est
CONSERVÉE en amont, inchangée par rapport à l'ancienne version -- décision
d'architecture volontaire, un changement à la fois. Les mots de table ne
passent PAS par le moteur boîtes/rangées général.

INTÉGRATION CHIRURGICALE (ajoutée après la mise en place de
compile/layout_tree.py) : les mots de table ne sont plus réintégrés par un
tri plat (y0, x0) unique -- ce tri mélangeait en-têtes et lignes de valeurs
dès qu'ils se chevauchaient verticalement (confirmé : "situation du foyer"
et "C T" du document fiscal, deux lignes visuellement distinctes mais
suffisamment proches en y pour un tri plat les entrelacer). Chaque table
est maintenant ordonnée via SA PROPRE grille (`TableElement.cell_bboxes`,
déjà calculée à l'extraction par extract/pdfplumber.py) : ligne par ligne,
cellule par cellule gauche->droite au sein de chaque ligne -- même principe
que `construire_boite_tableau` (layout_tree.py), mais appliqué directement
à des objets Word plutôt qu'à des ids, PARCE QUE cette fonction tourne
AVANT la renumérotation finale de compiler.py (mots encore à id=-1 pour
les vectorisés à ce stade, cf. docstring de construire_boite_tableau pour
le détail) -- utiliser des ids ici serait prématuré, pas une erreur en soi,
mais une dépendance sur une garantie qui n'existe pas encore à ce point du
pipeline. Un mot dans une table mais dans AUCUNE cellule (bord, cellule
fusionnée sans bbox) reste capté par le même filet de sécurité qu'avant :
tri plat (y0, x0), en fin de liste -- jamais perdu.

LIMITE CONNUE, NON RÉSOLUE par cette intégration : un mot peut être proche
d'une table sans que `_dans_un_tableau` le capte -- si la bbox de la table
détectée par pdfplumber ne s'étend pas jusqu'à cette "ligne invisible" (ex.
confirmé : "C"/"T" du document fiscal, juste sous la bbox du tableau
d'en-têtes, jamais inclus dans mots_dans_table). Ce cas-là reste traité par
le moteur boîtes/rangées général, pas par cette intégration -- un problème
de géométrie de détection en amont (extract/pdfplumber.py), pas d'ordre.

INTÉGRATION CHIRURGICALE #2 (encadrés colorés, cf.
frontend/layout/detectors.py::detecter_boites_encadres) : même principe que
l'intégration table ci-dessus, appliquée aux rectangles/quads détectés par
couleur (ex. les encadrés bleus "Vos références"/"Vos contacts" du document
fiscal). Un mot dont le centre tombe dans un encadré est retiré du bassin
général et ordonné À PART, récursivement, par le même algorithme
boîtes/rangées (`_ordonner_sous_ensemble`).

Chaque encadré est ensuite réinséré dans la séquence finale comme un ITEM
ATOMIQUE, positionné par un simple TRI STABLE sur son propre y0 -- PAS par
le mécanisme de chevauchement de `_ordonner_par_boites`. Version précédente
cassée, gardée en mémoire ici : y faire participer l'encadré comme UNE
Boite unique (bbox = toute sa hauteur, ex. 190pt pour "Vos références")
recréait exactement le RISQUE CONNU documenté plus haut ("boîte nettement
plus haute que ses voisines absorbe tout ce qui la chevauche à 30%") --
confirmé empiriquement : "DUPONT ..." (hors de tout encadré, mais
verticalement contenu dans sa plage y) se retrouvait réinjecté AU MILIEU de
ses lignes plutôt qu'après.

LIMITE CONNUE, NON RÉSOLUE par cette intégration : un mot logiquement
rattaché à un encadré mais physiquement situé en dehors de sa bbox (ex.
confirmé sur le document fiscal : le libellé destinataire "DUPONT
..." lui-même, qui précède "Vos références" dans l'ordre idéal sans
être dans AUCUN encadré) n'est pas résolu par cette intégration -- il reste
positionné par le moteur boîtes/rangées général, à sa position géométrique
naturelle. Reste un problème ouvert pour une itération suivante si le
résultat empirique le confirme.
"""

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
    """Regroupe des mots en lignes (liste de LISTES, pas encore aplatie)
    par tolérance sur y0 -- coeur commun réutilisé à deux endroits :
    1. `_grouper_par_ligne_tolerant` : tri final à l'intérieur d'une boîte.
    2. `_construire_boites_natives`/`_construire_boites_vectorisees` :
       découpage d'un bloc/cluster en boîtes une-ligne AVANT le
       regroupement en rangées, pas seulement au moment du tri final --
       voir docstring de module pour le bug concret (N5/V12) que ça
       corrige."""
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
    """Regroupe des mots en lignes par tolérance sur y0 (pas un tri brut),
    puis trie chaque ligne par x0. Évite qu'un micro-écart de y0 (ex. 19.7
    vs 21.4, deux mots de la MÊME ligne visuelle) ne fasse passer un mot de
    droite avant un mot de gauche."""
    lignes = _grouper_lignes_par_tolerance(mots, tolerance)
    resultat = []
    for ligne in lignes:
        resultat.extend(sorted(ligne, key=lambda w: w.bbox.x0))
    return resultat


def _ordonner_items_par_ligne(items, tolerance=TOLERANCE_LIGNE):
    """Fusionne dans une même ligne les blocs dont le y0 diffère légèrement,
    puis les lit de gauche à droite. Le tri final par y0 seul séparait parfois
    les fragments natifs et vectorisés d'une même ligne."""
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
    """Région rectangulaire regroupant un ou plusieurs mots déjà reconnus
    comme faisant partie de la même ligne physique (native ou vectorisée).
    Volontairement publique : `diagnostiquer_absorption` et les tests
    manipulent directement des `Boite`."""
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
    """Une boîte par LIGNE physique à l'intérieur de chaque bloc PyMuPDF,
    pas une boîte par bloc entier (cf. docstring de module, bug N5). Un mot
    sans `.block` (repli défensif, jamais rencontré sur le document de
    test mais pas garanti ailleurs) devient sa propre boîte isolée plutôt
    que d'être perdu."""
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
    """Structure union-find pour le clustering des mots vectorisés."""
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
    """Vérifie si deux bbox se chevauchent après dilatation de `marge` points."""
    return not (a.bbox.x1 + marge < b.bbox.x0 or
                a.bbox.x0 - marge > b.bbox.x1 or
                a.bbox.y1 + marge < b.bbox.y0 or
                a.bbox.y0 - marge > b.bbox.y1)


def _construire_boites_vectorisees(mots_vecto, marge=DILATATION_CLUSTERING_VECTO,
                                    tolerance_ligne=TOLERANCE_LIGNE):
    """Le clustering union-find regroupe des mots proches en une même ZONE
    OCR -- légitime en soi, mais si on laisse la zone entière comme UNE
    boîte, elle subit le même problème que N5 côté natif (cas V12, cf.
    docstring de module). Donc : cluster par proximité pour DÉCIDER quels
    mots appartiennent à la même zone, puis redécoupe cette zone en lignes
    (même logique que côté natif) avant de créer les boîtes finales."""
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
    """Alerte sur les rangées où une boîte est nettement plus haute que les
    autres membres -- signature du risque qu'une grosse boîte absorbe à
    tort une petite boîte sans rapport dans sa rangée (cf. RISQUE CONNU,
    docstring de module). PAS appelée automatiquement par `ordonner()` --
    fonction pure, sans log ; à appeler explicitement depuis les tests ou
    le pipeline (QA) si une alerte est souhaitée."""
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
    """Regroupe les boîtes en rangées (chevauchement vertical >= seuil),
    trie chaque rangée par x0, concatène. Retourne (boîtes dans l'ordre,
    rangées avant aplatissement) -- le second élément sert uniquement au
    diagnostic (`diagnostiquer_absorption`).

    Une nouvelle boîte est comparée à la BANDE COMMUNE de la rangée
    (intersection courante des bornes y de tous les membres déjà admis),
    PAS à un membre individuel pris isolément. La bande ne peut que
    RÉTRÉCIR à chaque ajout, jamais s'élargir -- ça borne la dérive à
    l'ancre initiale de la rangée. Sans ça (comparaison à "n'importe quel
    membre déjà présent"), une rangée peut dériver transitivement loin de
    son ancre : A chevauche B, B chevauche C, mais A et C ne se chevauchent
    jamais -- A, B et C finiraient quand même dans la même rangée, triés
    par x0 sans rapport avec leur position verticale réelle. Confirmé
    empiriquement (deux champs sans rapport, colonnes horizontalement
    éloignées, finissaient dans la même rangée avec la version "any")."""
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
    """Lit les boîtes SATELLITES d'une pile APRÈS la pile, au lieu de les
    intercaler dans la rangée où elles tombent par simple chevauchement
    vertical.

    Cas réel (test-impots-revenu.pdf, 27/09/2026) : "AVIS_IR_RG" (petit
    repère à droite, y=33-39) chevauche verticalement la ligne "Impôt sur
    les revenus de 2020" (y=27.9-47.2) -> même rangée -> lu juste après
    elle, AVANT "Avis d'impôt établi en 2021", qui fait pourtant partie du
    même titre (trois lignes alignées à gauche, x0 = 128.3 / 128.0 /
    127.6).

    Définitions :
      - ancre d'une rangée = sa boîte la plus à gauche ;
      - pile = ancres consécutives alignées à gauche (x0 à `ecart_x0` près)
        et verticalement jointives (écart <= hauteur de la plus petite) ;
      - satellites = boîtes non-ancres des rangées d'une pile.
    Si peu de rangées de la pile ont un partenaire (proportion <
    `seuil_densite`), les partenaires ne sont pas des "valeurs" appariées
    ligne à ligne mais des annexes : elles passent après la pile.

    Ne touche pas au cas "libellé / valeur" (chaque libellé de la pile a
    sa valeur : proportion 1.0 -> intact). Vérifié sur la page 1 du
    document de test : seule AVIS_IR_RG change de place (2 boîtes déplacées
    sur 41 rangées). NON vérifié sur d'autres documents ; approximation
    (bbox d'encre des tracés, pas les bbox Paddle) pour la validation.
    EXCEPTION -- valeurs sur la même ligne que leur libellé (page 3 de l'avis
    d'impôt : « Plafond total de 2019 ..... 15810 », « Revenu fiscal de
    référence ..... 28548 »...). Ces partenaires sont alignés sur l'ancre
    (|y0 - y0 de l'ancre| <= ECART_Y0_MEME_LIGNE) : ce sont des valeurs
    lues avec leur libellé, pas des annexes. La décision de différer reste
    celle de la densité (inchangée), mais seuls les satellites NON alignés
    sont déplacés ; sans cette exception, toute une colonne de montants
    partait à la fin de la pile, loin de ses libellés.

    Retourne (rangées triées par x0, {id(satellite): y0 repère}) : le
    repère sert au tri final par y0 de `ordonner()`, qui sinon remettrait
    le satellite avant la fin de la pile."""
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
    """Applique l'algorithme boîtes/rangées (natif/vectorisé -> boîtes par
    ligne -> rangées par chevauchement -> tri x0) à un sous-ensemble de mots
    DÉJÀ ISOLÉ -- extraction pure du corps historique de `ordonner()`, sans
    changement de comportement. Réutilisée deux fois : sur le "reste de
    page" (hors encadrés) et, récursivement, sur le contenu de CHAQUE
    encadré détecté (cf. `ordonner()`, section ENCADRÉS)."""
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
    """Zones cliquables assez petites pour être lues comme UN bloc de texte (encadré-lien)."""
    surface = max(1.0, page.width * page.height)
    conteneurs = []
    for lien in getattr(page, "links", []):
        b = lien.bbox
        if b is not None and (b.x1 - b.x0) * (b.y1 - b.y0) <= PART_PAGE_MAX_CONTENEUR_LIEN * surface:
            conteneurs.append({"bbox": b, "type": "lien"})
    return conteneurs


def _ordonner_lignes_simple(mots, tolerance=TOLERANCE_LIGNE):
    """Ordre de lecture d'un petit bloc de texte : lignes de haut en bas, mots de gauche à droite.
    Pour un texte justifié, les grands écarts entre mots ne doivent PAS le couper en colonnes."""
    resultat = []
    for ligne in _grouper_lignes_par_tolerance(mots, tolerance):
        resultat.extend(sorted(ligne, key=lambda w: w.bbox.x0))
    return resultat


def _repartir_par_encadre(mots, encadres):
    """Partitionne `mots` (déjà hors table) entre les encadrés détectés
    (centre du mot dans la bbox de l'encadré -- même convention que
    `mot_dans_cellule`/`dans_un_tableau`, réutilisée telle quelle) et le
    reste de la page. Retourne (dict index_encadre -> [mots],
    [mots hors de tout encadré]).

    Un mot n'est jamais compté dans deux encadrés : le premier encadré qui
    le capte (dans l'ordre de la liste `encadres`) l'emporte -- même
    principe défensif que l'assignation table-par-table plus bas dans ce
    fichier, au cas où deux zones détectées se chevaucheraient."""
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
    """Ordonne les mots d'UNE table selon sa grille `cell_bboxes` (ligne
    par ligne, cellule par cellule gauche->droite) -- remplace le tri plat
    (y0, x0) qui mélangeait en-têtes et lignes de valeurs proches
    verticalement (cf. docstring de module, section "INTÉGRATION
    CHIRURGICALE").

    Au sein d'une cellule : regroupement en lignes par TOLÉRANCE
    (_grouper_lignes_par_tolerance, même fonction que pour les boîtes
    natives/vectorisées du moteur général) avant de trier chaque ligne par
    x0 -- PAS un tri plat (y0, x0) direct. Erreur commise puis corrigée
    dans cette même fonction : sur les vraies coordonnées de la page 2,
    "foyer" (y0=94.6) triait avant "situation"/"du" (y0=94.8) à cause d'un
    écart de 0.2pt -- exactement le mécanisme du bug "Feuillet 1 2" déjà
    corrigé ailleurs (cf. Cas 5, test_reading_order_regression.py) et
    réintroduit ici par inattention avant d'être repéré sur données
    réelles.

    Mots hors de toute cellule connue (bord, cellule fusionnée) : ajoutés
    à la fin, triés (y0, x0) -- même filet de sécurité que le reste du
    fichier, jamais de perte silencieuse.

    Si `table.cell_bboxes` est vide (géométrie non disponible, ex. ancien
    document.json généré avant ce champ) : comportement identique à
    avant, tri plat pur -- pas de régression sur des données plus
    anciennes."""
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
    """Retourne des COPIES des mots natifs de `page`, dans l'ordre de
    lecture réel : tableaux exclus du tri par boîtes/rangées, mais
    réintégrés à la fin pour ne jamais perdre de contenu.
    """
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
