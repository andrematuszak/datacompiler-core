#!/usr/bin/env python3
"""diagnostic_json.py — Outil d'inspection du document.json produit par le
pipeline DataCompiler (page.resolved.words, essentiellement).

Le JSON est le vrai produit du pipeline (le "coeur" du projet) -- ce script
sert à l'explorer sans avoir à le charger à la main dans un REPL à chaque
fois, ni à faire confiance à l'affichage d'un lecteur PDF tiers (qui peut
réordonner ou fusionner du texte silencieusement -- cf. l'épisode
Aperçu/Live Text qui a fait perdre du temps à identifier un faux bug).

Lecture seule : ne modifie JAMAIS le fichier .document.json.

Toutes les commandes lisent `resolved.words` par défaut (le texte final,
post-compilation, dans l'ordre de sortie réel) sauf mention contraire. Les
pages sont 1-indexées dans les options --page, comme le reste du projet.

USAGE
=====

Résumé global ou par page (sources, confiance, flags qa.py) :
    python diagnostic_json.py resume doc.json
    python diagnostic_json.py resume doc.json --page 1

Recherche de texte (sous-chaîne, insensible à la casse, MOT PAR MOT --
"revenus de 2020" ne matchera jamais rien puisque ce sont 3 Word séparés ;
chercher un seul token à la fois) :
    python diagnostic_json.py chercher doc.json --texte KENNEDY
    python diagnostic_json.py chercher doc.json --texte KENNEDY --page 1
    python diagnostic_json.py chercher doc.json --source ocr_vectoriel
    python diagnostic_json.py chercher doc.json --flag confiance_basse

Lister les mots signalés par compile/qa.py :
    python diagnostic_json.py flags doc.json
    python diagnostic_json.py flags doc.json --severity warning
    python diagnostic_json.py flags doc.json --type confiance_basse

Contexte autour d'un mot précis, par id, DANS L'ORDRE DE SORTIE RÉEL --
utile pour inspecter une zone suspecte (ex. un bloc mal espacé ou mal
ordonné) sans dépendre d'un lecteur PDF :
    python diagnostic_json.py contexte doc.json --page 1 --id 42
    python diagnostic_json.py contexte doc.json --page 1 --id 42 --fenetre 10

Texte brut dans l'ordre de sortie (ce qu'un traducteur verrait) :
    python diagnostic_json.py texte doc.json --page 1

Répartition par source, avec confiance moyenne et taux de reconstruction :
    python diagnostic_json.py sources doc.json

Comparaison de deux exports JSON -- utile en régression, avant/après un
correctif (ex. vérifier qu'un correctif ne fait pas exploser le nombre de
mots d'une page, ou déplacer une source vers une autre) :
    python diagnostic_json.py comparer avant.json apres.json
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Chargement et utilitaires bas niveau
# ---------------------------------------------------------------------------

def charger(chemin: str) -> dict:
    path = Path(chemin)
    if not path.exists():
        sys.exit(f"Fichier introuvable : {chemin}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def texte_affiche(mot: dict) -> str:
    """Reproduit Word.output_text (property Python, absente du JSON brut) :
    resolved_text, sinon replacement, sinon text."""
    return mot.get("resolved_text") or mot.get("replacement") or mot.get("text") or ""


def bbox_str(mot: dict) -> str:
    b = mot.get("bbox")
    if not b:
        return "bbox=None"
    return f"bbox=({b['x0']:.1f}, {b['y0']:.1f}, {b['x1']:.1f}, {b['y1']:.1f})"


def flags_str(mot: dict) -> str:
    flags = mot.get("flags") or []
    if not flags:
        return ""
    return "flags=[" + ", ".join(f"{f.get('type')}:{f.get('severity')}" for f in flags) + "]"


def pages_selectionnees(doc: dict, page_arg):
    """Retourne [(numero_1_indexe, page_dict), ...] -- toutes les pages si
    page_arg est None, sinon une seule page. Erreur claire si la page
    demandée n'existe pas, plutôt qu'une liste vide silencieuse."""
    pages = doc.get("pages", [])
    if page_arg is None:
        return list(enumerate(pages, start=1))
    if page_arg < 1 or page_arg > len(pages):
        sys.exit(f"Page {page_arg} hors limites (document de {len(pages)} pages).")
    return [(page_arg, pages[page_arg - 1])]


# ---------------------------------------------------------------------------
# Commande : resume
# ---------------------------------------------------------------------------

def cmd_resume(args):
    doc = charger(args.fichier)
    for num, page in pages_selectionnees(doc, args.page):
        mots = page.get("resolved", {}).get("words", [])
        par_source = Counter(m.get("source") or "native" for m in mots)
        reconstruits = sum(1 for m in mots if m.get("reconstructed"))
        corriges = sum(1 for m in mots if m.get("is_corrected"))
        vectorises = sum(1 for m in mots if m.get("is_vectorized"))
        sans_bbox = sum(1 for m in mots if not m.get("bbox"))
        confiances = [m["confidence"] for m in mots if m.get("confidence") is not None]
        toutes_flags = [f for m in mots for f in (m.get("flags") or [])]
        flags_par_type = Counter(f.get("type") for f in toutes_flags)

        print(f"=== Page {num} ===")
        print(f"  Mots (resolved.words)     : {len(mots)}")
        print(f"  Par source                : {dict(par_source)}")
        print(f"  Reconstructed             : {reconstruits}")
        print(f"  Corrigés (is_corrected)   : {corriges}")
        print(f"  Vectorisés                : {vectorises}")
        print(f"  Sans bbox (non positionné): {sans_bbox}")
        if confiances:
            print(f"  Confiance : min={min(confiances):.2f} "
                  f"moy={sum(confiances)/len(confiances):.2f} max={max(confiances):.2f} "
                  f"(sur {len(confiances)}/{len(mots)} mots avec confidence renseignée)")
        else:
            print("  Confiance : aucun mot avec confidence renseignée")
        if toutes_flags:
            print(f"  Flags (qa.py)             : {dict(flags_par_type)} "
                  f"({len(toutes_flags)} au total)")
        else:
            print("  Flags (qa.py)             : aucun")

        diag = page.get("diagnostic")
        if diag:
            interessant = {k: v for k, v in diag.items() if v not in (None, "", [], {})}
            if interessant:
                print("  page.diagnostic (brut) :")
                for k, v in interessant.items():
                    print(f"    {k} = {v}")
        print()


# ---------------------------------------------------------------------------
# Commande : chercher
# ---------------------------------------------------------------------------

def cmd_chercher(args):
    doc = charger(args.fichier)
    trouves = 0

    for num, page in pages_selectionnees(doc, args.page):
        mots = page.get("resolved", {}).get("words", [])

        for i, mot in enumerate(mots):
            if args.reconstructed and not mot.get("reconstructed"):
                continue
            if args.texte and args.texte.lower() not in texte_affiche(mot).lower():
                continue
            if args.source and (mot.get("source") or "native") != args.source:
                continue
            if args.flag and args.flag not in [f.get("type") for f in (mot.get("flags") or [])]:
                continue

            trouves += 1
            if args.limite and trouves > args.limite:
                print(f"... (limite de {args.limite} atteinte -- utilisez --limite 0 pour tout voir)")
                return

            avant = texte_affiche(mots[i - 1]) if i > 0 else "…"
            apres = texte_affiche(mots[i + 1]) if i + 1 < len(mots) else "…"
            print(f"Page {num} #{i:4d} \"{texte_affiche(mot)}\"")
            print(f"       {bbox_str(mot)}  source={mot.get('source')}  "
                  f"reconstructed={mot.get('reconstructed')}  "
                  f"confidence={mot.get('confidence')}")
            extra = flags_str(mot)
            if extra:
                print(f"       {extra}")
            print(f"       contexte (ordre de sortie) : ... {avant} [{texte_affiche(mot)}] {apres} ...")

    if trouves == 0:
        print("Aucune occurrence trouvée.")


# ---------------------------------------------------------------------------
# Commande : flags
# ---------------------------------------------------------------------------

def cmd_flags(args):
    doc = charger(args.fichier)
    trouves = 0

    for num, page in pages_selectionnees(doc, args.page):
        mots = page.get("resolved", {}).get("words", [])
        for i, mot in enumerate(mots):
            flags = mot.get("flags") or []
            if args.severity:
                flags = [f for f in flags if f.get("severity") == args.severity]
            if args.type:
                flags = [f for f in flags if f.get("type") == args.type]
            if not flags:
                continue

            trouves += 1
            print(f"Page {num} #{i:4d} \"{texte_affiche(mot)}\"  {bbox_str(mot)}")
            for f in flags:
                print(f"       [{f.get('severity')}] {f.get('type')} -- {f.get('detail')}")

    if trouves == 0:
        print("Aucun mot signalé (avec ces filtres).")
    else:
        print(f"\n{trouves} mot(s) signalé(s).")


# ---------------------------------------------------------------------------
# Commande : contexte
# ---------------------------------------------------------------------------

def cmd_contexte(args):
    doc = charger(args.fichier)
    _, page = pages_selectionnees(doc, args.page)[0]
    mots = page.get("resolved", {}).get("words", [])

    index = next((i for i, m in enumerate(mots) if m.get("id") == args.id), None)
    if index is None:
        sys.exit(f"Aucun mot avec id={args.id} sur la page {args.page}.")

    debut = max(0, index - args.fenetre)
    fin = min(len(mots), index + args.fenetre + 1)

    print(f"Contexte autour du mot id={args.id} (page {args.page}, "
          f"fenêtre de {args.fenetre} mots de chaque côté) :\n")
    for i in range(debut, fin):
        marqueur = ">>> " if i == index else "    "
        m = mots[i]
        print(f"{marqueur}#{i:4d} \"{texte_affiche(m)}\"  {bbox_str(m)}  "
              f"source={m.get('source')}  {flags_str(m)}")

    print("\nTexte concaténé de la fenêtre :")
    print(" ".join(texte_affiche(mots[i]) for i in range(debut, fin)))


# ---------------------------------------------------------------------------
# Commande : texte
# ---------------------------------------------------------------------------

def cmd_texte(args):
    doc = charger(args.fichier)
    for num, page in pages_selectionnees(doc, args.page):
        mots = page.get("resolved", {}).get("words", [])
        print(f"--- Page {num} ({len(mots)} mots) ---")
        print(" ".join(texte_affiche(m) for m in mots))
        print()


# ---------------------------------------------------------------------------
# Commande : sources
# ---------------------------------------------------------------------------

def _bucket():
    return {"n": 0, "reconstructed": 0, "corrected": 0, "conf": []}


def cmd_sources(args):
    doc = charger(args.fichier)
    global_stats = defaultdict(_bucket)

    for num, page in pages_selectionnees(doc, args.page):
        mots = page.get("resolved", {}).get("words", [])
        stats = defaultdict(_bucket)
        for m in mots:
            src = m.get("source") or "native"
            for bucket in (stats[src], global_stats[src]):
                bucket["n"] += 1
                bucket["reconstructed"] += int(bool(m.get("reconstructed")))
                bucket["corrected"] += int(bool(m.get("is_corrected")))
                if m.get("confidence") is not None:
                    bucket["conf"].append(m["confidence"])

        print(f"=== Page {num} ===")
        _afficher_table_sources(stats)
        print()

    if args.page is None and len(doc.get("pages", [])) > 1:
        print("=== Document entier ===")
        _afficher_table_sources(global_stats)


def _afficher_table_sources(stats: dict):
    print(f"  {'source':<16} {'n':>6} {'reconstructed':>14} {'corrigés':>10} {'conf. moy.':>11}")
    for src, s in sorted(stats.items(), key=lambda kv: -kv[1]["n"]):
        conf_moy = f"{sum(s['conf'])/len(s['conf']):.2f}" if s["conf"] else "—"
        print(f"  {src:<16} {s['n']:>6} {s['reconstructed']:>14} {s['corrected']:>10} {conf_moy:>11}")


# ---------------------------------------------------------------------------
# Commande : comparer
# ---------------------------------------------------------------------------

def cmd_comparer(args):
    doc_a = charger(args.fichier_a)
    doc_b = charger(args.fichier_b)
    pages_a = doc_a.get("pages", [])
    pages_b = doc_b.get("pages", [])

    if len(pages_a) != len(pages_b):
        print(f"ATTENTION : nombre de pages différent ({len(pages_a)} vs {len(pages_b)})")

    print(f"{'Page':<6} {'mots A':>8} {'mots B':>8} {'écart':>8}  détail par source (A -> B)")
    for i in range(max(len(pages_a), len(pages_b))):
        mots_a = pages_a[i].get("resolved", {}).get("words", []) if i < len(pages_a) else []
        mots_b = pages_b[i].get("resolved", {}).get("words", []) if i < len(pages_b) else []
        src_a = Counter(m.get("source") or "native" for m in mots_a)
        src_b = Counter(m.get("source") or "native" for m in mots_b)
        toutes_sources = sorted(set(src_a) | set(src_b))
        detail = ", ".join(f"{s}: {src_a.get(s, 0)}->{src_b.get(s, 0)}" for s in toutes_sources)
        ecart = len(mots_b) - len(mots_a)
        signe = f"+{ecart}" if ecart > 0 else str(ecart)
        print(f"{i+1:<6} {len(mots_a):>8} {len(mots_b):>8} {signe:>8}  {detail}")


# ---------------------------------------------------------------------------
# Commande : valider
# ---------------------------------------------------------------------------

def cmd_valider(args):
    doc = charger(args.fichier)
    erreurs = []
    for num, page in pages_selectionnees(doc, args.page):
        mots = page.get("resolved", {}).get("words", [])
        ids = [m.get("id") for m in mots]
        if len(set(ids)) != len(ids):
            erreurs.append(f"Page {num} : ids dupliqués dans resolved.words")
        for m in mots:
            for f in (m.get("flags") or []):
                for lie_id in (f.get("lie_a") or []):
                    if lie_id not in ids:
                        erreurs.append(f"Page {num} #{m.get('id')} : flag lié à id={lie_id} introuvable")
    if erreurs:
        for e in erreurs:
            print(f"ERREUR : {e}")
        sys.exit(1)
    print("OK -- aucune incohérence structurelle détectée.")


# ---------------------------------------------------------------------------
# Commande : confiance
# ---------------------------------------------------------------------------

def cmd_confiance(args):
    doc = charger(args.fichier)
    par_source = defaultdict(list)
    for num, page in pages_selectionnees(doc, args.page):
        for m in page.get("resolved", {}).get("words", []):
            if m.get("confidence") is not None:
                par_source[m.get("source") or "native"].append(m["confidence"])

    tranches = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.85), (0.85, 1.01)]
    for src, valeurs in sorted(par_source.items(), key=lambda kv: -len(kv[1])):
        print(f"=== {src} ({len(valeurs)} mots avec confidence) ===")
        for lo, hi in tranches:
            n = sum(1 for v in valeurs if lo <= v < hi)
            barre = "█" * min(n, 50)
            print(f"  [{lo:.2f}-{hi:.2f}) {n:>4}  {barre}")
        print()

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Inspection du document.json produit par le pipeline DataCompiler.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sous = parser.add_subparsers(dest="commande", required=True)

    p = sous.add_parser("resume", help="Statistiques par page (sources, confiance, flags).")
    p.add_argument("fichier")
    p.add_argument("--page", type=int, default=None, help="1-indexé ; toutes les pages si omis.")
    p.set_defaults(func=cmd_resume)

    p = sous.add_parser("chercher", help="Recherche de texte dans resolved.words.")
    p.add_argument("fichier")
    p.add_argument("--reconstructed", action="store_true", help="Afficher uniquement les mots avec reconstructed=True.")
    p.add_argument("--texte", default="", help="Sous-chaîne recherchée (insensible à la casse).")
    p.add_argument("--page", type=int, default=None)
    p.add_argument("--source", default=None, help="Filtre exact, ex. ocr_vectoriel, native.")
    p.add_argument("--flag", default=None, help="Filtre par type de flag présent sur le mot.")
    p.add_argument("--limite", type=int, default=50, help="0 pour désactiver la limite.")
    p.set_defaults(func=cmd_chercher)

    p = sous.add_parser("flags", help="Liste les mots portant un flag qa.py.")
    p.add_argument("fichier")
    p.add_argument("--page", type=int, default=None)
    p.add_argument("--severity", default=None, choices=["info", "warning", "critical"])
    p.add_argument("--type", default=None)
    p.set_defaults(func=cmd_flags)

    p = sous.add_parser("contexte", help="Mots autour d'un id précis, dans l'ordre de sortie.")
    p.add_argument("fichier")
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--fenetre", type=int, default=5)
    p.set_defaults(func=cmd_contexte)

    p = sous.add_parser("texte", help="Texte brut dans l'ordre de sortie (resolved.words).")
    p.add_argument("fichier")
    p.add_argument("--page", type=int, default=None)
    p.set_defaults(func=cmd_texte)

    p = sous.add_parser("sources", help="Répartition des mots par source, avec confiance moyenne.")
    p.add_argument("fichier")
    p.add_argument("--page", type=int, default=None)
    p.set_defaults(func=cmd_sources)

    p = sous.add_parser("comparer", help="Compare deux exports JSON (régression avant/après).")
    p.add_argument("fichier_a")
    p.add_argument("fichier_b")
    p.set_defaults(func=cmd_comparer)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
