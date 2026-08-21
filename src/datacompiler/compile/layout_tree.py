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


def construire_boite_tableau(table_element, mots_resolus) -> LayoutBox:
    """Construit une LayoutBox(type="table") à partir de la géométrie
    persistée (table_element.cell_bboxes) et de mots RÉSOLUS -- à appeler
    avec `page.resolved.words`, PAS `page.native.words`.

    Ce n'est pas seulement une question de TIMING (attendre l'étape 4/6) --
    c'est structurel : reading_order.ordonner() fait un deepcopy() de
    chaque mot dès sa première ligne (cf. compile/reading_order.py), donc
    toute la chaîne compile/ (typography, arbitrage OCR, renumérotation
    finale dans compiler._resoudre_page : `for i, mot in enumerate(...,
    start=1): mot.id = i`) opère sur des COPIES, jamais sur les objets
    d'origine de native.words. Les mots vectorisés créés par tesseract.py
    avec id=-1 (cf. son commentaire "renumérotation finale par
    compile/compiler.py") gardent donc CE -1 pour toujours dans
    native.words, peu importe à quel moment du pipeline on regarde --
    resolved.words est la SEULE liste où compiler.py garantit des id
    réels et uniques.

    Confirmé empiriquement (session du 16/08) : appel avec native.words
    -> tous les word_ids valent -1, indiscernables entre eux dès qu'une
    cellule contient plusieurs mots vectorisés.

    Arbre produit : table -> une boîte "container" par ligne -> une boîte
    "native_text" par cellule, portant les `word_ids` des mots dont le
    centre tombe dans cette cellule (cf. _mot_dans_cellule).

    LIMITE CONNUE, pas encore tranchée : `type="native_text"` est mis en
    dur sur chaque cellule, même si les mots qu'elle contient sont
    vectorisés (LayoutBox prévoit pourtant "vector_text" comme type
    distinct). Pas de règle évidente pour une cellule MIXTE (natif +
    vectorisé) -- décision de politique à prendre séparément, pas
    tranchée ici pour ne pas deviner à la place de l'appelant.

    `mots_resolus` : liste de Word (typiquement page.resolved.words) --
    nom générique plutôt que directement "page" pour rester testable sans
    construire un Document complet (cf. test synthétique)."""
    ids_invalides = {m.id for m in mots_resolus if m.id is None or m.id < 0}
    if ids_invalides:
        raise ValueError(
            f"construire_boite_tableau : {len(ids_invalides)} mot(s) avec un id "
            f"invalide (<0 ou None) parmi les mots fournis -- probablement appelé "
            f"avec page.native.words au lieu de page.resolved.words (seule liste "
            f"où compiler.py garantit des ids réels, cf. sa renumérotation finale "
            f"dans _resoudre_page). native.words ne les aura JAMAIS, quel que soit "
            f"le moment du pipeline où cette fonction est appelée."
        )

    lignes_boites = []
    for i, ligne_bboxes in enumerate(table_element.cell_bboxes):
        cellules = []
        for j, cell_bbox in enumerate(ligne_bboxes):
            ids = [m.id for m in mots_resolus if _mot_dans_cellule(m, cell_bbox)]
            cellules.append(LayoutBox(
                bbox=cell_bbox, type="native_text", reading_order=j, word_ids=ids,
            ))
        lignes_boites.append(LayoutBox(
            bbox=_bbox_union(ligne_bboxes), type="container", reading_order=i, children=cellules,
        ))
    return LayoutBox(bbox=table_element.bbox, type="table", children=lignes_boites)
