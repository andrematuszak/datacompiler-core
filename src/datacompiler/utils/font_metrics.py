"""Measure glyph ink height relative to the font em size for substitute fonts bundled with the PDF renderers."""
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
    """Measure the tallest glyph’s ink height relative to the font em size for the configured substitute font."""
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
