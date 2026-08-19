"""Sonde légère de texte bitmap pendant l'extraction PDF.

Le diagnostic ne relit jamais le fichier PDF. Cette sonde reçoit donc les
pixels des images tant que PyMuPDF garde le document ouvert, puis son résultat
est conservé dans ``ImageElement.contains_text``.
"""

from __future__ import annotations

import io
from typing import Optional

import pymupdf

SEUIL_CONFIANCE_MIN = 0.4
TAILLE_MAX_SOUS_ECHANTILLONNAGE = 1500


def contient_probablement_du_texte(image_bytes: bytes, lang: str = "eng") -> Optional[bool]:
    """Retourne un signal texte oui/non, ou ``None`` si la sonde est indisponible.

    Une seule passe Tesseract ``sparse text`` est volontairement utilisée :
    ce n'est pas l'OCR de production, seulement un triage peu coûteux.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            image = source.convert("RGB")
            if max(image.size) > TAILLE_MAX_SOUS_ECHANTILLONNAGE:
                ratio = TAILLE_MAX_SOUS_ECHANTILLONNAGE / max(image.size)
                image = image.resize((round(image.width * ratio), round(image.height * ratio)))
            donnees = pytesseract.image_to_data(
                image,
                lang=lang,
                config="--psm 11",
                output_type=pytesseract.Output.DICT,
            )
    except (OSError, RuntimeError, pytesseract.TesseractError):
        # Binaire Tesseract absent, image non décodable ou langue absente :
        # inconnu, jamais un faux négatif.
        return None

    for texte, confiance in zip(donnees["text"], donnees["conf"]):
        try:
            confiance = float(confiance) / 100.0
        except (TypeError, ValueError):
            continue
        if texte.strip() and confiance >= SEUIL_CONFIANCE_MIN:
            return True
    return False


def sonder_images_page(document: pymupdf.Document, page: pymupdf.Page, lang: str = "eng") -> list[tuple[pymupdf.Rect, Optional[bool]]]:
    """Associe chaque placement d'image de ``page`` à son signal texte."""
    resultats = []
    signaux_par_xref = {}
    for image in page.get_images(full=True):
        xref = image[0]
        if xref not in signaux_par_xref:
            try:
                signaux_par_xref[xref] = contient_probablement_du_texte(document.extract_image(xref)["image"], lang)
            except (KeyError, ValueError, RuntimeError):
                signaux_par_xref[xref] = None
        resultats.extend((rect, signaux_par_xref[xref]) for rect in page.get_image_rects(xref))
    return resultats
