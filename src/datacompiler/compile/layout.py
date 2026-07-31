"""layout.py — Regroupement en lignes visuelles, calculé UNE FOIS pendant
la compilation plutôt que recalculé par chaque renderer de backend/.


Différence avec l'ancienne version (dans backend/layout.py) : celle-ci
NE RETOURNE PLUS une liste de listes -- elle ANNOTE en place chaque Word
avec son numéro de ligne (`layout_line`), sur la séquence déjà ordonnée par
reading_order.py. Les renderers n'ont alors qu'à grouper par cet attribut
(groupby), sans recalculer une comparaison de bbox par format de sortie.


Prérequis inchangé : les mots doivent déjà être EN ORDRE DE LECTURE (sortie
de reading_order.py) -- ce module ne trie jamais, il détecte seulement les
sauts de ligne au fil de la séquence déjà établie.
"""




def assigner_lignes(mots, tolerance_y=3) -> list:
    """Annote chaque mot avec `layout_line` (entier, 0-indexé) et retourne
    la même liste (mutation en place, cohérent avec le reste de compile/ qui
    mute les copies déjà faites par reading_order.ordonner).


    Les mots sans bbox (insertions OCR sans position -- cf.
    conflict_resolution.py, cas "ocr_seul") ne peuvent pas déclencher de
    saut de ligne : ils héritent du numéro de ligne courant, à l'endroit où
    ils apparaissent dans la séquence -- même pis-aller documenté que
    l'ancienne version dans backend/layout.py."""
    ligne_courante = 0
    dernier_y = None


    for mot in mots:
        if mot.bbox is None:
            mot.layout_line = ligne_courante
            continue


        y = mot.bbox.y0
        if dernier_y is not None and abs(y - dernier_y) > tolerance_y:
            ligne_courante += 1
        mot.layout_line = ligne_courante
        dernier_y = y


    return mots




def grouper_par_ligne(mots) -> list:
    """Reconstitue des groupes de mots à partir de `layout_line` déjà
    assigné -- utile côté backend/ pour retrouver l'ancienne interface
    (liste de listes) sans redupliquer la logique de détection de saut."""
    groupes = {}
    ordre = []
    for mot in mots:
        cle = mot.layout_line
        if cle not in groupes:
            groupes[cle] = []
            ordre.append(cle)
        groupes[cle].append(mot)
    return [groupes[cle] for cle in ordre]