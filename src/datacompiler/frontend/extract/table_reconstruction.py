"""Reconstruct tables detected by pdfplumber when their columns cannot be inferred from internal vertical rules."""

from collections import Counter


def table_degenere(table_pdfplumber, largeur_min=200.0):
    """Return whether a wide detected table has only one column, suggesting that internal separators were missed."""
    rows = table_pdfplumber.extract()
    if not rows:
        return False
    nb_colonnes = max(len(r) for r in rows)
    if nb_colonnes > 1:
        return False
    x0, top, x1, bottom = table_pdfplumber.bbox
    return (x1 - x0) > largeur_min


def _segments_horizontaux(page_plumb, bbox, tolerance_hauteur=0.6):
    """Find horizontal rules within the table bounds, including thin rectangles used as rules."""
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
    """Find recurring x positions that indicate column boundaries, including tables without vertical rules."""
    points = Counter()
    for x0, x1, _ in segments:
        points[round(x0, 1)] += 1
        points[round(x1, 1)] += 1
    seuil = max(2, int(nb_lignes * seuil_fraction))
    return sorted(x for x, freq in points.items() if freq >= seuil)


def _frontieres_lignes(segments, bbox):
    """Find horizontal separators that define actual table rows."""
    x0_tab, top_tab, x1_tab, bottom_tab = bbox
    ys = sorted(set(round(y, 1) for _, _, y in segments))
    if not ys or ys[0] > top_tab + 1:
        ys = [top_tab] + ys
    if ys[-1] < bottom_tab - 1:
        ys = ys + [bottom_tab]
    return ys


def _grille(page_plumb, table_pdfplumber):
    """Derive row and column boundaries from horizontal table rules."""
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

    if len(frontieres_x) < 3:
        return None

    return lignes_y, frontieres_x


def reconstruire(page_plumb, table_pdfplumber):
    """Reconstruct rows and cell boxes for a degenerate table using recurring rule intersections."""
    grille = _grille(page_plumb, table_pdfplumber)
    if grille is None:
        return None
    lignes_y, frontieres_x = grille
    nb_lignes = len(lignes_y) - 1

    zone = page_plumb.crop(table_pdfplumber.bbox)
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

    grille_mots = {}
    for w in mots:
        cle = (bande_y(w["top"]), bande_x(w["x0"]))
        grille_mots.setdefault(cle, []).append(w)

    resultat = []
    for i in range(nb_lignes):
        ligne = []
        for j in range(len(frontieres_x) - 1):
            mots_cellule = sorted(grille_mots.get((i, j), []), key=lambda w: (w["top"], w["x0"]))
            ligne.append(" ".join(w["text"] for w in mots_cellule))
        resultat.append(ligne)
    return resultat


def extraire_lignes(page_plumb, table_pdfplumber):
    """Return reconstructed table text rows using the legacy text-only interface."""
    rows = table_pdfplumber.extract()
    if table_degenere(table_pdfplumber):
        reconstruit = reconstruire(page_plumb, table_pdfplumber)
        if reconstruit is not None:
            return reconstruit
    return rows


def extraire_lignes_et_cellules(page_plumb, table_pdfplumber):
    """Return reconstructed table rows and cell geometry from one shared grid calculation."""
    rows_standard = table_pdfplumber.extract()

    if table_degenere(table_pdfplumber):
        grille = _grille(page_plumb, table_pdfplumber)
        if grille is not None:
            lignes_y, frontieres_x = grille
            nb_lignes = len(lignes_y) - 1
            nb_colonnes = len(frontieres_x) - 1

            zone = page_plumb.crop(table_pdfplumber.bbox)
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

            grille_mots = {}
            for w in mots:
                cle = (bande_y(w["top"]), bande_x(w["x0"]))
                grille_mots.setdefault(cle, []).append(w)

            rows, cell_bboxes = [], []
            for i in range(nb_lignes):
                ligne_texte, ligne_bbox = [], []
                for j in range(nb_colonnes):
                    mots_cellule = sorted(grille_mots.get((i, j), []), key=lambda w: (w["top"], w["x0"]))
                    ligne_texte.append(" ".join(w["text"] for w in mots_cellule))
                    ligne_bbox.append((frontieres_x[j], lignes_y[i], frontieres_x[j + 1], lignes_y[i + 1]))
                rows.append(ligne_texte)
                cell_bboxes.append(ligne_bbox)
            return rows, cell_bboxes

    # Standard (non dégénéré, ou repli sans grille fiable) : texte de
    # .extract(), géométrie de .rows[i].cells[j] -- exposés par
    # pdfplumber pour la MÊME table, cohérents entre eux par
    # construction de la librairie (contrairement à deux appels
    # .extract() séparés, cf. avertissement plus haut).
    cell_bboxes = [list(row.cells) for row in table_pdfplumber.rows]
    return rows_standard, cell_bboxes
