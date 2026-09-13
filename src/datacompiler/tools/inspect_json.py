"""diagnostic_json.py — Script de diagnostic en LECTURE SEULE d'un
document.json produit par datacompiler/pipeline.py.

Objectif : distinguer, pour une page donnée, entre les scénarios de
duplication/mauvais positionnement discutés :

  A. Deux zones vectorielles voisines qui auraient dû fusionner (bug de
     _grouper_par_proximite dans vector_text.py) -> deux jeux de mots
     source="ocr_vectoriel" au texte identique/proche, bbox qui se
     chevauchent, sans mot natif entre les deux.
  B. Une zone OCRisée qui chevauche du texte natif déjà présent
     (_mot_natif_present a raté ce mot, ou test au centre insuffisant)
     -> mots "ocr_vectoriel" et mots natifs au même endroit.
  C. Doublon réel dans le PDF source (volet dupliqué) -> deux occurrences
     du même texte à des positions clairement DIFFÉRENTES, non superposées.

  D. (nouveau) Un mot dont la bbox elle-même semble fausse (loin de tout
     voisin textuel cohérent) -> à distinguer d'un simple problème d'ORDRE
     de lecture sur une bbox correcte. La sous-commande `chercher` donne le
     contexte pour trancher visuellement, à comparer au PDF source.

Ne dépend d'aucun module datacompiler, ne modifie rien -- lit uniquement
le JSON déjà produit par pipeline.py (`<nom>.document.json`).

USAGE
-----
Lister les chevauchements de bbox sur une page :
    python diagnostic_json.py chevauchements fichier.document.json --page 1

Chercher où un texte précis apparaît sur la page (bbox + contexte d'ordre
de sortie) -- utile pour vérifier si un texte "mal placé" a vraiment une
bbox fausse, ou si c'est l'ORDRE de lecture qui est en cause :
    python diagnostic_json.py chercher fichier.document.json --page 1 --texte "GENERALE"
"""

import argparse
import json
from itertools import combinations


def _charger_mots(doc, page_number):
    """Retourne (mots, chemin_utilisé, page_dict) pour la page demandée.
    Essaie plusieurs emplacements possibles selon la structure réelle du
    JSON (resolved.words en priorité -- c'est l'ordre final utilisé pour la
    sortie texte -- puis native.words en repli)."""
    for page in doc.get("pages", []):
        if page.get("number") != page_number:
            continue
        for chemin in (("resolved", "words"), ("native", "words"), ("words",)):
            courant = page
            ok = True
            for cle in chemin:
                if isinstance(courant, dict) and cle in courant:
                    courant = courant[cle]
                else:
                    ok = False
                    break
            if ok and isinstance(courant, list) and courant:
                return courant, ".".join(chemin), page
        return [], None, page
    return [], None, None


def _bbox(word):
    b = word.get("bbox")
    if not b:
        return None
    if isinstance(b, dict):
        return b["x0"], b["y0"], b["x1"], b["y1"]
    return tuple(b[:4])


def _chevauche(a, b, marge=0.0):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 + marge <= bx0 or bx1 + marge <= ax0
                or ay1 + marge <= by0 or by1 + marge <= ay0)


def cmd_chevauchements(args):
    with open(args.json_path, encoding="utf-8") as f:
        doc = json.load(f)

    mots_bruts, chemin, page = _charger_mots(doc, args.page)
    if not mots_bruts:
        print(f"Aucun mot trouvé pour la page {args.page}.")
        return
    print(f"Page {args.page} — {len(mots_bruts)} mots (`{chemin}`), "
          f"taille page = {page.get('width')}x{page.get('height')} pt\n")

    mots = []
    for i, w in enumerate(mots_bruts):
        bbox = _bbox(w)
        if not bbox:
            continue
        mots.append({
            "bbox": bbox,
            "text": (w.get("text") or "").strip(),
            "source": w.get("source", "?"),
            "reconstructed": w.get("reconstructed", False),
            "idx": i,
        })

    paires = []
    for a, b in combinations(mots, 2):
        ta, tb = a["text"].lower(), b["text"].lower()
        if not ta or not tb:
            continue
        # texte identique, ou l'un contenu dans l'autre (utile pour capter
        # les fragments type "Date"/"ate" du phénomène 2)
        proche_texte = ta == tb or ta in tb or tb in ta
        if proche_texte and _chevauche(a["bbox"], b["bbox"], args.marge):
            paires.append((a, b))

    if not paires:
        print("Aucun chevauchement détecté avec cette marge/ces critères "
              f"(--marge {args.marge}). Essayez une marge plus grande.")
        return

    print(f"{len(paires)} paire(s) en chevauchement :\n")
    for a, b in paires:
        if a["source"] == b["source"] == "ocr_vectoriel":
            scenario = "A — zones vectorielles non fusionnées (_grouper_par_proximite)"
        elif "ocr_vectoriel" in (a["source"], b["source"]) and a["source"] != b["source"]:
            scenario = "B — zone OCR chevauche du texte natif (_mot_natif_present)"
        else:
            scenario = f"? sources={a['source']!r}/{b['source']!r} -- à examiner"

        print(f'  "{a["text"]}"  vs  "{b["text"]}"')
        print(f"    #{a['idx']:>4} source={a['source']:<14} reconstructed={str(a['reconstructed']):<5} bbox={tuple(round(v, 1) for v in a['bbox'])}")
        print(f"    #{b['idx']:>4} source={b['source']:<14} reconstructed={str(b['reconstructed']):<5} bbox={tuple(round(v, 1) for v in b['bbox'])}")
        print(f"    -> {scenario}\n")


def cmd_chercher(args):
    with open(args.json_path, encoding="utf-8") as f:
        doc = json.load(f)

    mots_bruts, chemin, page = _charger_mots(doc, args.page)
    if not mots_bruts:
        print(f"Aucun mot trouvé pour la page {args.page}.")
        return
    hauteur_page = page.get("height")
    print(f"Page {args.page} — recherche de {args.texte!r} dans `{chemin}` "
          f"(hauteur de page = {hauteur_page} pt ; y0 petit = haut de page, "
          f"y0 proche de {hauteur_page} = bas de page)\n")

    trouves = [
        (i, w) for i, w in enumerate(mots_bruts)
        if args.texte.lower() in (w.get("text") or "").lower()
    ]
    if not trouves:
        print("Aucune occurrence trouvée.")
        return

    for i, w in trouves:
        bbox = _bbox(w)
        print(f'  #{i:>4} "{w.get("text")}"')
        print(f"       source={w.get('source')!r} reconstructed={w.get('reconstructed', False)}")
        print(f"       bbox={tuple(round(v, 1) for v in bbox) if bbox else None}")
        # Contexte : les 2 mots juste avant/après dans l'ORDRE de la liste --
        # utile pour voir si le voisinage textuel a du sens (ordre/position
        # correcte) ou si ce mot est "collé" à un contenu physiquement sans
        # rapport (symptôme d'un bug d'ordre de lecture OU de bbox fausse --
        # comparer la bbox affichée à la position réelle dans le PDF source
        # permet de trancher entre les deux).
        avant = mots_bruts[max(0, i - 2):i]
        apres = mots_bruts[i + 1:i + 3]
        contexte_avant = " / ".join((m.get("text") or "").strip() for m in avant)
        contexte_apres = " / ".join((m.get("text") or "").strip() for m in apres)
        print(f"       contexte (ordre de sortie) : ... {contexte_avant} [{w.get('text')}] {contexte_apres} ...\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = parser.add_subparsers(dest="commande", required=True)

    p1 = sous.add_parser("chevauchements", help="Liste les mots dont les bbox se chevauchent sur une page")
    p1.add_argument("json_path")
    p1.add_argument("--page", type=int, default=1)
    p1.add_argument("--marge", type=float, default=1.0, help="Tolérance en pt (défaut : 1.0)")
    p1.set_defaults(func=cmd_chevauchements)

    p2 = sous.add_parser("chercher", help="Cherche un texte précis et affiche bbox + contexte d'ordre de sortie")
    p2.add_argument("json_path")
    p2.add_argument("--page", type=int, default=1)
    p2.add_argument("--texte", required=True)
    p2.set_defaults(func=cmd_chercher)

    args = parser.parse_args()
    args.func(args)
