"""layout_tree.py — Construction de l'arbre LayoutBox à partir de la
géométrie déjà extraite (page.graphics), plutôt que d'une nouvelle passe
d'extraction. Cf. discussion d'architecture : liste plate triée par
coordonnées -> arbre de mise en page, lu boîte par boîte.

JALON 1 (celui-ci) : boîtes-images seulement.
  - Géométrie : page.graphics.images (pdfplumber, déjà peuplé à
    l'extraction, cf. extract/pdfplumber.py) -- aucune nouvelle extraction
    nécessaire ici.
  - PAS de texte : une boîte-image a `word_ids=[]` tant qu'aucun
    mécanisme d'extraction de texte-dans-image n'est branché (limite déjà
    documentée : image_text_probe.py détecte "y a-t-il du texte",
    n'extrait rien). Une boîte géométriquement correcte mais vide reste
    utile -- point d'ancrage dans l'arbre, peuplable plus tard sans le
    redessiner.
  - PAS encore l'arbre complet : seulement la liste des boîtes-images,
    triée en ordre de lecture simple. L'entrelacement avec les autres
    types (vector_text, native_text, table) est un jalon séparé (2-4).

Jalons suivants, non traités ici :
  2. zones de texte vectoriel (probablement via
     diagnostic/vector_text.py, déjà existant -- à vérifier s'il expose
     déjà une géométrie réutilisable, même logique que pour les images)
  3. regroupement de mots en lignes au sein d'une boîte
  4. assemblage hiérarchique complet + parcours profondeur d'abord vers
     resolved.words
"""

from datacompiler.model.document import LayoutBox, BBox


def construire_boites_images(page) -> list:
    """Une LayoutBox(type="image") par image de page.graphics.images,
    triée en ordre de lecture simple (y0 puis x0).

    Volontairement PAS entrelacée avec le reste du contenu de la page à
    ce stade -- juste la liste des boîtes-images, pour validation
    indépendante avant d'attaquer l'assemblage complet."""
    boites = [
        LayoutBox(bbox=img.bbox, type="image", word_ids=[])
        for img in page.graphics.images
        if img.bbox is not None
    ]
    boites.sort(key=lambda b: (b.bbox.y0, b.bbox.x0))
    for i, boite in enumerate(boites):
        boite.reading_order = i
    return boites


def _mot_dans_cellule(mot, cell_bbox) -> bool:
    """True si le CENTRE de la bbox du mot tombe dans la cellule --
    plus robuste qu'un simple chevauchement pour un mot à cheval sur une
    frontière (le chevauchement partiel avec la cellule voisine ne le
    fait pas basculer dedans à tort)."""
    if not mot.bbox or cell_bbox is None:
        return False
    cx = (mot.bbox.x0 + mot.bbox.x1) / 2
    cy = (mot.bbox.y0 + mot.bbox.y1) / 2
    return cell_bbox.x0 <= cx <= cell_bbox.x1 and cell_bbox.y0 <= cy <= cell_bbox.y1


def _bbox_union(bboxes) -> "BBox | None":
    """Bbox englobante d'une liste de bbox, None ignorées (cellule
    fusionnée/absente dans la grille)."""
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
    """Construit une LayoutBox(type="table") à partir de la géométrie
    persistée (table_element.cell_bboxes) et de mots natifs -- à appeler
    APRÈS que le pipeline complet a tourné (native.words doit déjà
    inclure les mots vectorisés ajoutés par l'OCR ciblé, étape 4/6), pas
    pendant l'extraction (étape 1/6, où cell_bboxes est calculé) : cf.
    docstring de table_reconstruction.cellules_bbox_degenere pour le
    détail de cette contrainte d'ordre.

    Arbre produit : table -> une boîte "container" par ligne -> une boîte
    "native_text" par cellule, portant les `word_ids` des mots dont le
    centre tombe dans cette cellule (cf. _mot_dans_cellule).

    `mots_natifs` : liste de Word (typiquement page.native.words) --
    nom générique plutôt que "page" pour rester testable sans construire
    un Document complet (cf. test synthétique)."""
    lignes_boites = []
    for i, ligne_bboxes in enumerate(table_element.cell_bboxes):
        cellules = []
        for j, cell_bbox in enumerate(ligne_bboxes):
            ids = [m.id for m in mots_natifs if _mot_dans_cellule(m, cell_bbox)]
            cellules.append(LayoutBox(
                bbox=cell_bbox, type="native_text", reading_order=j, word_ids=ids,
            ))
        lignes_boites.append(LayoutBox(
            bbox=_bbox_union(ligne_bboxes), type="container", reading_order=i, children=cellules,
        ))
    return LayoutBox(bbox=table_element.bbox, type="table", children=lignes_boites)
