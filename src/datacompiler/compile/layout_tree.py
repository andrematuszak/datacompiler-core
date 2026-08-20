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

from datacompiler.model.document import LayoutBox


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
