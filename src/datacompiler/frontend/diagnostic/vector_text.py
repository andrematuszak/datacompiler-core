"""vector_text.py — Détecte du texte "dessiné" en vecteurs (glyphes tracés
comme des courbes/traits) plutôt qu'écrit comme du texte natif ou capturé
comme une image bitmap. Cas typique : logo texte, titre "designé" dans un
outil vectoriel, export depuis un logiciel qui dessine les caractères au
lieu de les écrire.

Les tracés PyMuPDF sont conservés durant l'extraction dans ``page.graphics``.
Le diagnostic regroupe ensuite les zones denses et retient seulement celles
qui ne contiennent pas déjà de mot natif : aucun PDF n'est rouvert ici.

LIMITE ASSUMÉE, à vérifier sur vos vrais fichiers : le modèle de données
(GraphicVector) ne stocke qu'une bbox par élément, pas le tracé détaillé
(points, direction des courbes) -- cette heuristique ne "reconnaît" donc
pas des lettres, elle repère seulement une zone dense et de forme
suspecte. Un logo abstrait dense (pas du texte) peut déclencher un faux
positif -- à traiter comme un signal à confirmer, pas un verdict certain.
Je n'ai pas pu tester sur un vrai fichier contenant ce cas (aucun dans le
corpus de test jusqu'ici) -- testé uniquement avec des données
synthétiques ci-dessous.
"""

from typing import List, Tuple

SEUIL_DENSITE_MIN = 8            # nb d'éléments vectoriels minimum dans une zone pour la considérer
HAUTEUR_MAX_LIGNE_TEXTE = 25.0   # pt -- au-delà, ça ne ressemble plus à une ligne de texte
HAUTEUR_MIN_LIGNE_TEXTE = 4.0
RATIO_LARGEUR_HAUTEUR_MIN = 1.5  # une ligne de texte est nettement plus large que haute


def _elements_vectoriels(page) -> list:
    """Rassemble lignes, courbes et rects fins (souvent utilisés pour des
    traits de lettres) en une seule liste de bbox. Suppose page.graphics a
    .lines/.curves/.rects, chacun avec un attribut .bbox -- comme dans le
    modèle d'origine. À confirmer si ça a changé dans la réorganisation."""
    elements = []
    for l in getattr(page.graphics, "lines", []):
        if l.bbox:
            elements.append(l.bbox)
    for c in getattr(page.graphics, "curves", []):
        if c.bbox:
            elements.append(c.bbox)
    for r in getattr(page.graphics, "rects", []):
        if r.bbox and (r.bbox.y1 - r.bbox.y0) < HAUTEUR_MAX_LIGNE_TEXTE:
            elements.append(r.bbox)
    return elements


def _grouper_par_proximite(elements, tolerance=3.0):
    """Regroupe les éléments par recouvrement/proximité de bbox -- fusion
    TRANSITIVE (union-find), pas une passe gloutonne à arrêt au premier
    groupe trouvé.

    CORRECTIF (remplace l'ancienne version) : l'ancienne implémentation
    rattachait chaque élément au PREMIER groupe compatible trouvé, sans
    vérifier s'il était également compatible avec un autre groupe déjà
    créé -- cas "fan-in" (élément B proche de A ET de C, mais A et C pas
    proches directement, traités dans l'ordre A, C, B) : A et C restaient
    dans deux groupes séparés au lieu de fusionner via B. Confirmé en
    pratique sur test-impots-revenu (phénomène 2 : mots fragmentés
    chevauchants type "Date ate d'établ lissement").
    """
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
                    a.y1 < b.y0 - tolerance or a.y0 > b.y1 + tolerance)

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


def _mot_natif_present(page, bbox) -> bool:
    x0, y0, x1, y1 = bbox
    for w in page.native.words:
        if not w.bbox:
            continue
        cx = (w.bbox.x0 + w.bbox.x1) / 2
        cy = (w.bbox.y0 + w.bbox.y1) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            return True
    return False


def zones_texte_vectorise_probable(page) -> List[Tuple[float, float, float, float]]:
    """Retourne les bbox (x0,y0,x1,y1) des zones suspectées de contenir du
    texte dessiné en vecteurs plutôt qu'écrit nativement."""
    elements = _elements_vectoriels(page)
    if len(elements) < SEUIL_DENSITE_MIN:
        return []

    resultat = []
    for g in _grouper_par_proximite(elements):
        if len(g["elements"]) < SEUIL_DENSITE_MIN:
            continue
        x0, y0, x1, y1 = g["bbox"]
        largeur, hauteur = x1 - x0, y1 - y0
        if hauteur <= 0 or not (HAUTEUR_MIN_LIGNE_TEXTE <= hauteur <= HAUTEUR_MAX_LIGNE_TEXTE):
            continue
        if largeur / hauteur < RATIO_LARGEUR_HAUTEUR_MIN:
            continue
        if _mot_natif_present(page, (x0, y0, x1, y1)):
            continue  # déjà du texte natif ici -- pas des vecteurs isolés
        resultat.append((x0, y0, x1, y1))
    return resultat


def couverture_texte_natif(page) -> float | None:
    """Estime la part de texte visible qui possède une couche native.

    Les surfaces des mots natifs sont comparées aux zones de glyphes vectoriels
    qui n'ont aucun mot natif associé. C'est une estimation géométrique, pas
    une mesure des pixels d'une image.
    """
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
    """True si des glyphes dessinés sans texte natif associé sont détectés."""
    return bool(zones_texte_vectorise_probable(page))
