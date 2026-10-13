"""Detect dense vector graphics that may represent text drawn as paths rather than native text or bitmap images. Results are heuristic candidates, not proof that a region contains text."""

from typing import List, Tuple

SEUIL_DENSITE_MIN = 8            # nb d'éléments vectoriels minimum dans une zone pour la considérer
HAUTEUR_MAX_LIGNE_TEXTE = 25.0   # pt -- au-delà, ça ne ressemble plus à une ligne de texte
HAUTEUR_MIN_LIGNE_TEXTE = 4.0
RATIO_LARGEUR_HAUTEUR_MIN = 1.13  # une ligne de texte est nettement plus large que haute
# Petits glyphes isolés (":" = 2 points, "la", ponctuation) : trop étroits pour passer le
# filtre de ratio, et dessinés à 3-4 pt du mot voisin (> tolérance de regroupement). On ne
# les envoie pas à l'OCR seuls (un ":" isolé n'est pas détecté) : on les RATTACHE à la zone
# de texte retenue voisine sur la même ligne, pour que l'OCR voie "avis :" d'un seul tenant.
# Éléments STRUCTURELS (cadres de cellules, bordures de tableau) : ce ne sont pas des traits de
# glyphes, mais ils touchent leurs voisins (cellules accolées à ~0-1 pt) et, avec la fusion
# transitive de _grouper_par_proximite, soudent toute une rangée -- voire deux rangées -- de
# cellules en un seul groupe. Page 2 de l'avis d'impôt : le bandeau "RÉSIDENCE EXCLUSIVE /
# ALTERNÉE" (14 pt) et les cellules du dessous (23 pt) se touchent -> un groupe de 36,9 pt de haut
# (> HAUTEUR_MAX_LIGNE_TEXTE) rejeté en bloc, donc tout le texte vectorisé de ces deux lignes
# n'arrivait jamais à l'OCR. Les glyphes, eux, sont des traits fins et courts.
TOLERANCE_GROUPE_X = 3.0         # pt -- écart horizontal max entre traits d'un même groupe
# pt -- écart vertical max (plus faible que l'horizontal : sépare les lignes serrées). Plateau
# de stabilité mesuré sur l'avis d'impôt avec le texte du lien « La notice de cet avis… » pris en
# compte : 0,85 à 1,0 donne les 12 zones du lien, 1 seule zone pour AVIS_IR_RG et 35 / 9 zones sur
# les pages 2 / 3 ; 1,05 et plus fusionne « disponible » et « cliquant ici » (descendantes du p
# contre montantes du l, q, t à 0,8 pt) ; 0,80 et moins coupe AVIS_IR_RG en 3 zones.
TOLERANCE_GROUPE_Y = 0.92
FILTRER_ELEMENTS_STRUCTURELS = True  # False = ancien comportement (utile pour un A/B de non-régression)
EPAISSEUR_MIN_BOITE = 6.0        # pt -- un rect dont les 2 côtés dépassent ça est une boîte, pas un trait de lettre
LONGUEUR_MIN_STRUCTURE = 60.0    # pt -- un trait/rect plus long que ça n'est pas un glyphe
TOLERANCE_BORD = 0.6             # pt -- un trait posé sur le bord d'une boîte structurelle en fait partie
ECART_MAX_RATTACHEMENT = 8.0      # pt -- écart horizontal max entre le petit glyphe et la zone voisine
RECOUVREMENT_VERTICAL_MIN = 0.6   # part de la hauteur du glyphe qui doit chevaucher la zone


def _rect_structurel(b) -> bool:
    """Boîte (cellule, cadre) ou rect très long : jamais un trait de lettre."""
    w, h = b.x1 - b.x0, b.y1 - b.y0
    return min(w, h) >= EPAISSEUR_MIN_BOITE or max(w, h) >= LONGUEUR_MIN_STRUCTURE


def _trait_structurel(b, boites) -> bool:
    """Classify a long vector line or rectangle as structural rather than a likely glyph."""
    w, h = b.x1 - b.x0, b.y1 - b.y0
    if max(w, h) >= LONGUEUR_MIN_STRUCTURE:
        return True
    t = TOLERANCE_BORD
    if h <= t:        # horizontal : sur le bord haut ou bas d'une boîte, dans son étendue
        for r in boites:
            if (abs(b.y0 - r.y0) <= t or abs(b.y0 - r.y1) <= t) and b.x0 >= r.x0 - t and b.x1 <= r.x1 + t:
                return True
    elif w <= t:      # vertical : sur le bord gauche ou droit
        for r in boites:
            if (abs(b.x0 - r.x0) <= t or abs(b.x0 - r.x1) <= t) and b.y0 >= r.y0 - t and b.y1 <= r.y1 + t:
                return True
    return False


def _elements_vectoriels(page) -> list:
    """Select vector graphics that may form text and group related marks."""
    rects = [r.bbox for r in getattr(page.graphics, "rects", []) if r.bbox]
    boites = [b for b in rects if _rect_structurel(b)] if FILTRER_ELEMENTS_STRUCTURELS else []
    elements = []
    for l in getattr(page.graphics, "lines", []):
        if l.bbox and not (FILTRER_ELEMENTS_STRUCTURELS and _trait_structurel(l.bbox, boites)):
            elements.append(l.bbox)
    for c in getattr(page.graphics, "curves", []):
        if c.bbox:
            elements.append(c.bbox)
    for r in rects:
        if (r.y1 - r.y0) < HAUTEUR_MAX_LIGNE_TEXTE and not (FILTRER_ELEMENTS_STRUCTURELS and _rect_structurel(r)):
            elements.append(r)
    return elements


def _grouper_par_proximite(elements, tolerance=TOLERANCE_GROUPE_X, tolerance_y=None):
    """Group nearby vector elements into candidate text regions."""
    if tolerance_y is None:
        tolerance_y = TOLERANCE_GROUPE_Y
    n = len(elements)
    parent = list(range(n))

    def find(i):
        racine = i
        while parent[racine] != racine:
            racine = parent[racine]
        while parent[i] != racine:  # compression de chemin
            parent[i], i = racine, parent[i]
        return racine

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    def proche(a, b):
        return not (a.x1 < b.x0 - tolerance or a.x0 > b.x1 + tolerance or
                    a.y1 < b.y0 - tolerance_y or a.y0 > b.y1 + tolerance_y)

    # Comparaison par paire -- O(n²), largement suffisant vu la volumétrie
    # attendue (quelques centaines d'éléments vectoriels par page au plus).
    for i in range(n):
        for j in range(i + 1, n):
            if proche(elements[i], elements[j]):
                union(i, j)

    composantes = {}
    for i, e in enumerate(elements):
        composantes.setdefault(find(i), []).append(e)

    groupes = []
    for membres in composantes.values():
        groupes.append({
            "elements": membres,
            "bbox": [
                min(e.x0 for e in membres),
                min(e.y0 for e in membres),
                max(e.x1 for e in membres),
                max(e.y1 for e in membres),
            ],
        })
    return groupes


def _mot_natif_present(page, bbox, seuil_recouvrement=0.5) -> bool:
    x0, y0, x1, y1 = bbox
    for w in page.native.words:
        if not w.bbox:
            continue
        ix0 = max(w.bbox.x0, x0)
        iy0 = max(w.bbox.y0, y0)
        ix1 = min(w.bbox.x1, x1)
        iy1 = min(w.bbox.y1, y1)
        if ix0 < ix1 and iy0 < iy1:
            aire_inter = (ix1 - ix0) * (iy1 - iy0)
            aire_mot = (w.bbox.x1 - w.bbox.x0) * (w.bbox.y1 - w.bbox.y0)
            if aire_mot > 0 and aire_inter / aire_mot >= seuil_recouvrement:
                return True
    return False


def _rattacher_petits_glyphes(zones, petits, mots_natifs=()):
    """Attach small punctuation-like glyphs to a nearby candidate text region."""
    zones = [list(z) for z in zones]
    for gx0, gy0, gx1, gy1 in petits:
        h = gy1 - gy0
        meilleur = None
        for i, (zx0, zy0, zx1, zy1) in enumerate(zones):
            recouvrement = min(gy1, zy1) - max(gy0, zy0)
            if h <= 0 or recouvrement / h < RECOUVREMENT_VERTICAL_MIN:
                continue
            ecart = gx0 - zx1 if gx0 >= zx1 else (zx0 - gx1 if gx1 <= zx0 else 0.0)
            if ecart > ECART_MAX_RATTACHEMENT:
                continue
            cle = (ecart, 0 if gx0 >= zx0 else 1)  # égalité -> zone à gauche
            if meilleur is None or cle < meilleur[0]:
                meilleur = (cle, i)
        if meilleur is not None:
            z = zones[meilleur[1]]
            z[0], z[1] = min(z[0], gx0), min(z[1], gy0)
            z[2], z[3] = max(z[2], gx1), max(z[3], gy1)
            continue

        proche_natif = False
        for mot in mots_natifs:
            if not mot.bbox or h <= 0:
                continue
            b = mot.bbox
            recouvrement = min(gy1, b.y1) - max(gy0, b.y0)
            ecart = gx0 - b.x1 if gx0 >= b.x1 else (b.x0 - gx1 if gx1 <= b.x0 else 0.0)
            if recouvrement / h >= RECOUVREMENT_VERTICAL_MIN and ecart <= ECART_MAX_RATTACHEMENT:
                proche_natif = True
                break
        if proche_natif:
            zones.append([gx0, gy0, gx1, gy1])
    return [tuple(z) for z in zones]


def zones_texte_vectorise_probable(page) -> List[Tuple[float, float, float, float]]:
    """Return candidate regions of text drawn as vector paths."""
    elements = _elements_vectoriels(page)
    if len(elements) < SEUIL_DENSITE_MIN:
        return []

    resultat = []
    petits_glyphes = []
    for g in _grouper_par_proximite(elements):
        x0, y0, x1, y1 = g["bbox"]
        largeur, hauteur = x1 - x0, y1 - y0
        if len(g["elements"]) < SEUIL_DENSITE_MIN:
            # Les glyphes de ponctuation (deux points, barre oblique) n'ont
            # pas la densité nécessaire pour former seuls une zone de texte.
            # Garder les petits groupes proches d'un mot vectorisé ou natif
            # permet de les rattacher ensuite sans OCR de traits décoratifs.
            ponctuation = (
                0 < hauteur <= HAUTEUR_MAX_LIGNE_TEXTE
                and largeur / hauteur < RATIO_LARGEUR_HAUTEUR_MIN
                and largeur <= 4.0
            )
            if ponctuation:
                petits_glyphes.append((x0, y0, x1, y1))
            continue
        if hauteur <= 0 or not (HAUTEUR_MIN_LIGNE_TEXTE <= hauteur <= HAUTEUR_MAX_LIGNE_TEXTE):
            continue
        if _mot_natif_present(page, (x0, y0, x1, y1)):
            continue  # déjà du texte natif ici -- pas des vecteurs isolés
        if largeur / hauteur < RATIO_LARGEUR_HAUTEUR_MIN:
            petits_glyphes.append((x0, y0, x1, y1))  # candidat au rattachement
            continue
        resultat.append((x0, y0, x1, y1))
    return _rattacher_petits_glyphes(resultat, petits_glyphes, page.native.words)


def couverture_texte_natif(page) -> float | None:
    """Estimate how much candidate vector text is already covered by native text."""
    surface_native = sum(
        (word.bbox.x1 - word.bbox.x0) * (word.bbox.y1 - word.bbox.y0)
        for word in page.native.words
        if word.bbox
    )
    if not surface_native:
        return 0.0 if page.native.words else None

    surface_vectorielle = sum(
        (x1 - x0) * (y1 - y0)
        for x0, y0, x1, y1 in zones_texte_vectorise_probable(page)
    )
    if not surface_vectorielle:
        return 1.0
    return surface_native / (surface_native + surface_vectorielle)


def texte_vectorise_detecte(page) -> bool:
    """Return whether the page contains likely vectorized text."""
    return bool(zones_texte_vectorise_probable(page))
