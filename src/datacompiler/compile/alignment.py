"""alignment.py — Aligne les mots natifs et les mots OCR d'une page.

Contrainte structurelle (cf. ocr.py) : Mistral ne fournit de bbox qu'au
niveau BLOC (paragraphe), jamais au niveau mot -- page.ocr.words n'a que
texte + confiance, bbox=None. L'alignement géométrique précis mot-à-mot est
donc IMPOSSIBLE avec les données actuelles. On aligne à la place les deux
SÉQUENCES DE TEXTE (natif et OCR) comme deux versions du même document,
avec difflib -- l'équivalent d'un diff de texte, pas d'un rapprochement
spatial.

Prérequis : `mots_natifs` doit déjà être dans l'ordre de lecture réel
(reading_order.py) et normalisé côté typographie (typography.py), sinon le
diff n'a aucune raison de s'aligner correctement avec l'ordre dans lequel
Mistral retourne son propre flux de mots.
"""

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
    """Retourne une liste de UniteAlignement décrivant la correspondance
    entre les deux séquences."""
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
