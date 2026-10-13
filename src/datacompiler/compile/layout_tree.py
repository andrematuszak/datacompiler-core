"""Build the page layout tree from geometry already present in ``page.graphics`` instead of running another extraction pass."""

from datacompiler.model.document import LayoutBox, BBox


def construire_boites_images(page) -> list:
    """Create one image LayoutBox per page image, ordered by page position."""
    boites = [
        LayoutBox(bbox=img.bbox, type="image", word_ids=[])
        for img in page.graphics.images
        if img.bbox is not None
    ]
    boites.sort(key=lambda b: (b.bbox.y0, b.bbox.x0))
    for i, boite in enumerate(boites):
        boite.reading_order = i
    return boites


def _bbox_contenu(bbox_petit, bbox_grand, marge=0.0) -> bool:
    """Return whether the smaller bounding box is fully contained in the larger box, within tolerance."""
    if bbox_petit is None or bbox_grand is None:
        return False
    return (bbox_grand.x0 - marge <= bbox_petit.x0) and (bbox_petit.x1 <= bbox_grand.x1 + marge)


def _chevauchement_y(a, b) -> bool:
    """Return whether two bounding boxes overlap vertically."""
    return a.y0 < b.y1 and b.y0 < a.y1


def _distance_x(bbox_a, bbox_b) -> float:
    """Return the horizontal gap between two bounding boxes, or zero when they overlap."""
    if bbox_a.x1 < bbox_b.x0:
        return bbox_b.x0 - bbox_a.x1
    if bbox_b.x1 < bbox_a.x0:
        return bbox_a.x0 - bbox_b.x1
    return 0.0


# Distance en-dessous de laquelle un voisin de la même ligne physique est
# considéré assez proche pour trancher une ambiguïté de cellule -- calibré
# sur les deux seuls écarts réels observés à ce jour (test-impots-revenu.pdf) :
# ~2.9pt entre "enfants" et "majeurs" (même groupe), ~52-60pt entre
# "majeurs"/"célibataires" et le premier mot de la colonne suivante (groupe
# différent). 15pt sépare proprement les deux sur CE document -- pas
# revalidé sur un autre, à recalibrer si des faux positifs/négatifs
# apparaissent sur un corpus plus large (même réserve que pour le seuil de
# largeur de _glyphe_isole_suspect).
SEUIL_PROXIMITE_MOT = 15.0


def _mot_dans_cellule(mot, cell_bbox) -> bool:
    """Return whether the word-box center falls inside the cell."""
    if not mot.bbox or cell_bbox is None:
        return False
    cx = (mot.bbox.x0 + mot.bbox.x1) / 2
    cy = (mot.bbox.y0 + mot.bbox.y1) / 2
    return cell_bbox.x0 <= cx <= cell_bbox.x1 and cell_bbox.y0 <= cy <= cell_bbox.y1


def _bbox_union(bboxes) -> "BBox | None":
    """Return the bounding box enclosing all non-null input boxes."""
    valides = [b for b in bboxes if b is not None]
    if not valides:
        return None
    return BBox(
        min(b.x0 for b in valides),
        min(b.y0 for b in valides),
        max(b.x1 for b in valides),
        max(b.y1 for b in valides),
    )


def construire_boite_tableau(table_element, mots_natifs) -> LayoutBox:
    """Build a table LayoutBox from stored cell geometry and native words."""
    lignes_boites = []
    for i, ligne_bboxes in enumerate(table_element.cell_bboxes):
        # Passe 1 : affectation SANS AMBIGUÏTÉ -- bbox du mot ENTIÈREMENT
        # contenue dans la cellule (_bbox_contenu), pas juste son centre.
        assignations = {j: [] for j in range(len(ligne_bboxes))}
        ambigus = []
        for m in mots_natifs:
            if not m.bbox:
                continue
            if not any(cb is not None and _chevauchement_y(m.bbox, cb) for cb in ligne_bboxes):
                continue  # ce mot n'est pas sur la bande y de cette ligne, ignoré ici
            candidats = [j for j, cb in enumerate(ligne_bboxes) if cb is not None and _bbox_contenu(m.bbox, cb)]
            if len(candidats) == 1:
                assignations[candidats[0]].append(m)
            else:
                ambigus.append(m)

        # Passe 2 : mots à cheval sur une frontière -- rattachés à la
        # cellule dont un mot déjà affecté (passe 1) est le plus PROCHE
        # horizontalement, restreint aux voisins de la même ligne
        # physique (_chevauchement_y). Justification empirique (cf. cas
        # "majeurs") : un mot d'en-tête peut déborder de sa colonne
        # nominale tant qu'il reste loin du contenu réel de la colonne
        # voisine -- la proximité tranche là où la géométrie de cellule
        # seule (centre ou majorité d'aire) se trompe.
        for m in ambigus:
            meilleure_cellule, meilleure_distance = None, float("inf")
            for j, cb in enumerate(ligne_bboxes):
                if cb is None:
                    continue
                for voisin in assignations[j]:
                    if not _chevauchement_y(m.bbox, voisin.bbox):
                        continue
                    d = _distance_x(m.bbox, voisin.bbox)
                    if d < meilleure_distance:
                        meilleure_distance, meilleure_cellule = d, j
            if meilleure_cellule is None or meilleure_distance > SEUIL_PROXIMITE_MOT:
                # Pas de voisin assez proche sur la même ligne -- soit
                # aucun trouvé, soit trouvé mais trop loin (chevauchement
                # Y coïncidentel entre mots sans rapport, cf. le bug
                # "célibataires" découvert en testant). Repli sur le
                # centre plutôt que de faire confiance à ce signal faible.
                meilleure_cellule = next(
                    (j for j, cb in enumerate(ligne_bboxes) if cb is not None and _mot_dans_cellule(m, cb)),
                    None,
                )
            if meilleure_cellule is not None:
                assignations[meilleure_cellule].append(m)

        cellules = []
        for j, cell_bbox in enumerate(ligne_bboxes):
            mots_cellule = sorted(assignations[j], key=lambda m: (m.bbox.y0, m.bbox.x0))
            cellules.append(LayoutBox(
                bbox=cell_bbox, type="native_text", reading_order=j, word_ids=[m.id for m in mots_cellule],
            ))
        lignes_boites.append(LayoutBox(
            bbox=_bbox_union(ligne_bboxes), type="container", reading_order=i, children=cellules,
        ))
    return LayoutBox(bbox=table_element.bbox, type="table", children=lignes_boites)


def aplatir_ids(boite: LayoutBox) -> list:
    """Traverse the layout tree in reading order and return its word IDs."""
    if boite.children:
        ids = []
        for enfant in sorted(boite.children, key=lambda b: b.reading_order):
            ids.extend(aplatir_ids(enfant))
        return ids
    return list(boite.word_ids)
