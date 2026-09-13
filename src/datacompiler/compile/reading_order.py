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
"""

import itertools
from copy import deepcopy
from collections import defaultdict

from datacompiler.utils.heuristics_geometry import dans_un_tableau, mot_dans_cellule


SEUIL_CHEVAUCHEMENT_RANGEE = 0.3   # fraction de la + petite hauteur, pour dire "même rangée"
DILATATION_CLUSTERING_VECTO = 8.0  # pt, marge de tolérance pour fusionner des mots vectorisés proches
TOLERANCE_LIGNE = 3.5              # pt, écart de y0 toléré pour dire "même ligne" (bruit OCR)


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

    # 1. Séparation : mots hors table (pour tri complexe) vs mots dans table
    #    (sauvegarde) -- inchangé par rapport à l'ancienne version.
    mots_hors_table = [
        deepcopy(w)
        for w in page.native.words
        if w.bbox and not _dans_un_tableau(w, tables)
    ]
    mots_dans_table = [
        deepcopy(w)
        for w in page.native.words
        if w.bbox and _dans_un_tableau(w, tables)
    ]

    # 2. Séparation natif / vectorisé, construction des boîtes, ordre par
    #    rangées -- remplace l'ancien tri par colonnes globales.
    natifs = [w for w in mots_hors_table if not getattr(w, "is_vectorized", False)]
    vectos = [w for w in mots_hors_table if getattr(w, "is_vectorized", False)]

    boites_natives = _construire_boites_natives(natifs)
    boites_vectorisees = _construire_boites_vectorisees(vectos)
    toutes_boites = boites_natives + boites_vectorisees

    boites_ordonnees, _rangees = _ordonner_par_boites(toutes_boites)

    resultat = []
    for boite in boites_ordonnees:
        resultat.extend(_grouper_par_ligne_tolerant(boite.mots))

    # 3. RÉINTÉGRATION : mots de table, ordonnés PAR TABLE via sa grille de
    #    cellules (cf. _ordonner_mots_table) plutôt qu'un tri plat unique
    #    sur l'ensemble des tables mélangées. Tables elles-mêmes triées par
    #    y0 -- l'ordre de page.graphics.tables n'est pas garanti être déjà
    #    l'ordre de lecture (dépend de pdfplumber.find_tables()).
    #
    #    Un mot n'est assigné qu'à la PREMIÈRE table qui le capte (retiré
    #    du bassin avant de passer à la suivante) -- protège contre une
    #    duplication si deux tables détectées ont des bbox qui se
    #    chevauchent (cas non rencontré sur le document de test, mais pas
    #    à exclure sur un autre document).
    if mots_dans_table:
        tables_triees = sorted(tables, key=lambda t: t.bbox.y0 if t.bbox else 0.0)
        bassin = list(mots_dans_table)
        for table in tables_triees:
            mots_de_cette_table = [w for w in bassin if _dans_un_tableau(w, [table])]
            if mots_de_cette_table:
                resultat.extend(_ordonner_mots_table(mots_de_cette_table, table))
                dejas_assignes = {id(w) for w in mots_de_cette_table}
                bassin = [w for w in bassin if id(w) not in dejas_assignes]

    return resultat