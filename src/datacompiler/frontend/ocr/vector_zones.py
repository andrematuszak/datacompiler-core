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

Accepte PLUSIEURS backends (dict nom -> instance) exposant ocraliser_zone()
(cf. ocr/base.py) -- fusionnés zone par zone via fusion_ocr.py quand
plusieurs sont fournis et disponibles (ex. Tesseract + PaddleOCR). Un seul
backend dans le dict reste un cas valide (fusion_ocr.fusionner_candidats_ocr
sur un seul candidat = pas d'arbitrage à faire, comportement inchangé).
Fonctionne indépendamment de MISTRAL_API_KEY -- Mistral n'expose pas
ocraliser_zone (bbox bloc, pas par mot) et serait simplement ignoré s'il
apparaissait dans le dict (cf. fusion_ocr.fusionner_zone_multi_backend,
qui journalise et saute tout backend en échec plutôt que de planter).
"""

import pymupdf

from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.frontend.extract.extract_pymupdf import rendre_zone_image
from datacompiler.frontend.ocr.fusion_ocr import fusionner_zone_multi_backend
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


def recuperer_texte_vectorise(doc: Document, pdf_path: str, backends: dict, lang: str = "fra", dpi: int = 300) -> Document:
    """
    backends : dict {nom: instance_de_backend}, ex.
        {"tesseract": TesseractBackend(...)}
        {"tesseract": TesseractBackend(...), "paddleocr": PaddleOCRBackend(...)}
    Chaque backend doit exposer ocraliser_zone() (cf. ocr/base.py) pour être
    utilisable ici -- les autres (Mistral) sont ignorés silencieusement par
    fusion_ocr.fusionner_zone_multi_backend, pas par ce module.
    """
# Gestion souple : conversion si un backend unique est passé au lieu d'un dictionnaire
    if not isinstance(backends, dict):
        if hasattr(backends, "ocraliser_zone"):
            backends = {"default": backends}
        else:
            return doc

    backends_utilisables = {nom: b for nom, b in backends.items() if hasattr(b, "ocraliser_zone")}
    if not backends_utilisables:
        return doc

    source = pymupdf.open(pdf_path)
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

            page_pymupdf = source[i]
            mots_natifs_existants = page.native.words  # référence avant tout ajout, pour cette page
            # Les backends (tesseract.py, paddle.py) laissent id=-1 sur les
            # mots OCR en promettant une "renumérotation finale par
            # compile/compiler.py" -- vrai UNIQUEMENT pour page.resolved.words
            # (une copie, cf. reading_order.ordonner), JAMAIS pour
            # page.native.words lui-même, où ces mots sont injectés
            # directement. Sans ce correctif, tous les mots OCR d'une même
            # page partagent id=-1 -- inoffensif tant que rien ne s'appuie
            # sur l'unicité de l'id, mais bloquant pour LayoutBox.word_ids
            # (impossible de savoir lequel de plusieurs -1 est référencé).
            prochain_id = max((w.id for w in mots_natifs_existants if w.id and w.id > 0), default=0) + 1
            for zone in zones_a_traiter:
                image, _ = rendre_zone_image(page_pymupdf, zone, dpi=dpi)
                mots = fusionner_zone_multi_backend(
                    image, offset=(zone.x0, zone.y0), backends=backends_utilisables, dpi=dpi, lang=lang
                )
                if not mots:
                    continue
                # Filtre AVANT ajout : un mot OCR qui recouvre significativement
                # du natif existant est un doublon dû à la fusion de zones
                # (cf. _chevauche_natif), pas une vraie récupération. S'applique
                # de la même façon quel que soit le backend d'origine du mot,
                # puisque fusion_ocr a déjà réduit à un seul candidat par zone
                # de chevauchement avant qu'on arrive ici.
                mots_valides = [m for m in mots if not _chevauche_natif(m, mots_natifs_existants)]
                for m in mots_valides:
                    m.id = prochain_id
                    prochain_id += 1
                page.native.words.extend(mots_valides)
    finally:
        source.close()

    return doc
