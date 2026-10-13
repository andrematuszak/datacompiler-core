"""Add text-integrity signals not covered by basic control-character and token-shape checks, such as consistent character substitutions that still form plausible words."""

import re
from collections import Counter

from datacompiler.utils.heuristics_text import TOKEN_PATTERN

_MOTIF_NOMBRE_LETTRE = re.compile(r"\d[.,]\d{2}\s*([A-Za-z])\b")
_MOT_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")

SEUIL_MOTS_FIABLE = 30


def symboles_corrompus(texte: str, seuil_repetition: int = 2) -> dict:
    """Lettre isolée répétée après un montant décimal — signature d'un symbole
    (devise) mal mappé."""
    occurrences = Counter(m.group(1) for m in _MOTIF_NOMBRE_LETTRE.finditer(texte))
    return {lettre: n for lettre, n in occurrences.items() if n >= seuil_repetition}


def _trigrammes(mot: str):
    m = mot.lower()
    return [m[i:i + 3] for i in range(len(m) - 2)]


def mots_suspects_ngrammes(texte: str, longueur_min: int = 7, top_n: int = 20) -> list:
    """Rank candidate words that may contain character-level corruption using document-internal trigrams. This is a weak signal for human review, not an automatic verdict."""
    mots = _MOT_PATTERN.findall(texte)
    if not mots:
        return []

    compte_tri: Counter[str] = Counter()
    for m in mots:
        for tri in _trigrammes(m):
            compte_tri[tri] += 1
    total = sum(compte_tri.values())
    if not total:
        return []

    def score(mot):
        tris = _trigrammes(mot)
        return sum(compte_tri.get(t, 0) / total for t in tris) / len(tris)

    candidats = {m for m in mots if len(m) >= longueur_min}
    scores = sorted((score(m), m) for m in candidats)
    return scores[:top_n]


def qualite_avec_confiance(texte: str, qualite_brute) -> dict:
    """Augment an existing text-quality score with a confidence estimate based on the analyzed sample size."""
    nb_mots = len(TOKEN_PATTERN.findall(texte)) if texte else 0
    confiance_suffisante = nb_mots >= SEUIL_MOTS_FIABLE
    return {
        "nb_mots_analyses": nb_mots,
        "confiance_suffisante": confiance_suffisante,
        "qualite_brute": qualite_brute,
        "recommend_ocr_par_precaution": not confiance_suffisante,
    }
