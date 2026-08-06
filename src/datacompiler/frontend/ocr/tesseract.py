"""tesseract_backend.py — OCR local (Tesseract), utile pour un client qui
refuse d'envoyer ses documents à un tiers (Mistral = API distante). Qualité
généralement inférieure à Mistral sur mise en page complexe/polices
inhabituelles, mais aucune dépendance réseau ni exposition du document.

Différence structurelle IMPORTANTE avec Mistral : Tesseract donne une bbox
ET une confiance PAR MOT (via pytesseract.image_to_data), alors que Mistral
ne donne de bbox qu'au niveau bloc/paragraphe (cf. resolve/alignment.py,
qui documente cette limite pour Mistral). Avec ce backend, un vrai
alignement GÉOMÉTRIQUE mot-à-mot devient possible -- pas implémenté ici
(alignment.py actuel aligne par texte/séquence, ce qui reste valide avec ce
backend aussi), mais c'est une direction à explorer si la précision de
repositionnement des corrections devient un besoin.

Dépendances : pytesseract, Pillow, et le binaire `tesseract` installé sur
le système (PAS un paquet pip -- `apt install tesseract-ocr` ou équivalent).
"""

import io

import fitz
import pytesseract
from PIL import Image

from datacompiler.model.document import BBox, Document, Word

from datacompiler.frontend.ocr.base import OcrBackend


_PSM_LAYOUT_GENERAL = 3   # défaut Tesseract : segmentation automatique de page -- bonne mise en page générale
_PSM_BLOC_UNIFORME = 6    # traite l'image comme un bloc de texte uniforme -- meilleur sur les tableaux denses de chiffres

# Tokens purement ponctuation/bordure, quasi toujours des artefacts de
# grille de tableau mal lue plutôt que du vrai contenu -- exclus
# INDÉPENDAMMENT de la confiance : certains ont une confiance élevée malgré
# tout (confirmé en pratique sur un vrai scan : des "|" à plus de 90%).
_CARACTERES_BRUIT_BORDURE = set("|[]{}_\\/~")
_CONFIANCE_MIN = 0.30  # filtre le bruit restant (texte réellement illisible)


def _extraire_tesseract(image, lang, psm):
    donnees = pytesseract.image_to_data(image, lang=lang, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
    mots = []
    for j in range(len(donnees["text"])):
        texte = donnees["text"][j].strip()
        if not texte:
            continue
        conf_brute = float(donnees["conf"][j])
        confiance = conf_brute / 100.0 if conf_brute >= 0 else None
        mots.append({
            "text": texte,
            "x0": donnees["left"][j], "y0": donnees["top"][j],
            "x1": donnees["left"][j] + donnees["width"][j],
            "y1": donnees["top"][j] + donnees["height"][j],
            "confidence": confiance,
        })
    return mots


def _chevauche(a, b):
    return not (a["x1"] <= b["x0"] or b["x1"] <= a["x0"] or a["y1"] <= b["y0"] or b["y1"] <= a["y0"])


def _bruit_bordure(texte):
    """True si le token n'est composé QUE de caractères de bordure/
    ponctuation isolée -- quasi toujours une ligne de grille de tableau mal
    lue par PSM 6, pas un vrai mot. Exclu indépendamment de la confiance."""
    return all(c in _CARACTERES_BRUIT_BORDURE for c in texte)


def _extraire_deux_passes(image, lang):
    """Fusionne deux passes Tesseract : PSM 3 en base, complété par tout ce
    que PSM 6 trouve dans les zones où PSM 3 n'a RIEN détecté du tout (pas
    de chevauchement de bbox).

    Découvert sur un vrai scan (test8, compte de copropriété) : PSM 3 seul
    rate systématiquement les colonnes de montants d'un tableau de charges
    -- visibles à l'œil nu dans le scan, absentes du résultat par défaut,
    pas un problème de qualité d'image. PSM 6 seul les récupère mais perd
    certains éléments de mise en page générale (ex. un titre en bandeau
    "RESIDENCE ..." disparaît). Fusionner plutôt que choisir un seul mode --
    même principe que le seuil adaptatif de reading_order.py : une seule
    stratégie globale ne suffit pas partout sur la page."""
    mots_a = _extraire_tesseract(image, lang, psm=_PSM_LAYOUT_GENERAL)
    mots_b = _extraire_tesseract(image, lang, psm=_PSM_BLOC_UNIFORME)

    ajouts = [b for b in mots_b if not any(_chevauche(a, b) for a in mots_a)]
    fusion = mots_a + ajouts

    fusion = [
        m for m in fusion
        if not _bruit_bordure(m["text"])
        and (m["confidence"] is None or m["confidence"] >= _CONFIANCE_MIN)
    ]

    # Retrié par position (haut->bas, gauche->droite) : les ajouts PSM 6
    # sont sinon en vrac à la fin de la liste, ce qui nuirait à
    # l'alignement séquentiel natif<->OCR de resolve/alignment.py (qui
    # suppose les deux flux dans un ordre de lecture approximativement
    # comparable). Tri simple, pas la logique de colonnes de
    # reading_order.py -- suffisant ici, l'alignement se fait par texte
    # pas par position exacte.
    fusion.sort(key=lambda m: (round(m["y0"] / 10), m["x0"]))
    return fusion


def _parser_image(image, lang: str, scale: float) -> list:
    """Fait tourner Tesseract sur UNE image déjà rendue (stratégie à deux
    passes, cf. _extraire_deux_passes) et retourne une liste de Word --
    séparé de ocraliser() pour être testable directement avec une image
    (PNG/PIL), sans dépendre de fitz pour la conversion PDF -> image."""
    mots_bruts = _extraire_deux_passes(image, lang)
    mots = []
    for m in mots_bruts:
        x = m["x0"] / scale
        y = m["y0"] / scale
        largeur = (m["x1"] - m["x0"]) / scale
        hauteur = (m["y1"] - m["y0"]) / scale
        mots.append(Word(
            id=len(mots) + 1,
            text=m["text"],
            bbox=BBox(x, y, x + largeur, y + hauteur),  # bbox réelle, contrairement à Mistral
            confidence=m["confidence"],
            source="tesseract",
        ))
    return mots


class TesseractBackend(OcrBackend):
    name = "tesseract"

    def __init__(self, lang: str = "fra", dpi: int = 300):
        self.lang = lang
        self.dpi = dpi

    def ocraliser(self, doc: Document, pdf_path: str, pages: list = None, **kwargs) -> Document:
        source = fitz.open(pdf_path)
        scale = self.dpi / 72.0
        matrix = fitz.Matrix(scale, scale)

        try:
            for i, page_obj in enumerate(doc.pages):
                # Contrairement à Mistral, Tesseract tourne PAGE PAR PAGE --
                # `pages` est ici un VRAI filtre, pas juste indicatif.
                if pages is not None and page_obj.number not in pages:
                    continue

                pix = source[i].get_pixmap(matrix=matrix, alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))

                page_obj.ocr.engine = f"tesseract-{self.lang}"
                page_obj.ocr.words = _parser_image(image, self.lang, scale)  # ré-appel idempotent : remplace, n'accumule pas
        finally:
            source.close()

        return doc
