"""test_regression_word_count.py -- Vérifie que le PDF rendu contient
EXACTEMENT les mêmes mots que page.resolved.words, pas seulement le même
NOMBRE de mots.

Un simple comptage égal peut cacher un vrai décalage de contenu (X mots en
trop ET Y mots en moins qui se compensent par coïncidence) -- risque réel
identifié cette semaine : un premier passage montrait 302 vs 268 sans
qu'on sache lesquels étaient en cause avant de creuser à la main. Ce test
compare maintenant les MULTI-ENSEMBLES de tokens (Counter) et affiche le
détail des écarts en cas d'échec plutôt qu'un simple delta numérique.

LIMITE ASSUMÉE : ce test est insensible à l'ORDRE par construction (un
Counter ne voit pas les positions). Il confirme "mêmes mots présents",
PAS "dans le même ordre" -- reading_order.py peut encore diverger de
page.resolved.words sur l'ordre (cf. typography.normaliser et
alignment/conflict_resolution, qui s'exécutent après reading_order.py) et
ce test resterait vert malgré ça. Un test d'ordre est un sujet séparé, à
écrire une fois reading_order.py stabilisé -- ne pas le confondre avec
celui-ci.
"""

import json
from collections import Counter
from pathlib import Path

import pymupdf
import pytest


def _normaliser(mot: str) -> str:
    """Normalisation minimale avant comparaison -- les espaces en bord de
    mot ne doivent pas compter comme une vraie différence de contenu.

    Convertit aussi les soft hyphens (\\xad) en tirets (-) : pymupdf les
    produit lors de la lecture du PDF reconstruit (get_text("words")),
    alors que le JSON contient le tiret normal. C'est un artefact de
    lecture, pas une différence de contenu."""
    return mot.strip().replace("\xad", "-")


def _mots_json(resolved_words: list) -> list:
    """Extrait les tokens depuis resolved.words, éclatés sur les espaces.

    Un output_text avec un espace interne (mot composé reconstruit, ex.
    "CS 20009" stocké comme un seul Word) compte comme PLUSIEURS tokens
    une fois rendu et relu par pymupdf.get_text("words") -- éclater ici évite
    de comparer des granularités différentes des deux côtés, qui aurait
    pu être la cause du delta 302 vs 268 observé avant régénération."""
    mots = []
    for w in resolved_words:
        texte = (w.get("output_text") or w.get("text") or "").strip()
        mots.extend(t for t in texte.split() if t)
    return mots


def _trouver_mots_concernes(resolved_words, cible_tokens):
    """Retourne la liste des objets mots du JSON qui contribuent aux tokens cibles."""
    found = []
    # On crée un multi-ensemble des tokens cibles à consommer
    cibles_restants = Counter(cible_tokens)
    
    for w in resolved_words:
        texte = (w.get("output_text") or w.get("text") or "").strip()
        tokens = [t for t in texte.split() if t]
        
        # Vérifie si un des tokens de ce mot est dans la liste cible
        match = False
        for t in tokens:
            if cibles_restants.get(t, 0) > 0:
                match = True
                cibles_restants[t] -= 1
        
        if match:
            found.append(w)
            
    return found


def test_word_count_consistency():
    fixture_dir = Path(__file__).parent / "fixtures"
    pdf_propre = fixture_dir / "impots-revenu" / "impots-revenu_rebuilt.pdf"
    json_doc = fixture_dir / "impots-revenu" / "impots-revenu.document.json"

    if not pdf_propre.exists() or not json_doc.exists():
        pytest.skip("Fichiers de sortie manquants. Lancez d'abord le pipeline.")

    with open(json_doc, "r", encoding="utf-8") as f:
        doc_data = json.load(f)

    doc_pdf = pymupdf.open(pdf_propre)

    try:
        assert len(doc_pdf) == len(doc_data["pages"]), (
    f"Incohérence du nombre de pages : PDF={len(doc_pdf)} vs JSON={len(doc_data['pages'])}"
)

        echecs = []
        for i, page_data in enumerate(doc_data["pages"]):
            page_pdf = doc_pdf[i]

            resolved_words = page_data.get("resolved", {}).get("words", [])
            mots_json = _mots_json(resolved_words)
            mots_pdf = [_normaliser(w[4]) for w in page_pdf.get_text("words") if _normaliser(w[4])]

            compte_json = Counter(mots_json)
            compte_pdf = Counter(mots_pdf)

            en_trop_pdf = compte_pdf - compte_json    # dans le PDF, absents/en excès côté JSON
            manquants_pdf = compte_json - compte_pdf  # dans le JSON, absents/en défaut côté PDF

            if en_trop_pdf or manquants_pdf:
                detail = [f"Page {i + 1} : JSON={len(mots_json)} mots, PDF={len(mots_pdf)} mots"]
                
                # --- Analyse des mots EN TROP dans le PDF ---
                if en_trop_pdf:
                    detail.append(f"\n  En trop dans le PDF ({sum(en_trop_pdf.values())} occurrences) :")
                    detail.append(f"    Tokens: {dict(en_trop_pdf.most_common(15))}")
                    # On cherche les mots du JSON qui correspondent à ces tokens (pour voir leur source)
                    # Note: C'est contre-intuitif, mais on cherche dans le JSON les mots qui RESSEMBLENT
                    # à ceux en trop dans le PDF pour voir s'ils ont été mal marqués (ex: non reconstruits)
                    mots_json_en_trop = _trouver_mots_concernes(resolved_words, list(en_trop_pdf.elements()))
                    if mots_json_en_trop:
                        detail.append("    Exemples correspondants dans le JSON (Source/Reconstructed/Diff):")
                        for w in mots_json_en_trop[:5]: # Limite à 5 exemples
                            out_txt = w.get("resolved_text") or w.get("replacement") or w.get("text") or ""
                            txt = w.get("text", "")
                            is_diff = "OUI" if out_txt != txt else "NON"
                            detail.append(f"      - '{out_txt}' | Source: {w.get('source')} | Reconstructed: {w.get('reconstructed')} | Output!=Text: {is_diff}")

                # --- Analyse des mots MANQUANTS dans le PDF ---
                if manquants_pdf:
                    detail.append(f"\n  Manquants dans le PDF ({sum(manquants_pdf.values())} occurrences) :")
                    detail.append(f"    Tokens: {dict(manquants_pdf.most_common(15))}")
                    mots_json_manquants = _trouver_mots_concernes(resolved_words, list(manquants_pdf.elements()))
                    if mots_json_manquants:
                        detail.append("    Exemples correspondants dans le JSON (Source/Reconstructed/Diff):")
                        for w in mots_json_manquants[:5]: # Limite à 5 exemples
                            out_txt = w.get("output_text", "")
                            txt = w.get("text", "")
                            is_diff = "OUI" if out_txt != txt else "NON"
                            detail.append(f"      - '{out_txt}' | Source: {w.get('source')} | Reconstructed: {w.get('reconstructed')} | Output!=Text: {is_diff}")
                
                echecs.append("\n".join(detail))

        if echecs:
            pytest.fail("Contenu incohérent entre JSON et PDF (compte peut-être identique, "
                        "mots différents) :\n\n" + "\n\n".join(echecs))
    finally:
        doc_pdf.close()
        

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
