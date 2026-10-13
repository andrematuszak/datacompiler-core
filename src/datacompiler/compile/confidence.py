"""Estimate native-word confidence on a shared 0-to-1 scale so conflict resolution can compare native and OCR candidates using common text-integrity signals."""


from datacompiler.utils.heuristics_text import taux_caracteres_suspects, chiffre_dans_mot, casse_irreguliere


CONFIANCE_OCR_PAR_DEFAUT = 0.5
ECART_SIGNIFICATIF = 0.15




def confiance_native(word) -> float:
    """Estimate heuristic confidence for one native PyMuPDF word."""
    texte = word.text
    if not texte:
        return 0.0


    score = 1.0
    if taux_caracteres_suspects(texte) > 0:
        score -= 0.6
    if len(texte) >= 2 and (chiffre_dans_mot(texte) or casse_irreguliere(texte)):
        score -= 0.3


    return max(0.0, score)




def confiance_ocr(word) -> float:
    if word.confidence is not None:
        return max(0.0, min(1.0, word.confidence))
    return CONFIANCE_OCR_PAR_DEFAUT




def meilleur(confiance_a: float, confiance_b: float):
    ecart = abs(confiance_a - confiance_b)
    a_gagne = confiance_a >= confiance_b
    confiance_gagnante = confiance_a if a_gagne else confiance_b
    return a_gagne, confiance_gagnante, ecart >= ECART_SIGNIFICATIF