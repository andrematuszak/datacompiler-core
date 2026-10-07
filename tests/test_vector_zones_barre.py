"""Non-régression : la barre oblique « / » de « Feuillet n° : 1 / 2 » (page 2) garde sa bbox.

Elle est reconstruite par géométrie (pas d'OCR). Avant correctif, _ajuster_ligne_sur_traces la
recalait comme un mot OCR et l'écrasait contre le dernier tracé de la ligne (x≈510 au lieu de 530),
d'où l'ordre de lecture « / 1 2 » à la place de « 1 / 2 ».
"""
from pathlib import Path

import pymupdf
import pytest

from datacompiler.frontend.extract.extract_pymupdf import extraire_page_pymupdf
from datacompiler.frontend.ocr.vector_zones import recuperer_texte_vectorise
from datacompiler.model.document import Document, Word
from datacompiler.model.geometry import BBox

PDF = Path(__file__).parent / "fixtures" / "impots-revenu" / "impots-revenu.pdf"


class _FauxBackend:
    """Un mot par zone, calé sur la zone : suffit à déclencher le recalage par lignes."""
    name = "faux"

    def ocraliser_zone(self, image, offset=(0.0, 0.0), dpi=300, lang=None, **kw):
        w_px, h_px = image.size if hasattr(image, "size") else (image.shape[1], image.shape[0])
        w, h = w_px * 72 / dpi, h_px * 72 / dpi
        return [Word(id=-1, text="X", resolved_text="X",
                     bbox=BBox(offset[0], offset[1], offset[0] + w, offset[1] + h),
                     source="faux", is_vectorized=True, confidence=0.9)]


def test_barre_oblique_garde_sa_position(tmp_path):
    pdf = pymupdf.open(str(PDF))
    page, _ = extraire_page_pymupdf(pdf[1], 2, 0)
    sous = pymupdf.open()
    sous.insert_pdf(pdf, from_page=1, to_page=1)
    chemin = tmp_path / "p2.pdf"
    sous.save(str(chemin))

    recuperer_texte_vectorise(Document(pages=[page]), str(chemin), {"faux": _FauxBackend()})

    barres = [w for w in page.native.words if w.text == "/" and w.source == "vector_geometry"]
    assert len(barres) == 1
    un = next(w for w in page.native.words if w.text == "1" and w.bbox.x0 > 500 and w.bbox.y0 < 50)
    deux = next(w for w in page.native.words if w.text == "2" and w.bbox.x0 > 500 and w.bbox.y0 < 50)
    assert un.bbox.x1 <= barres[0].bbox.x0 <= barres[0].bbox.x1 <= deux.bbox.x0


# --- calibrage par ligne : l'encre de la ligne voisine ne doit pas contaminer la ligne --------

def test_calibrage_ne_remonte_pas_la_seconde_ligne_des_cellules(tmp_path):
    """Page 2, bbox BRUTES réelles de Paddle (relevées avec debug_zones.py).

    « PARTS » (y0 147,4) est rattaché aux quatre « handicapés » (y0 ~150) par la tolérance de
    ligne. Avant correctif, l'encre de la ligne du dessus (bas à 148,2) était comptée dans cette
    ligne : tous ses mots remontaient à y0=142,6 et, dans les cellules 2 et 4, « handicapés »
    passait avant « dont enfants » à l'ordre de lecture."""
    brut = {
        (31.3, 140.6): [("enfants mineurs ou", 32.8, 142.1, 102.9, 149.3), ("handicapés", 46.0, 149.3, 88.7, 158.2)],
        (149.5, 140.6): [("dont enfants", 150.7, 141.6, 196.5, 149.5), ("handicapés", 153.3, 149.8, 195.6, 157.9)],
        (245.4, 140.6): [("enfants mineurs ou", 246.9, 142.1, 316.9, 149.3), ("handicapés", 260.5, 150.0, 303.0, 157.9)],
        (363.6, 140.6): [("dont enfants", 364.8, 141.6, 410.6, 149.5), ("handicapés", 367.4, 149.8, 409.7, 157.9)],
        (489.4, 136.6): [("DE", 489.4, 136.6, 503.6, 146.2)],
        (481.4, 146.5): [("PARTS", 481.9, 147.4, 510.9, 155.1)],
    }

    class _PaddleRejoue:
        name = "paddle_rejoue"

        def ocraliser_zone(self, image, offset=(0.0, 0.0), dpi=300, lang=None, **kw):
            for (ox, oy), mots in brut.items():
                if abs(ox - offset[0]) < 0.6 and abs(oy - offset[1]) < 0.6:
                    return [Word(id=-1, text=t, resolved_text=t, bbox=BBox(a, b, c, d),
                                 source="ocr_vectoriel_paddle", is_vectorized=True,
                                 reconstructed=True, confidence=0.99) for t, a, b, c, d in mots]
            return []

    pdf = pymupdf.open(str(PDF))
    page, _ = extraire_page_pymupdf(pdf[1], 2, 0)
    sous = pymupdf.open()
    sous.insert_pdf(pdf, from_page=1, to_page=1)
    chemin = tmp_path / "p2.pdf"
    sous.save(str(chemin))
    recuperer_texte_vectorise(Document(pages=[page]), str(chemin), {"p": _PaddleRejoue()})

    handicapes = [w for w in page.native.words if w.text == "handicapés"]
    premieres = [w for w in page.native.words if w.text in ("enfants mineurs ou", "dont enfants")]
    assert len(handicapes) == 4 and len(premieres) == 4
    # chaque « handicapés » reste nettement SOUS sa première ligne (≥ 4 pt d'écart sur y0 : le
    # regroupement des lignes dans un tableau se fait à 3,5 pt)
    assert min(h.bbox.y0 for h in handicapes) - max(p.bbox.y0 for p in premieres) >= 4.0
    # et garde son x : pas décalé vers la gauche comme avant (x0 = 33,3 au lieu de ~47)
    assert min(h.bbox.x0 for h in handicapes) > 45.0
