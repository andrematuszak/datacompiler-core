"""blind_spots.py — Détections additives non couvertes par text_integrity.py
(mojibake, tokens anormaux) : substitution de caractère produisant un token
à forme normale (ex. € -> e, l -> t).
 — Détecte deux classes de corruption invisibles
à l'heuristique actuelle de diagnostic.py (SUSPECT_PATTERN/casse_irreguliere/
chiffre_dans_mot), qui ne voient que des caractères de contrôle ou une
structure de token anormale -- pas une substitution de caractère qui
produit un token à la forme parfaitement normale (bonne casse, pas de
chiffre, pas de caractère de contrôle).

Découvert sur test3 (€ -> e systématique) et test7 (l -> t systématique,
OCR tiers avec confusion de caractères visuellement proches).

Additif : ne modifie pas diagnostic.py, expose deux fonctions à appeler en
plus quand tu es prêt à les intégrer."""

import re
from collections import Counter

from datacompiler.heuristics import TOKEN_PATTERN

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
    """Candidats à corruption caractère-par-caractère via trigrammes internes
    au document. Signal faible — review humaine, pas verdict automatique."""
    mots = _MOT_PATTERN.findall(texte)
    if not mots:
        return []

    compte_tri = Counter()
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
    """Enrichit une qualité déjà calculée avec un indicateur de confiance lié
    à la taille de l'échantillon."""
    nb_mots = len(TOKEN_PATTERN.findall(texte)) if texte else 0
    confiance_suffisante = nb_mots >= SEUIL_MOTS_FIABLE
    return {
        "nb_mots_analyses": nb_mots,
        "confiance_suffisante": confiance_suffisante,
        "qualite_brute": qualite_brute,
        "recommend_ocr_par_precaution": not confiance_suffisante,
    }
