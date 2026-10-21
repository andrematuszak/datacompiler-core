"""Non-régression : les cadres de cellules ne doivent pas souder le texte vectorisé.

Page 2 de l'avis d'impôt : le bandeau « RÉSIDENCE EXCLUSIVE / ALTERNÉE » et les cellules du
dessous se touchent ; avant correctif, leur groupe (36,9 pt de haut) était rejeté en bloc et
aucun mot de ces deux lignes n'arrivait à l'OCR. La rangée de cellules du haut formait, elle,
une seule zone de 535 pt de large.
"""
from pathlib import Path

import pymupdf
import pytest

from datacompiler.frontend.diagnostic import vector_text
from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.frontend.extract.extract_pymupdf import extraire_page_pymupdf

PDF = Path(__file__).parent / "fixtures" / "tax-notice.pdf"


@pytest.fixture(scope="module")
def page2():
    doc = pymupdf.open(str(PDF))
    page, _ = extraire_page_pymupdf(doc[1], 2, 0)
    return page


def _dans(zones, y_min, y_max):
    return [z for z in zones if y_min <= z[1] and z[3] <= y_max]


def test_bandeau_residence_et_cellules_du_dessous_ont_des_zones(page2):
    zones = zones_texte_vectorise_probable(page2)
    assert len(_dans(zones, 125, 138)) >= 3   # RÉSIDENCE, EXCLUSIVE, RÉSIDENCE ALTERNÉE
    assert len(_dans(zones, 140, 160)) >= 4   # une zone par cellule « enfants mineurs / dont enfants »


def test_rangee_de_cellules_du_haut_nest_pas_une_seule_zone(page2):
    zones = _dans(zones_texte_vectorise_probable(page2), 85, 108)
    assert len(zones) >= 5
    assert max(z[2] - z[0] for z in zones) < 150


def test_ancien_comportement_reproductible(page2, monkeypatch):
    monkeypatch.setattr(vector_text, "FILTRER_ELEMENTS_STRUCTURELS", False)
    zones = zones_texte_vectorise_probable(page2)
    # c'est le bug : rien à gauche de la colonne « NOMBRE DE PARTS » (x < 440)
    assert [z for z in _dans(zones, 125, 160) if z[2] < 440] == []


# --- tolérance verticale + exclusion des liens (page 1) -------------------------------------

@pytest.fixture(scope="module")
def page1():
    doc = pymupdf.open(str(PDF))
    page, _ = extraire_page_pymupdf(doc[0], 1, 0)
    return page


def test_avis_ir_rg_reste_une_seule_zone(page1):
    """Une tolérance verticale trop faible fragmente « AVIS_IR_RG » (souligné bas) en plusieurs zones."""
    zones = [z for z in zones_texte_vectorise_probable(page1) if 500 <= z[0] <= 545 and 28 <= z[1] <= 42]
    assert len(zones) == 1


def test_lignes_serrees_separees_par_la_tolerance_verticale(page1, monkeypatch):
    """Avec l'ancienne tolérance isotrope (3 pt), les lignes serrées se soudent en un bloc
    de plus de 25 pt : rejeté en bloc."""
    ref = len(zones_texte_vectorise_probable(page1))
    monkeypatch.setattr(vector_text, "TOLERANCE_GROUPE_Y", 3.0)
    assert len(zones_texte_vectorise_probable(page1)) < ref
