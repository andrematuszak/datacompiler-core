"""geometry.py — Utilitaires géométriques partagés entre reading_order.py
et qa.py (et potentiellement d'autres modules de compile/ à l'avenir).

Extrait de reading_order.py (où `_dans_un_tableau` vivait en interne) pour
que qa.py puisse exclure les mots de table de `_ordre_suspect` sans en
recopier une seconde version -- exactement le genre de divergence qu'on a
mis plusieurs sessions à débusquer ailleurs dans ce projet (deux copies du
même calcul qui finissent par ne plus dire la même chose).
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
