"""vector_zones.py — Orchestration de l'OCR ciblé sur les zones de texte
vectorisé détectées par diagnostic/vector_text.py.

Différence avec ocr/tesseract.py et ocr/mistral.py en mode page entière :
ceux-là remplissent page.ocr, en attente d'un arbitrage dans compile/
(alignment.py + conflict_resolution.py) contre page.native.words existant.
Ici il n'y a RIEN à arbitrer -- pas de désaccord, un vide géométrique à
combler. Les mots produits sont donc injectés directement dans
page.native.words (is_vectorized=True, source="ocr_vectoriel"), EN AMONT
du pipeline compile/ : ils traversent reading_order/typography comme
n'importe quel mot natif, sans jamais passer par alignment.py.

Nécessite un backend exposant ocraliser_zone() (cf. ocr/base.py) --
aujourd'hui seul TesseractBackend le fait (bbox par mot). Fonctionne donc
indépendamment de MISTRAL_API_KEY.
"""

import fitz

from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.frontend.extract.pymupdf import rendre_zone_image
from datacompiler.model.document import BBox, Document

MARGE_ZONE = 2.0  # pt -- contexte autour de la bbox détectée ; une zone trop serrée nuit à Tesseract

def _chevauche_bbox(a, b):
    """AABB overlap -- même logique que _chevauche dans tesseract.py,
    appliquée ici aux ZONES (après expansion par MARGE_ZONE)."""
    return not (a.x1 <= b.x0 or b.x1 <= a.x0 or a.y1 <= b.y0 or b.y1 <= a.y0)


def _fusionner_zones_chevauchantes(zones):
    """Fusionne par composantes connexes les zones (déjà marginées) dont
    les bbox se chevauchent -- même principe que
    vector_text._grouper_par_proximite, appliqué aux zones plutôt qu'aux
    éléments vectoriels bruts."""
    n = len(zones)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _chevauche_bbox(zones[i], zones[j]):
                union(i, j)

    composantes = {}
    for i, z in enumerate(zones):
        composantes.setdefault(find(i), []).append(z)

    return [
        BBox(
            min(z.x0 for z in membres),
            min(z.y0 for z in membres),
            max(z.x1 for z in membres),
            max(z.y1 for z in membres),
        )
        for membres in composantes.values()
    ]

def _chevauche_natif(mot, mots_natifs, seuil_recouvrement=0.5):
    """True si `mot` (produit par OCR de zone) recouvre significativement un
    mot déjà natif -- signe qu'il duplique du texte déjà bien extrait par
    PyMuPDF plutôt que de combler un vrai vide.

    Nécessaire depuis l'ajout de _fusionner_zones_chevauchantes : la fusion
    produit un rectangle ENGLOBANT plusieurs zones individuellement validées
    par vector_text._mot_natif_present, mais ce rectangle peut avaler une
    portion de texte natif située ENTRE deux zones fusionnées -- jamais
    couverte par aucune zone individuelle, donc jamais testée en amont. Le
    crop+OCR du rectangle plus large relit alors ce texte natif et produit un
    doublon -- pas un faux positif de détection de zone, un effet de bord de
    la fusion géométrique elle-même."""
    if not mot.bbox:
        return False
    for nat in mots_natifs:
        if not nat.bbox:
            continue
        x0 = max(mot.bbox.x0, nat.bbox.x0)
        y0 = max(mot.bbox.y0, nat.bbox.y0)
        x1 = min(mot.bbox.x1, nat.bbox.x1)
        y1 = min(mot.bbox.y1, nat.bbox.y1)
        if x0 < x1 and y0 < y1:
            intersection = (x1 - x0) * (y1 - y0)
            aire_mot = (mot.bbox.x1 - mot.bbox.x0) * (mot.bbox.y1 - mot.bbox.y0)
            if aire_mot > 0 and intersection / aire_mot >= seuil_recouvrement:
                return True
    return False


def recuperer_texte_vectorise(doc: Document, pdf_path: str, backend, lang: str = "fra", dpi: int = 300) -> Document:
    if not hasattr(backend, "ocraliser_zone"):
        return doc

    source = fitz.open(pdf_path)
    try:
        for i, page in enumerate(doc.pages):
            zones = zones_texte_vectorise_probable(page)
            if not zones:
                continue

            zones_marginees = [
                BBox(x0 - MARGE_ZONE, y0 - MARGE_ZONE, x1 + MARGE_ZONE, y1 + MARGE_ZONE)
                for x0, y0, x1, y1 in zones
            ]
            zones_a_traiter = _fusionner_zones_chevauchantes(zones_marginees)

            page_fitz = source[i]
            mots_natifs_existants = page.native.words  # référence avant tout ajout, pour cette page
            for zone in zones_a_traiter:
                image, _ = rendre_zone_image(page_fitz, zone, dpi=dpi)
                try:
                    mots = backend.ocraliser_zone(image, offset=(zone.x0, zone.y0), lang=lang, dpi=dpi)
                except NotImplementedError:
                    continue
                # Filtre AVANT ajout : un mot OCR qui recouvre significativement
                # du natif existant est un doublon dû à la fusion de zones
                # (cf. _chevauche_natif), pas une vraie récupération.
                mots_valides = [m for m in mots if not _chevauche_natif(m, mots_natifs_existants)]
                page.native.words.extend(mots_valides)
    finally:
        source.close()

    return doc


