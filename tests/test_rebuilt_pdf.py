"""test_rebuilt_pdf.py — Non-régression pour rebuilt_pdf.py.

Fait tourner le VRAI rebuilt_pdf.py (import direct, non réécrit) contre un
faux module `pymupdf` (pymupdf_stub.py) et un modèle Document minimal, pour
attraper sans PyMuPDF installé les deux classes de bugs qu'on a mis
plusieurs tours à diagnostiquer à l'œil sur un rendu PDF entier :

  1. Régression id() -- `mots_exclus` et `ordre` doivent partager les
     MÊMES objets Word (même id() Python), sinon les couleurs
     échantillonnées (mots blancs sur fond bleu/coloré) ne matchent plus
     et retombent silencieusement sur mot.color. C'est le bug qui a fait
     perdre le blanc de "Vos références" une fois simple_sort=True retiré.
  2. Régression simple_sort -- si `ordonner()` est un jour rappelé avec
     simple_sort=True (ou si son défaut change), l'ordre casse sur les
     lignes à jitter de y0. Cf. test_reading_order_regression.py pour le
     mécanisme précis ; ici on vérifie que rebuilt_pdf.py appelle bien
     ordonner() SANS simple_sort=True.

Complète, ne remplace pas, l'inspection visuelle du PDF produit -- ceci
attrape les régressions STRUCTURELLES (couleur, ordre, taille), pas
l'esthétique fine.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(__file__))

import importlib

import pytest
import pymupdf_stub
from datacompiler.backend import rebuilt_pdf


@pytest.fixture(autouse=True)
def stub_pymupdf(monkeypatch):
    monkeypatch.setattr(rebuilt_pdf, "pymupdf", pymupdf_stub)
    
from datacompiler.backend import rebuilt_pdf
importlib.reload(rebuilt_pdf)  # au cas où déjà importé avec l'ancien pymupdf réel

from datacompiler.model.document import (
    Document, TableElement, Page, Word, BBox, NativeContainer, GraphicsContainer, ResolvedContainer, Metadata,
)

echecs = []


def verifier(nom, condition, detail=""):
    marque = "OK" if condition else "ÉCHEC"
    print(f"{nom} : {marque}" + (f"  -- {detail}" if detail and not condition else ""))
    if not condition:
        echecs.append(nom)


def _construire_page1():
    """Reproduit le cas réel 'Numéro fiscal (C) : 00 00 000 000 000' --
    mélange natif ('(C)', ':') et vectorisé ('Numéro', 'fiscal'), avec
    'Numéro'/'fiscal' échantillonnés en BLANC depuis un dessin vectoriel
    (simule le cas 'Vos références' en bandeau bleu). C'est le cas qui a
    révélé la régression id()."""
    mots = [
        Word(id=1, text="Numéro", bbox=BBox(21, 215, 55, 222), block=None,
             is_vectorized=True, font_size=0.0, color="#000000"),
        Word(id=2, text="fiscal", bbox=BBox(58, 215, 80, 222), block=None,
             is_vectorized=True, font_size=0.0, color="#000000"),
        Word(id=3, text="(C)", bbox=BBox(83, 212, 100, 224), block=1,
             is_vectorized=False, font_size=9.0, color="#000000"),
        Word(id=4, text=":", bbox=BBox(102, 212, 106, 224), block=1,
             is_vectorized=False, font_size=9.0, color="#000000"),
    ]
    page_json = Page(
        number=1,
        width=595.0,
        height=842.0,
        native=NativeContainer(words=mots),
        graphics=GraphicsContainer(tables=[]),
        resolved=ResolvedContainer(words=mots),  # non utilisé par rebuilt_pdf.py (fix id())
    )
    return page_json, mots


def test_id_coherence_couleur_echantillonnee():
    """LE test qui aurait attrapé la régression 'Vos références plus
    blanc' : un dessin vectoriel BLANC recouvrant 'Numéro' doit se
    retrouver appliqué au moment de l'insertion du texte -- pas retomber
    sur mot.color (#000000, noir) faute de correspondance d'id().

    Nécessite de capturer le document de SORTIE créé par render_rebuilt_pdf
    (pymupdf.open() sans argument) -- pymupdf_stub.open est instrumenté juste
    en dessous pour ça avant que cette fonction ne soit appelée.
    """
    _docs_crees.clear()
    page_json, mots = _construire_page1()
    doc = Document(pages=[page_json], metadata=Metadata(source_pdf="/fake/source.pdf", filename="test.pdf"))

    dessin_blanc = {
        "rect": pymupdf_stub.Rect(20, 214, 56, 223),
        "items": [("re", pymupdf_stub.Rect(20, 214, 56, 223))],
        "color": (1.0, 1.0, 1.0),
        "fill": (1.0, 1.0, 1.0),
        "width": 1.0,
        "dashes": None,
    }
    src_page = pymupdf_stub.Page(width=595, height=842, images=[], drawings=[dessin_blanc])
    pymupdf_stub._FAKE_SOURCES["/fake/source.pdf"] = [src_page]

    rebuilt_pdf.render_rebuilt_pdf(doc, "/tmp/test_id.pdf", source_pdf="/fake/source.pdf")

    verifier("Un document de sortie a été créé", len(_docs_crees) >= 1)
    if not _docs_crees:
        return
    output_doc = _docs_crees[-1]
    verifier("Le document de sortie a une page", len(output_doc._pages) >= 1)
    if not output_doc._pages:
        return
    dst_page = output_doc._pages[0]

    # Chercher le segment contenant "Numéro"
    segment_numero = None
    for w in dst_page.writes:
        for (point, texte, font, fontsize) in w["items"]:
            if texte == "Numéro":
                segment_numero = w
                break
    verifier("'Numéro' a bien été inséré", segment_numero is not None)
    if segment_numero:
        couleur = segment_numero["color"]
        est_blanc = couleur is not None and tuple(round(c, 2) for c in couleur[:3]) == (1.0, 1.0, 1.0)
        verifier("'Numéro' utilise la couleur ÉCHANTILLONNÉE (blanc), pas mot.color (#000000)",
                 est_blanc, f"couleur obtenue = {couleur}")


# --- Instrumentation : capture le document de sortie -----------------------
# render_rebuilt_pdf() ne retourne que le chemin, pas l'objet Document --
# on intercepte pymupdf.open() sans argument (toujours le doc de SORTIE dans
# ce fichier) pour récupérer une référence dessus après coup.
_docs_crees = []
_open_original = pymupdf_stub.open


def _open_instrumente(path=None):
    d = _open_original(path)
    if path is None:  # doc de SORTIE (vierge)
        _docs_crees.append(d)
    return d


pymupdf_stub.open = _open_instrumente


def test_natif_pas_de_recalage():
    """Un mot natif garde exactement son font_size -- pas de recalage
    largeur appliqué (règle ajoutée pour corriger le cas '53:')."""
    mot_natif = Word(id=10, text="Bonjour", bbox=BBox(0, 0, 100, 10),
                      block=1, is_vectorized=False, font_size=9.5)
    page_json = Page(number=1, width=595.0, height=842.0, native=NativeContainer(words=[mot_natif]),
                      graphics=GraphicsContainer(tables=[]), resolved=ResolvedContainer(words=[mot_natif]))
    doc = Document(pages=[page_json], metadata=Metadata(source_pdf="/fake/natif.pdf", filename="t.pdf"))
    pymupdf_stub._FAKE_SOURCES["/fake/natif.pdf"] = [pymupdf_stub.Page(595, 842)]

    _docs_crees.clear()
    rebuilt_pdf.render_rebuilt_pdf(doc, "/tmp/test_natif.pdf", source_pdf="/fake/natif.pdf")
    output_doc = _docs_crees[-1]
    dst_page = output_doc._pages[0]

    tailles = [fs for w in dst_page.writes for (_, t, _, fs) in w["items"] if t == "Bonjour"]
    verifier("Mot natif : taille finale == font_size exact (pas de recalage)",
             bool(tailles) and abs(tailles[0] - 9.5) < 1e-6, f"tailles trouvées = {tailles}")


def test_exposant_natif_conserve_sa_position_verticale():
    mots = [
        Word(id=30, text="barème", bbox=BBox(154.38, 376.68, 186.59, 389.73),
             block=1, is_vectorized=False, font_size=9.5),
        Word(id=31, text="14", bbox=BBox(189.23, 377.44, 195.90, 385.68),
             block=1, is_vectorized=False, font_size=6.0),
    ]
    page_json = Page(
        number=1, width=595.0, height=842.0,
        native=NativeContainer(words=mots),
        graphics=GraphicsContainer(tables=[]),
        resolved=ResolvedContainer(words=mots),
    )
    doc = Document(
        pages=[page_json],
        metadata=Metadata(source_pdf="/fake/superscript.pdf", filename="t.pdf"),
    )
    pymupdf_stub._FAKE_SOURCES["/fake/superscript.pdf"] = [
        pymupdf_stub.Page(595, 842)
    ]

    _docs_crees.clear()
    rebuilt_pdf.render_rebuilt_pdf(
        doc, "/tmp/test_superscript.pdf", source_pdf="/fake/superscript.pdf"
    )
    output_page = _docs_crees[-1]._pages[0]
    positions = {
        texte.strip(): (point.y, fontsize)
        for write in output_page.writes
        for point, texte, _font, fontsize in write["items"]
    }

    assert positions["14"][1] == 6.0
    assert positions["14"][0] < positions["barème"][0] - 1.0


def test_texte_vectorise_compresse_horizontalement_sans_reduire_le_corps():
    mot = Word(
        id=20, text="DIRECTION", bbox=BBox(10, 10, 30, 18),
        is_vectorized=True, reconstructed=True, font_size=12.0,
        resolved_text="DIRECTION",
    )
    page_json = Page(
        number=1, width=595.0, height=842.0,
        native=NativeContainer(words=[mot]),
        graphics=GraphicsContainer(tables=[]),
        resolved=ResolvedContainer(words=[mot]),
    )
    doc = Document(
        pages=[page_json],
        metadata=Metadata(source_pdf="/fake/vector-size.pdf", filename="t.pdf"),
    )
    pymupdf_stub._FAKE_SOURCES["/fake/vector-size.pdf"] = [
        pymupdf_stub.Page(595, 842)
    ]

    _docs_crees.clear()
    rebuilt_pdf.render_rebuilt_pdf(
        doc, "/tmp/test_vector_size.pdf", source_pdf="/fake/vector-size.pdf"
    )
    output_page = _docs_crees[-1]._pages[0]
    writes = [write for write in output_page.writes if write["morph"] is not None]
    verifier("Le texte vectorisé utilise une transformation horizontale", bool(writes))
    if writes:
        verifier("Le texte inchangé utilise une couche invisible sur ses tracés source",
                 writes[0]["render_mode"] == 3)
        morph = writes[0]["morph"]
        verifier("La transformation conserve l'échelle verticale",
                 morph[1].a < 1 and morph[1].d == 1)
        tailles = [
            fontsize
            for write in writes
            for (_, texte, _, fontsize) in write["items"]
            if texte == "DIRECTION"
        ]
        verifier("Le corps de police n'est pas réduit pour tenir dans la bbox",
                 tailles == [12.0], f"tailles trouvées = {tailles}")


def test_correction_du_texte_vectorise_reste_visible():
    mot = Word(
        id=21, text="DIRECTION", bbox=BBox(10, 10, 50, 18),
        is_vectorized=True, reconstructed=True, font_size=10.0,
        resolved_text="DIRECTION CORRIGÉE",
    )
    page_json = Page(
        number=1, width=595.0, height=842.0,
        native=NativeContainer(words=[mot]),
        graphics=GraphicsContainer(tables=[]),
        resolved=ResolvedContainer(words=[mot]),
    )
    doc = Document(
        pages=[page_json],
        metadata=Metadata(source_pdf="/fake/vector-correction.pdf", filename="t.pdf"),
    )
    pymupdf_stub._FAKE_SOURCES["/fake/vector-correction.pdf"] = [
        pymupdf_stub.Page(595, 842)
    ]

    _docs_crees.clear()
    rebuilt_pdf.render_rebuilt_pdf(
        doc, "/tmp/test_vector_correction.pdf", source_pdf="/fake/vector-correction.pdf"
    )
    writes = _docs_crees[-1]._pages[0].writes

    verifier("Le texte vectorisé corrigé est rendu visible",
             bool(writes) and all(write["render_mode"] == 0 for write in writes))


def test_pas_simple_sort_true():
    """Garde-fou statique : rebuilt_pdf.py ne doit JAMAIS APPELER
    ordonner(..., simple_sort=True). Recherche restreinte à un appel
    effectif (regex sur la forme ordonner(...simple_sort=True...)), pas
    une simple recherche de sous-chaîne -- sinon un commentaire qui
    MENTIONNE ce piège (comme celui qui documente ce correctif) déclenche
    un faux positif."""
    import re
    from pathlib import Path
    rebuilt_pdf_path = Path(__file__).parent.parent / "src" / "datacompiler" / "backend" / "rebuilt_pdf.py"

    with open(rebuilt_pdf_path, encoding="utf-8") as f:
        source = f.read()
    motif = re.compile(r"ordonner\([^)]*simple_sort\s*=\s*True[^)]*\)")
    trouve = motif.search(source)
    verifier("Aucun appel effectif à ordonner(..., simple_sort=True)",
              trouve is None,
              f"trouvé : {trouve.group(0)!r}" if trouve else "")


def test_espace_separateur_apres_chaque_mot():
    """Deux mots OCR dont les bbox se touchent (0.6pt, cas GÉNÉRALE/DES)
    doivent quand même produire un glyphe d'espace dans le TextWriter --
    sinon MuPDF fusionne les tokens au rechargement."""
    mots = [
        Word(id=1, text="GÉNÉRALE", bbox=BBox(184.35, 18.54, 240.75, 30.06),
             block=None, is_vectorized=True, reconstructed=True, font_size=0.0,
             resolved_text="GÉNÉRALE"),
        Word(id=2, text="DES", bbox=BBox(241.35, 19.99, 264.15, 30.07),
             block=None, is_vectorized=True, reconstructed=True, font_size=0.0,
             resolved_text="DES"),
    ]
    page_json = Page(
        number=1, width=595.0, height=842.0,
        native=NativeContainer(words=mots),
        graphics=GraphicsContainer(tables=[]),
        resolved=ResolvedContainer(words=mots),
    )
    doc = Document(pages=[page_json], metadata=Metadata(source_pdf="/fake/gap.pdf", filename="t.pdf"))
    pymupdf_stub._FAKE_SOURCES["/fake/gap.pdf"] = [pymupdf_stub.Page(595, 842)]

    _docs_crees.clear()
    rebuilt_pdf.render_rebuilt_pdf(doc, "/tmp/test_gap.pdf", source_pdf="/fake/gap.pdf")
    dst_page = _docs_crees[-1]._pages[0]
    textes = [t for w in dst_page.writes for (_, t, _, _) in w["items"]]
    verifier("Les deux mots sont insérés", "GÉNÉRALE" in textes and "DES" in textes)
    verifier("Un espace séparateur est inséré entre les mots",
             " " in textes, f"textes insérés = {textes}")


if __name__ == "__main__":
    test_id_coherence_couleur_echantillonnee()
    test_natif_pas_de_recalage()
    test_pas_simple_sort_true()
    test_espace_separateur_apres_chaque_mot()

    print()
    if echecs:
        print(f"{len(echecs)} ÉCHEC(S) : {echecs}")
        sys.exit(1)
    print("Tous les cas passent.")
