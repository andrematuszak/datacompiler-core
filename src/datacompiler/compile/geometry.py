"""geometry.py — Utilitaires géométriques partagés entre reading_order.py,
qa.py et layout_tree.py (et potentiellement d'autres modules de compile/ à
l'avenir).

Extrait de reading_order.py (où `_dans_un_tableau` vivait en interne) pour
que qa.py puisse exclure les mots de table de `_ordre_suspect` sans en
recopier une seconde version -- exactement le genre de divergence qu'on a
mis plusieurs sessions à débusquer ailleurs dans ce projet (deux copies du
même calcul qui finissent par ne plus dire la même chose).

`mot_dans_cellule` : même discipline, extraite de layout_tree.py pour être
réutilisée par reading_order.py (ordre de lecture à l'intérieur d'une
table, cf. son docstring) sans dupliquer le test centre-dans-bbox une
troisième fois.
"""


def dans_un_tableau(mot, tables):
    """Vérifie si le centre d'un mot tombe dans une table."""
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


def mot_dans_cellule(mot, cell_bbox) -> bool:
    """True si le CENTRE de la bbox du mot tombe dans la cellule --
    plus robuste qu'un simple chevauchement pour un mot à cheval sur une
    frontière (le chevauchement partiel avec la cellule voisine ne le
    fait pas basculer dedans à tort)."""
    if not mot.bbox or cell_bbox is None:
        return False
    cx = (mot.bbox.x0 + mot.bbox.x1) / 2
    cy = (mot.bbox.y0 + mot.bbox.y1) / 2
    return cell_bbox.x0 <= cx <= cell_bbox.x1 and cell_bbox.y0 <= cy <= cell_bbox.y1
