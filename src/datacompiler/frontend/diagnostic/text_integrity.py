"""text_integrity.py — Qualité du texte natif reconstruit (mojibake,
tokens anormaux) et densité textuelle par page."""

from typing import Optional

from datacompiler.utils.heuristics_text import taux_caracteres_suspects, taux_tokens_anormaux


def texte_page(page) -> str:
    return " ".join(w.text for w in page.native.words)


def qualite_texte(texte: str) -> Optional[float]:
    if not texte:
        return None
    taux_suspect = taux_caracteres_suspects(texte)
    taux_tokens = taux_tokens_anormaux(texte)
    return max(0.0, 1.0 - taux_suspect * 5 - taux_tokens * 3)


# Seuil EMPIRIQUE, pas théorique -- à recalibrer avec vos tests. Base :
# une page A4 pleine de texte tourne autour de 450-800 mots (595x842pt).
SEUIL_DENSITE_BASSE = 0.003  # mots / pt²


def densite_texte(page) -> float:
    surface = page.width * page.height
    return len(page.native.words) / surface if surface else 0.0


def page_a_faible_densite(page) -> bool:
    """Signal FAIBLE isolément : une page de titre légitime a peu de mots
    aussi. À combiner côté orchestrateur avec l'absence d'image (sinon
    c'est juste `has_full_page_images` qui explique déjà le vide)."""
    return densite_texte(page) < SEUIL_DENSITE_BASSE

