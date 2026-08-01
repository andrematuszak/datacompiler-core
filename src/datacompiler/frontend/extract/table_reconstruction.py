"""table_reconstruction.py — Repli pour les tableaux que pdfplumber détecte
mais dont il ne trouve pas les colonnes (aucune verticale interne, cf.
test-sans-bordures-2-extrait.pdf : un tableau RFC dont les filets sont des
segments de LIGNES HORIZONTALES coupés exactement aux frontières de
colonnes, mais sans aucune verticale interne pour le confirmer).

Ne remplace PAS find_tables() -- vient en repli uniquement quand son
résultat est "dégénéré" (une seule colonne détectée alors que la table est
large), reconstruit alors les colonnes à partir des points de rupture
récurrents des segments horizontaux (lignes ou rects fins utilisés comme
filets, cf. test-sans-bordures.pdf où les filets sont des rects de 0.48pt
de hauteur, pas des objets ligne).

Additif : n'importe rien de nouveau dans extract.py, à appeler
explicitement depuis la boucle d'extraction des tableaux quand tu es prêt.
"""

from collections import Counter


def table_degenere(table_pdfplumber, largeur_min=200.0):
    """True si la table détectée par pdfplumber n'a en réalité qu'une
    seule colonne alors que sa bbox est large -- signe probable d'un
    tableau sans verticale interne, mal détecté par la stratégie par
    défaut plutôt qu'un vrai tableau à une colonne (rare au-delà de
    quelques dizaines de points de large)."""
    rows = table_pdfplumber.extract()
    if not rows:
        return False
    nb_colonnes = max(len(r) for r in rows)
    if nb_colonnes > 1:
        return False
    x0, top, x1, bottom = table_pdfplumber.bbox
    return (x1 - x0) > largeur_min


def _segments_horizontaux(page_plumb, bbox, tolerance_hauteur=0.6):
    """Segments 'horizontaux' de la zone bbox, qu'ils soient des objets
    ligne ou des rects très fins utilisés comme filets (cf.
    test-sans-bordures.pdf : filets en rects de 0.48pt de hauteur, pas des
    objets ligne)."""
    x0_tab, top_tab, x1_tab, bottom_tab = bbox
    segments = []
    for l in page_plumb.lines:
        if abs(l["top"] - l["bottom"]) < tolerance_hauteur and top_tab - 1 <= l["top"] <= bottom_tab + 1:
            segments.append((l["x0"], l["x1"], l["top"]))
    for r in page_plumb.rects:
        if r.get("height", 999) <= tolerance_hauteur and top_tab - 1 <= r["top"] <= bottom_tab + 1:
            segments.append((r["x0"], r["x1"], r["top"]))
    return segments


def _frontieres_colonnes(segments, nb_lignes, seuil_fraction=0.3):
    """Points de rupture (x0/x1) des segments horizontaux qui reviennent
    sur une fraction significative des lignes du tableau -- signe d'une
    vraie frontière de colonne, même sans verticale complète pour la
    confirmer."""
    points = Counter()
    for x0, x1, _ in segments:
        points[round(x0, 1)] += 1
        points[round(x1, 1)] += 1
    seuil = max(2, int(nb_lignes * seuil_fraction))
    return sorted(x for x, freq in points.items() if freq >= seuil)


def _frontieres_lignes(segments, bbox):
    """Positions y des séparateurs de lignes -- définit les bandes de
    lignes RÉELLES du tableau. Important pour le texte qui wrappe sur
    plusieurs lignes physiques au sein d'une seule ligne de tableau (ex.
    "HTTP Authentication-Info...\\nHeader Fields") : sans ça, un simple
    regroupement par proximité verticale détecterait à tort une ligne de
    tableau supplémentaire pour chaque retour à la ligne wrappé."""
    x0_tab, top_tab, x1_tab, bottom_tab = bbox
    ys = sorted(set(round(y, 1) for _, _, y in segments))
    if not ys or ys[0] > top_tab + 1:
        ys = [top_tab] + ys
    if ys[-1] < bottom_tab - 1:
        ys = ys + [bottom_tab]
    return ys


def reconstruire(page_plumb, table_pdfplumber):
    """Reconstruit les lignes d'un tableau "dégénéré" (cf. table_degenere)
    à partir des points de rupture récurrents de ses filets horizontaux.
    Retourne une liste de lignes (chacune une liste de chaînes), ou None si
    le signal n'est pas assez net pour reconstruire quoi que ce soit de
    fiable -- dans ce cas, le résultat original de pdfplumber doit être
    conservé tel quel plutôt que remplacé par quelque chose de pire."""
    bbox = table_pdfplumber.bbox
    x0_tab, top_tab, x1_tab, bottom_tab = bbox

    segments = _segments_horizontaux(page_plumb, bbox)
    if not segments:
        return None

    lignes_y = _frontieres_lignes(segments, bbox)
    if len(lignes_y) < 2:
        return None
    nb_lignes = len(lignes_y) - 1

    frontieres_x = _frontieres_colonnes(segments, nb_lignes)
    if frontieres_x and frontieres_x[0] > x0_tab + 2:
        frontieres_x = [x0_tab] + frontieres_x
    if frontieres_x and frontieres_x[-1] < x1_tab - 2:
        frontieres_x = frontieres_x + [x1_tab]

    # il faut au moins les deux bords + une frontière interne pour que ça
    # vaille le coup -- sinon on n'a rien de plus que la détection standard
    if len(frontieres_x) < 3:
        return None

    zone = page_plumb.crop(bbox)
    mots = zone.extract_words()

    def bande_y(y0):
        for i in range(len(lignes_y) - 1):
            if lignes_y[i] - 1 <= y0 < lignes_y[i + 1] + 1:
                return i
        return len(lignes_y) - 2

    def bande_x(x0):
        for i in range(len(frontieres_x) - 1):
            if frontieres_x[i] - 1 <= x0 < frontieres_x[i + 1] + 1:
                return i
        return len(frontieres_x) - 2

    grille = {}
    for w in mots:
        cle = (bande_y(w["top"]), bande_x(w["x0"]))
        grille.setdefault(cle, []).append(w)

    resultat = []
    for i in range(nb_lignes):
        ligne = []
        for j in range(len(frontieres_x) - 1):
            mots_cellule = sorted(grille.get((i, j), []), key=lambda w: (w["top"], w["x0"]))
            ligne.append(" ".join(w["text"] for w in mots_cellule))
        resultat.append(ligne)
    return resultat


def extraire_lignes(page_plumb, table_pdfplumber):
    """Point d'entrée : retourne les lignes de la table, en tentant la
    reconstruction seulement si la détection par défaut est dégénérée, et
    en revenant au résultat original si la reconstruction elle-même échoue
    ou n'apporte rien de plus fiable."""
    rows = table_pdfplumber.extract()
    if table_degenere(table_pdfplumber):
        reconstruit = reconstruire(page_plumb, table_pdfplumber)
        if reconstruit is not None:
            return reconstruit
    return rows
