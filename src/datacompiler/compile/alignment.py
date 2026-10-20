"""Align native and OCR text sequences at the block level. The OCR provider may not supply word bounding boxes, so geometric word-to-word alignment is unavailable; sequence matching is used instead."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from datacompiler.model.document import Word


@dataclass
class UniteAlignement:
    native: Optional[Word]
    ocr: Optional[Word]
    type: str  # "equal" | "conflit" | "natif_seul" | "ocr_seul"


def aligner(mots_natifs: list, mots_ocr: list) -> list:
    """Return alignment units describing the correspondence between native and OCR text sequences."""
    textes_natifs = [w.output_text for w in mots_natifs]
    textes_ocr = [w.text for w in mots_ocr]

    # autojunk=False : par défaut SequenceMatcher traite comme "junk" tout
    # élément apparaissant dans plus de 1% d'une séquence de plus de 200
    # éléments -- pertinent pour du texte naturel (mots très fréquents comme
    # "de", "le"), pas pour ce cas d'usage où CHAQUE occurrence compte pour
    # la fidélité du document.
    matcher = SequenceMatcher(a=textes_natifs, b=textes_ocr, autojunk=False)
    unites = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                unites.append(UniteAlignement(mots_natifs[i], mots_ocr[j], "equal"))

        elif tag == "replace":
            # Appariement positionnel sur le chevauchement des deux blocs ;
            # le surplus de chaque côté (si les deux blocs n'ont pas la même
            # longueur) part en natif_seul / ocr_seul plutôt que d'être
            # apparié arbitrairement.
            n = min(i2 - i1, j2 - j1)
            for k in range(n):
                unites.append(UniteAlignement(mots_natifs[i1 + k], mots_ocr[j1 + k], "conflit"))
            for i in range(i1 + n, i2):
                unites.append(UniteAlignement(mots_natifs[i], None, "natif_seul"))
            for j in range(j1 + n, j2):
                unites.append(UniteAlignement(None, mots_ocr[j], "ocr_seul"))

        elif tag == "delete":
            for i in range(i1, i2):
                unites.append(UniteAlignement(mots_natifs[i], None, "natif_seul"))

        elif tag == "insert":
            for j in range(j1, j2):
                unites.append(UniteAlignement(None, mots_ocr[j], "ocr_seul"))

    return unites
