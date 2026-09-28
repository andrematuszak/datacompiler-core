"""utils/font_metrics.py — Ratio hauteur d'encre / corps (em) pour les
polices de substitution embarquées (backend/fonts/), mesuré directement
sur les contours glyphes (fontTools), pas deviné.

Contexte (session du 27/09/2026) : `font_size` pour un mot vectorisé
(OCR) était jusqu'ici assigné = hauteur de bbox mesurée, comme si
hauteur d'encre et corps de police étaient la même unité. Ce n'est
jamais le cas : la hauteur d'un glyphe (baseline -> sommet) ne
représente qu'une fraction du corps (ex. ~0.70 pour une capitale
plate, ~0.87 pour une capitale accentuée en Liberation Sans -- mesuré
empiriquement, cf. learnings.md). Ce module fournit ce ratio, mesuré
sur le vrai fichier de police utilisé au rendu (backend/rebuilt_pdf.py),
pour que frontend/ocr/vector_zones._assigner_taille_lissee puisse
convertir hauteur mesurée -> corps réel avant de lisser par ligne.

Le ratio est ancré sur la ligne de base (yMax / unitsPerEm), pas sur
l'étendue totale du glyphe (yMax - yMin) : un jambage descendant sous
la ligne de base (ex. le Q de certaines polices, dont Liberation Sans)
ne doit pas gonfler la hauteur perçue d'un mot tout en capitales --
confirmé empiriquement sur "PUBLIQUES" (test-impots-revenu.pdf) où
ignorer yMin fait converger les 5 mots de la ligne à ±0.13pt contre un
écart de 25% en utilisant la hauteur brute.
"""
from pathlib import Path
from functools import lru_cache

from fontTools.ttLib import TTFont

_FONTS_DIR = Path(__file__).parent.parent / "backend" / "fonts"
_FICHIERS = {
    (False, False): "LiberationSans-Regular.ttf",
    (True, False): "LiberationSans-Bold.ttf",
    (False, True): "LiberationSans-Italic.ttf",
    (True, True): "LiberationSans-BoldItalic.ttf",
}
_FALLBACK = "DejaVuSans.ttf"


@lru_cache(maxsize=None)
def _police(gras: bool, italic: bool) -> TTFont:
    fichier = _FONTS_DIR / _FICHIERS[(gras, italic)]
    if not fichier.exists():
        fichier = _FONTS_DIR / _FALLBACK
    return TTFont(str(fichier))


def ratio_encre_em(texte: str, gras: bool = False, italic: bool = False):
    """Ratio (hauteur d'encre du glyphe le plus haut du mot / corps de
    la police), mesuré sur les contours réels de la police de
    substitution qui sera effectivement utilisée au rendu pour ce mot
    (même sélection gras/italic que backend/rebuilt_pdf._font_objet).

    Retourne None si aucun caractère du mot n'a de glyphe avec contours
    dans la police (mot vide, tout en espaces, caractère hors police) --
    l'appelant doit alors se replier sur l'ancien comportement (hauteur
    brute) plutôt que planter.
    """
    if not texte or not texte.strip():
        return None
    font = _police(bool(gras), bool(italic))
    upm = font["head"].unitsPerEm
    glyf = font["glyf"]
    cmap = font.getBestCmap()

    y_max = 0
    trouve = False
    for c in texte:
        gname = cmap.get(ord(c))
        if gname is None or gname not in glyf:
            continue
        g = glyf[gname]
        if getattr(g, "numberOfContours", 0) == 0:
            continue  # espace, caractère sans contour
        y_max = max(y_max, g.yMax)
        trouve = True

    if not trouve:
        return None
    return y_max / upm
