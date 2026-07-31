"""reading_order.py — Détermine l'ordre de lecture réel des mots natifs
d'une page : exclut ceux qui appartiennent à un tableau (déjà représentés
via graphics.tables / resolved.tables -- les inclure aussi comme mots isolés
les dupliquerait), détecte les colonnes, puis trie colonne par colonne,
ligne par ligne au sein de chaque colonne.

Ne modifie ni texte ni bbox -- uniquement l'ORDRE. typography.py (césures)
et alignment.py (natif<->OCR) supposent tous les deux que cet ordre est déjà
correct quand ils s'exécutent.

Deux corrections apportées après un test sur un vrai papier IEEE deux
colonnes, qui cassait complètement avec la version précédente :

1. SEUIL ADAPTATIF plutôt que fixe : l'ancien SEUIL_GAP=15.0 échouait sur
   ce papier, dont la vraie gouttière ne fait que ~11pt -- plus petit que
   le seuil fixe, donc jamais détecté comme séparation de colonnes. Le
   seuil est maintenant dérivé de l'écart médian entre mots CE document
   précis (un vrai gouttière de colonne se détache nettement de
   l'espacement normal, quel que soit le document).

2. LIGNES PLEINE LARGEUR exclues de la détection de colonnes : un titre ou
   un résumé qui chevauche toute la largeur de la page comble l'écart entre
   colonnes pour TOUTE la page si on les laisse participer à la détection
   (confirmé sur le papier IEEE : un seul bloc pleine largeur en haut de
   page faisait fusionner les deux colonnes en une seule bande sur la page
   entière). Ces lignes sont maintenant mises de côté pour la détection,
   puis réinsérées à la bonne position dans l'ordre final -- ce qui
   nécessite de "vider" les colonnes en cours de lecture avant d'émettre un
   bloc pleine largeur (sinon il s'intercalerait au milieu d'une colonne).

LIMITE CONNUE, TOUJOURS VRAIE : ceci reste une heuristique de projection
horizontale, pas un vrai analyseur de mise en page. Un layout plus complexe
que "colonnes verticales strictes + blocs pleine largeur" (encadrés
flottants, texte qui serpente autour d'une image, 3+ colonnes irrégulières)
n'est pas géré -- à revoir avec des cas réels plutôt que sur-ingénierer.
"""

from copy import deepcopy


def _dans_un_tableau(mot, tables):
    if not mot.bbox:
        return False
    cx = (mot.bbox.x0 + mot.bbox.x1) / 2
    cy = (mot.bbox.y0 + mot.bbox.y1) / 2
    for table in tables:
        if not table.bbox:
            continue
        if table.bbox.x0 <= cx <= table.bbox.x1 and table.bbox.y0 <= cy <= table.bbox.y1:
            return True
    return False


def _grouper_lignes_brutes(mots, tolerance_y=3.0):
    """Regroupement en lignes par simple proximité verticale -- ne suppose
    RIEN sur les colonnes (contrairement à output/layout.py, qui suppose
    l'ordre déjà résolu). Sert uniquement à décider, ligne par ligne, si
    elle est pleine largeur ou non."""
    mots_tries = sorted([w for w in mots if w.bbox], key=lambda w: (w.bbox.y0, w.bbox.x0))
    lignes = []
    ligne_courante = []
    y_courant = None
    for mot in mots_tries:
        y = mot.bbox.y0
        if y_courant is None or abs(y - y_courant) <= tolerance_y:
            ligne_courante.append(mot)
            y_courant = y if y_courant is None else y_courant
        else:
            lignes.append(ligne_courante)
            ligne_courante = [mot]
            y_courant = y
    if ligne_courante:
        lignes.append(ligne_courante)
    return lignes


def _seuil_bimodal(ecarts, plancher=2.0, frequence_min=3, facteur_relatif=1.5):
    """Cherche la frontière entre 'espacement normal entre mots' et 'vraie
    séparation de colonne' dans la distribution des écarts.

    Deux contraintes, ajoutées après deux échecs successifs sur le papier
    IEEE :
    1. La valeur en dessous de la frontière doit SE RÉPÉTER (au moins
       `frequence_min` fois) -- un vrai gouttière de colonne revient des
       dizaines de fois, un écart isolé (indentation de paragraphe, note de
       bas de page...) ne doit pas pouvoir définir la frontière.
    2. On s'arrête au PREMIER saut relatif suffisant en balayant du plus
       petit écart vers le plus grand (`facteur_relatif`, défaut +50%),
       plutôt que de chercher le plus grand saut absolu sur toute la
       distribution -- sinon un saut plus loin dans la traîne (ex. entre
       deux valeurs rares mais numériquement très espacées) l'emporte à
       tort sur le vrai saut, plus modeste en valeur absolue mais qui
       sépare réellement les deux populations recherchées."""
    valeurs = sorted(e for e in ecarts if e > 0)
    if len(valeurs) < 2:
        return plancher

    from collections import Counter
    compte = Counter(round(v, 1) for v in valeurs)

    for i in range(len(valeurs) - 1):
        if valeurs[i] < plancher:
            continue
        if compte[round(valeurs[i], 1)] < frequence_min:
            continue
        if valeurs[i + 1] >= valeurs[i] * facteur_relatif:
            return (valeurs[i] + valeurs[i + 1]) / 2

    return plancher


def _ecart_mot_normal(lignes):
    """Rassemble tous les écarts horizontaux intra-ligne de la page et en
    déduit un seuil de scission par détection bimodale (cf. _seuil_bimodal)
    -- agrégé sur toute la page plutôt que ligne par ligne, où l'échantillon
    serait trop petit pour distinguer fiablement les deux populations."""
    ecarts = []
    for ligne in lignes:
        mots_tries = sorted(ligne, key=lambda w: w.bbox.x0)
        for i in range(len(mots_tries) - 1):
            ecarts.append(mots_tries[i + 1].bbox.x0 - mots_tries[i].bbox.x1)
    return _seuil_bimodal(ecarts)


def _scinder_ligne(ligne, seuil):
    """Scinde une 'ligne' (mots proches en y) en fragments séparés par un
    écart horizontal significatif. Nécessaire car deux lignes de COLONNES
    DIFFÉRENTES tombent souvent dans la même bande de y par coïncidence
    (hauteurs de ligne similaires des deux côtés) et se retrouvent
    fusionnées par _grouper_lignes_brutes -- sans cette scission,
    _est_pleine_largeur mesurerait la largeur totale de ce faux-positif
    (colonne gauche + trou + colonne droite) et le confondrait avec une
    vraie ligne pleine largeur continue."""
    mots_tries = sorted(ligne, key=lambda w: w.bbox.x0)
    fragments = [[mots_tries[0]]]
    for i in range(1, len(mots_tries)):
        if mots_tries[i].bbox.x0 - mots_tries[i - 1].bbox.x1 > seuil:
            fragments.append([])
        fragments[-1].append(mots_tries[i])
    return fragments


def _est_pleine_largeur(ligne, largeur_max_observee, tolerance=0.9):
    """True si l'étendue horizontale de ce FRAGMENT (déjà scindé par
    _scinder_ligne) est proche de la largeur de ligne la plus large
    observée sur la page -- proxy adaptatif de "pleine largeur" plutôt
    qu'une marge fixe, qui suppose à tort une mise en page standard."""
    x0 = min(w.bbox.x0 for w in ligne)
    x1 = max(w.bbox.x1 for w in ligne)
    return (x1 - x0) >= largeur_max_observee * tolerance


def _colonnes_depuis_fragments(lignes, marge_min=2.0):
    """Regroupe les fragments de ligne (déjà scindés par _scinder_ligne) en
    positions de colonnes, à partir de leur x0 de départ -- plus direct que
    fusionner des intervalles de mots individuels sur toute la page,
    puisque chaque fragment est déjà un morceau de ligne cohérent à ce
    stade (une colonne entière, pas un mélange). Retourne une liste de x0
    croissants, un par colonne détectée."""
    if not lignes:
        return [0.0]
    debuts = sorted(set(round(min(w.bbox.x0 for w in l), 1) for l in lignes))
    if len(debuts) == 1:
        return debuts

    ecarts = [debuts[i + 1] - debuts[i] for i in range(len(debuts) - 1)]
    # Peu de valeurs distinctes ici (une poignée de colonnes, pas des
    # centaines de mots) : la contrainte de fréquence de _seuil_bimodal
    # n'a plus de sens (chaque position n'apparaît qu'une fois dans cette
    # liste dédupliquée), on la désactive pour ce cas d'usage.
    seuil = _seuil_bimodal(ecarts, plancher=marge_min, frequence_min=1)

    frontieres = [debuts[0]]
    for i in range(len(debuts) - 1):
        if debuts[i + 1] - debuts[i] > seuil:
            frontieres.append(debuts[i + 1])
    return frontieres


def _colonne_de_fragment(fragment, frontieres):
    """Un fragment est déjà entièrement dans UNE colonne (c'est le sens de
    _scinder_ligne) -- on lui trouve la frontière de colonne la plus proche
    par valeur inférieure, pas un vote mot par mot."""
    x0 = min(w.bbox.x0 for w in fragment)
    meilleur = 0
    for i, f in enumerate(frontieres):
        if f <= x0 + 1:
            meilleur = i
    return meilleur


def ordonner(page) -> list:
    """Retourne des COPIES des mots natifs de `page`, dans l'ordre de
    lecture réel : tableaux exclus, blocs pleine largeur préservés à leur
    position naturelle, colonnes traitées de gauche à droite entre deux
    blocs pleine largeur.

    Copie (deepcopy) faite ici, au tout premier maillon du pipeline resolve/
    -- l'immutabilité de native (contrat documenté dans document.py) est
    garantie à la source plutôt que rappelée à chaque étape suivante."""
    tables = page.graphics.tables
    mots = [
        deepcopy(w)
        for w in page.native.words
        if w.bbox and not _dans_un_tableau(w, tables)
    ]

    lignes_brutes = _grouper_lignes_brutes(mots)
    seuil_scission = _ecart_mot_normal(lignes_brutes)

    lignes = []
    for l in lignes_brutes:
        lignes.extend(_scinder_ligne(l, seuil_scission))

    largeur_max_observee = max(
        (max(w.bbox.x1 for w in l) - min(w.bbox.x0 for w in l) for l in lignes),
        default=page.width,
    )

    lignes_etroites = [l for l in lignes if not _est_pleine_largeur(l, largeur_max_observee)]

    frontieres = _colonnes_depuis_fragments(lignes_etroites) if lignes_etroites else [0.0]

    resultat = []
    tampons = {i: [] for i in range(len(frontieres))}

    def vider_tampons():
        for i in range(len(frontieres)):
            resultat.extend(sorted(tampons[i], key=lambda w: (round(w.bbox.y0 / 3), w.bbox.x0)))
            tampons[i] = []

    for ligne in lignes:  # dans l'ordre y d'origine (fragments d'une même bande y restent adjacents)
        if _est_pleine_largeur(ligne, largeur_max_observee):
            # Termine la lecture des colonnes accumulées AVANT ce bloc --
            # sinon il s'intercalerait au milieu d'une colonne en cours.
            vider_tampons()
            resultat.extend(sorted(ligne, key=lambda w: w.bbox.x0))
        else:
            idx = _colonne_de_fragment(ligne, frontieres)
            tampons[idx].extend(ligne)

    vider_tampons()
    return resultat
