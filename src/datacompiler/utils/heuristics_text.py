"""heuristics_text.py — Signaux bas niveau partagés entre diagnostic/ et
resolve/confidence.py. Regroupés ici pour éviter la duplication (les deux
modules réimplémentaient indépendamment les mêmes patterns)."""


import re


# Caractères de contrôle / remplacement Unicode.
SUSPECT_PATTERN = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")


# Zone d'usage privé Unicode (BMP + plans 15/16) : symptôme classique d'une
# table ToUnicode manquante ou cassée -- le moteur retombe sur ces
# codepoints faute de mapping vers le vrai caractère. Signal fort, peu
# ambigu (contrairement aux heuristiques d'accents ASCII, abandonnées --
# trop de faux positifs).
PUA_PATTERN = re.compile(r"[\uE000-\uF8FF\U000F0000-\U000FFFFD\U00100000-\U0010FFFD]")


TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)




def chiffre_dans_mot(tok: str) -> bool:
    return any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)




def casse_irreguliere(tok: str) -> bool:
    return any(tok[i - 1].islower() and tok[i].isupper() for i in range(1, len(tok)))




def taux_caracteres_suspects(texte: str) -> float:
    if not texte:
        return 0.0
    suspects = len(SUSPECT_PATTERN.findall(texte)) + len(PUA_PATTERN.findall(texte))
    return suspects / len(texte)




def taux_tokens_anormaux(texte: str) -> float:
    tokens = TOKEN_PATTERN.findall(texte)
    if not tokens:
        return 0.0
    anormaux = [t for t in tokens if len(t) >= 2 and (chiffre_dans_mot(t) or casse_irreguliere(t))]
    return len(anormaux) / len(tokens)