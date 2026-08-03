"""vector_text.py — Détecte du texte "dessiné" en vecteurs (glyphes tracés
comme des courbes/traits) plutôt qu'écrit comme du texte natif ou capturé
comme une image bitmap. Cas typique : logo texte, titre "designé" dans un
outil vectoriel, export depuis un logiciel qui dessine les caractères au
lieu de les écrire.

Signal utilisé : le champ is_vectorized est maintenant calculé pendant
l'extraction PyMuPDF (get_drawings()) et stocké sur chaque mot Word.
Cette fonction vérifie simplement si au moins un mot de la page est marqué
comme vectorisé.

Signal utilisé, à partir de ce qui est DÉJÀ dans le modèle après extraction
(même principe que container.py/visual_integrity.py -- pas de réouverture
du PDF) : une zone à forte densité d'éléments vectoriels (lignes/courbes
courtes), de forme et de taille proches d'une ligne de texte, SANS mot
natif à cet endroit.

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
    transitive simple, pas un clustering sophistiqué (pas nécessaire vu la
    volumétrie attendue par page)."""
    groupes = []
    for e in elements:
        rattache = None
        for g in groupes:
            gx0, gy0, gx1, gy1 = g["bbox"]
            if not (e.x1 < gx0 - tolerance or e.x0 > gx1 + tolerance or
                    e.y1 < gy0 - tolerance or e.y0 > gy1 + tolerance):
                rattache = g
                break
        if rattache is None:
            groupes.append({"elements": [e], "bbox": [e.x0, e.y0, e.x1, e.y1]})
        else:
            rattache["elements"].append(e)
            rattache["bbox"][0] = min(rattache["bbox"][0], e.x0)
            rattache["bbox"][1] = min(rattache["bbox"][1], e.y0)
            rattache["bbox"][2] = max(rattache["bbox"][2], e.x1)
            rattache["bbox"][3] = max(rattache["bbox"][3], e.y1)
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


def texte_vectorise_detecte(page) -> bool:
    """Retourne True si au moins un mot de la page est marqué comme texte
    vectorisé (dessiné géométriquement plutôt qu'écrit nativement)."""
    return any(word.is_vectorized for word in page.native.words)
