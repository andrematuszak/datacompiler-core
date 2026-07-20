"""
diagnostic.py — Remplit doc.diagnostic à partir de l'objet Document DÉJÀ
EXTRAIT (doc.pages[].native / .graphics). Ne rouvre JAMAIS le PDF -- c'est le
gain direct de la nouvelle architecture : diagnostic.py devient une fonction
pure de Document, plus rapide et plus simple que la version précédente qui
rouvrait le fichier avec pdfplumber.

Diagnostic est un objet UNIQUE au niveau du document (pas par page, suivant
le schéma JSON fourni) -- diagnostic.py agrège donc les signaux de toutes
les pages. C'est une vraie simplification (perte de nuance par page, ex. un
document de 15 pages où une seule page pose problème déclenchera quand même
recommend_ocr=True pour tout le document) -- les pages concernées restent
listées dans `notes` pour ne pas perdre l'info, à charge pour ocr.py/pipeline
d'affiner plus tard si besoin de cibler certaines pages seulement.

Usage : diagnostiquer(doc) -> Document (même objet, modifié en place et retourné)
"""

import re

from datacleaner.core.document import Document

SUSPECT_PATTERN = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")
TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)

SEUIL_COUVERTURE_PLEINE_PAGE = 0.85
SEUIL_BAS = 0.6
SEUIL_HAUT = 0.9


def _chiffre_dans_mot(tok):
    return any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)


def _casse_irreguliere(tok):
    return any(tok[i - 1].islower() and tok[i].isupper() for i in range(1, len(tok)))


def _texte_page(page):
    return " ".join(w.text for w in page.native.words)


def _qualite_texte(texte):
    """Même heuristique que la version précédente (taux de caractères
    suspects + tokens à structure anormale), mais appliquée au texte
    reconstruit depuis les mots déjà extraits plutôt qu'en rouvrant le pdf."""
    if not texte:
        return None
    tokens = TOKEN_PATTERN.findall(texte)
    taux_suspect = len(SUSPECT_PATTERN.findall(texte)) / len(texte) if texte else 0.0
    taux_tokens = (
        len([t for t in tokens if len(t) >= 2 and (_chiffre_dans_mot(t) or _casse_irreguliere(t))]) / len(tokens)
        if tokens else 0.0
    )
    return max(0.0, 1.0 - taux_suspect * 5 - taux_tokens * 3)


def _couverture_image_max(page):
    surface_page = page.width * page.height
    if not surface_page:
        return 0.0
    couverture = 0.0
    for img in page.graphics.images:
        if not img.bbox:
            continue
        largeur = img.bbox.x1 - img.bbox.x0
        hauteur = img.bbox.y1 - img.bbox.y0
        couverture = max(couverture, (largeur * hauteur) / surface_page)
    return couverture


def _score_ordre_lecture(page):
    """Proxy sans réouverture du PDF : regroupe les mots en lignes par leur
    position verticale (comme render.py), puis vérifie que l'ordre
    d'apparition dans page.native.words (ordre d'extraction PyMuPDF)
    correspond à l'ordre géométrique gauche->droite au sein de chaque ligne.
    Un score bas signale un flux d'extraction qui ne suit pas la géométrie
    visuelle (colonnes mélangées, mots entrelacés)."""
    mots = [w for w in page.native.words if w.bbox]
    if len(mots) < 2:
        return 1.0

    lignes = {}
    for w in mots:
        y_arrondi = round(w.bbox.y0 / 3) * 3  # tolérance de regroupement
        lignes.setdefault(y_arrondi, []).append(w)

    total_paires = 0
    paires_dans_ordre = 0
    for ligne in lignes.values():
        if len(ligne) < 2:
            continue
        for i in range(len(ligne) - 1):
            total_paires += 1
            if ligne[i].bbox.x0 <= ligne[i + 1].bbox.x0:
                paires_dans_ordre += 1

    return paires_dans_ordre / total_paires if total_paires else 1.0


def diagnostiquer(doc: Document) -> Document:
    notes = []
    scores_qualite = []
    scores_ordre = []
    a_texte_natif = False
    a_images = False
    a_tables = False
    a_images_pleine_page = False
    ocr_integre_detecte = False

    for page in doc.pages:
        texte = _texte_page(page)
        if page.native.words:
            a_texte_natif = True
        if page.graphics.images:
            a_images = True
        if page.graphics.tables:
            a_tables = True

        couverture = _couverture_image_max(page)
        pleine_page = couverture >= SEUIL_COUVERTURE_PLEINE_PAGE
        if pleine_page:
            a_images_pleine_page = True

        qualite = _qualite_texte(texte)
        if qualite is not None:
            scores_qualite.append(qualite)

        # OCR tiers déjà appliqué en amont : image pleine page + texte natif
        # présent quand même (cf. test7, session précédente)
        if pleine_page and page.native.words:
            ocr_integre_detecte = True
            notes.append(f"Page {page.number} : OCR tiers probable (image pleine page + texte natif présent)")
            qualite = min(qualite, 0.4) if qualite is not None else 0.4

        ordre = _score_ordre_lecture(page)
        scores_ordre.append(ordre)
        if ordre < 0.85:
            notes.append(f"Page {page.number} : ordre de lecture instable (score {ordre:.2f})")

        if not page.native.words:
            notes.append(f"Page {page.number} : aucun texte natif -- OCR obligatoire")

    native_text_quality = round(sum(scores_qualite) / len(scores_qualite), 3) if scores_qualite else None
    reading_order_score = round(sum(scores_ordre) / len(scores_ordre), 3) if scores_ordre else None

    recommend_ocr = (
        not a_texte_natif
        or (native_text_quality is not None and native_text_quality < SEUIL_HAUT)
        or ocr_integre_detecte
    )

    if recommend_ocr and not notes:
        notes.append("Enrichissement recommandé (raison non détaillée par page)")
    if not recommend_ocr:
        notes.append("Texte natif jugé suffisamment fiable sur toutes les pages -- OCR non recommandé (économie)")

    doc.diagnostic.has_native_text = a_texte_natif
    doc.diagnostic.has_images = a_images
    doc.diagnostic.has_tables = a_tables
    doc.diagnostic.has_full_page_images = a_images_pleine_page
    doc.diagnostic.embedded_ocr_detected = ocr_integre_detecte
    doc.diagnostic.reading_order_score = reading_order_score
    doc.diagnostic.native_text_quality = native_text_quality
    doc.diagnostic.image_quality = None  # pas de métrique fiable sans inspection visuelle -- non fabriqué
    doc.diagnostic.recommend_ocr = recommend_ocr
    doc.diagnostic.notes = notes

    return doc


if __name__ == "__main__":
    import sys
    from document import Document as _Document

    if len(sys.argv) < 2:
        print("Usage : python diagnostic.py document.json")
        sys.exit(1)

    doc = _Document.load(sys.argv[1])
    diagnostiquer(doc)
    print(doc.diagnostic)
