"""pymupdf_stub.py — Faux module `pymupdf`, juste assez pour importer et exécuter
rebuilt_pdf.py sans PyMuPDF installé. À enregistrer dans sys.modules AVANT
d'importer rebuilt_pdf.py :

    import sys
    import pymupdf_stub
    sys.modules["pymupdf"] = pymupdf_stub

But : tester le VRAI rebuilt_pdf.py (non modifié, non réécrit) plutôt qu'une
copie séparée -- éviter le piège déjà rencontré plusieurs fois dans ce
projet (tester un fichier différent de celui qui tourne réellement).

`text_length` est une approximation déterministe (pas la vraie métrique
LiberationSans) -- suffisant pour vérifier la LOGIQUE de branchement
(recalage sauté pour les natifs, emprunt de taille, clamp), pas pour
valider des valeurs de rendu pixel-exactes.
"""

from types import SimpleNamespace

def paper_size(name):
    """Bouchon pour simuler pymupdf.paper_size."""
    # Renvoie les dimensions A4 standards en points (largeur, hauteur)
    return (595.0, 842.0)

class Point:
    def __init__(self, x, y):
        self.x, self.y = x, y

    def __repr__(self):
        return f"Point({self.x}, {self.y})"


class Rect:
    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1

    def get_area(self):
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)

    @property
    def is_empty(self):
        return self.x1 <= self.x0 or self.y1 <= self.y0

    def __and__(self, other):
        x0, y0 = max(self.x0, other.x0), max(self.y0, other.y0)
        x1, y1 = min(self.x1, other.x1), min(self.y1, other.y1)
        return Rect(x0, y0, x1, y1)

    def __repr__(self):
        return f"Rect({self.x0}, {self.y0}, {self.x1}, {self.y1})"


class Font:
    def __init__(self, fontfile=None):
        self.fontfile = fontfile

    def text_length(self, text, fontsize):
        # Approximation déterministe : ~0.5em par caractère.
        return len(text) * fontsize * 0.5


class TextWriter:
    def __init__(self, rect):
        self.rect = rect
        self.appended = []  # [(point, texte, font, fontsize)]

    def append(self, point, text, font=None, fontsize=None):
        self.appended.append((point, text, font, fontsize))

    def write_text(self, page, color=None, render_mode=None, opacity=None, morph=None):
        page.writes.append({
            "color": color,
            "render_mode": render_mode,
            "opacity": opacity,
            "morph": morph,
            "items": list(self.appended),
        })


class Shape:
    def draw_line(self, *a, **kw): pass
    def draw_rect(self, *a, **kw): pass
    def draw_bezier(self, *a, **kw): pass
    def draw_polyline(self, *a, **kw): pass
    def finish(self, **kw): pass
    def commit(self): pass
    def __bool__(self): return True


class Page:
    """Page SOURCE (pymupdf page brute) -- get_images/get_drawings/etc."""
    def __init__(self, width=595.0, height=842.0, images=None, drawings=None):
        self.rect = SimpleNamespace(width=width, height=height)
        self._images = images or []
        self._drawings = drawings or []
        self.writes = []  # rempli par TextWriter.write_text (page destination)
        self.parent = None

    def get_images(self):
        return self._images

    def get_image_rects(self, xref):
        return []

    def get_drawings(self):
        return self._drawings

    def new_shape(self):
        return Shape()

    def insert_image(self, rect, stream=None):
        pass


class _Doc:
    def __init__(self, pages=None):
        self._pages = list(pages or [])
        self.saved_path = None
        self.metadata = {}

    def __len__(self):
        return len(self._pages)

    def __iter__(self):
        return iter(self._pages)

    def __getitem__(self, i):
        return self._pages[i]

    def new_page(self, width=595.0, height=842.0):
        p = Page(width=width, height=height)
        p.parent = self
        self._pages.append(p)
        return p

    def set_metadata(self, d):
        self.metadata = d

    def subset_fonts(self):
        pass

    def save(self, path, **kw):
        self.saved_path = path

    def extract_image(self, xref):
        return {"image": b""}

    def close(self):
        pass

Document = _Doc  # alias pour rebuilt_pdf.py

# Registre : chemin -> liste de Page, pour que pymupdf.open(path) retourne des
# pages pré-construites par le test. pymupdf.open() sans argument (le doc de
# sortie, vierge) retourne toujours un _Doc vide.
_FAKE_SOURCES = {}


def open(path=None):  # noqa: A001 (redéfinit sciemment open, comme pymupdf)
    if path is not None and path in _FAKE_SOURCES:
        return _Doc(pages=_FAKE_SOURCES[path])
    return _Doc()
