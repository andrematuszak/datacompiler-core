"""spatial_integrity.py — Ordre de lecture (proxy, sans réorganiser -- contrairement
à resolve/reading_order.py qui, lui, réordonne réellement), chevauchements
de texte, coordonnées hors-limites."""


def score_ordre_lecture(page) -> float:
    """Identique à l'ancienne _score_ordre_lecture de diagnostic.py."""
    mots = [w for w in page.native.words if w.bbox]
    if len(mots) < 2:
        return 1.0

    lignes = {}
    for w in mots:
        y_arrondi = round(w.bbox.y0 / 3) * 3
        lignes.setdefault(y_arrondi, []).append(w)

    total_paires = 0
    paires_dans_ordre = 0
    for ligne in lignes.values():
        if len(ligne) < 2:
            continue
        for i in range(len(ligne) - 1):
            total_paires += 1
            if ligne[i].bbox.x0 <= ligne[i + 1].bbox.x0:
                paires_dans_ordre += 1

    return paires_dans_ordre / total_paires if total_paires else 1.0


def _chevauchement(a, b) -> float:
    """Aire d'intersection normalisée par la plus petite des deux bbox --
    tolère un chevauchement léger (kerning, antialiasing), signale un
    recouvrement quasi total."""
    ix0, iy0 = max(a.x0, b.x0), max(a.y0, b.y0)
    ix1, iy1 = min(a.x1, b.x1), min(a.y1, b.y1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    aire_inter = (ix1 - ix0) * (iy1 - iy0)
    aire_min = min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0))
    return aire_inter / aire_min if aire_min else 0.0


SEUIL_CHEVAUCHEMENT = 0.5


def detecter_chevauchements(page) -> list:
    """Regroupe par bande y (tolérance 3pt, même logique que reading_order.py)
    pour éviter une comparaison O(n²) sur toute la page."""
    mots = [w for w in page.native.words if w.bbox]
    bandes = {}
    for w in mots:
        y = round(w.bbox.y0 / 3) * 3
        bandes.setdefault(y, []).append(w)

    paires = []
    for bande in bandes.values():
        for i in range(len(bande)):
            for j in range(i + 1, len(bande)):
                if _chevauchement(bande[i].bbox, bande[j].bbox) >= SEUIL_CHEVAUCHEMENT:
                    paires.append((bande[i], bande[j]))
    return paires


def detecter_hors_limites(page, tolerance: float = 2.0) -> list:
    """Marge de tolérance : l'arrondi de certains moteurs d'extraction peut
    légèrement déborder sans que ce soit anormal."""
    return [
        w for w in page.native.words
        if w.bbox and (
            w.bbox.x0 < -tolerance or w.bbox.y0 < -tolerance
            or w.bbox.x1 > page.width + tolerance or w.bbox.y1 > page.height + tolerance
        )
    ]

