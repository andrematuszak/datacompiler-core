"""diagnostic_zones_reelles.py — Calcule les zones de texte vectorisé
RÉELLEMENT utilisées par le pipeline (détection vector_text.py + marge +
fusion vector_zones.py), pour trouver la bbox EXACTE envoyée à l'OCR --
au lieu de la deviner à la main comme dans diagnostic_ocr_zone.py
jusqu'ici, ce qui a raté deux fois de suite (zone de sortie != zone
d'entrée, car _fusionner_zones_chevauchantes peut agrandir/fusionner
plusieurs détections en un seul rectangle).

Réutilise le code de production tel quel (import direct), donc les zones
imprimées sont garanties identiques à ce que voit réellement Tesseract en
pipeline -- pas une approximation.

Usage :
    python diagnostic_zones_reelles.py test-impots-revenu.pdf --page 0

Marque automatiquement la zone qui contient la bbox de sortie du mot
"Pavis" (80.4, 215.7, 102.0, 222.2), pour l'identifier sans avoir à
comparer les chiffres à l'oeil.
"""

import argparse

from datacompiler.frontend.extract import extraire
from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.frontend.ocr.vector_zones import _fusionner_zones_chevauchantes, MARGE_ZONE
from datacompiler.model.document import BBox, Document

# bbox de SORTIE du mot "Pavis" (Page 1 #65, cf. diagnostic_json.py chercher) --
# sert uniquement à repérer quelle zone finale l'englobe, pas à la retester directement.
_BBOX_SORTIE_PAVIS = (80.4, 215.7, 102.0, 222.2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--page", type=int, required=True, help="index de page (0-based, comme fitz)")
    args = parser.parse_args()

    print("Extraction du document (peut prendre quelques secondes)...")
    doc = extraire(Document(), args.pdf)
    page = doc.pages[args.page]

    zones = zones_texte_vectorise_probable(page)
    print(f"\n{len(zones)} zone(s) brute(s) détectée(s) par vector_text.py :")
    for z in zones:
        print(f"  brute  : {z}")

    zones_marginees = [
        BBox(x0 - MARGE_ZONE, y0 - MARGE_ZONE, x1 + MARGE_ZONE, y1 + MARGE_ZONE)
        for x0, y0, x1, y1 in zones
    ]
    zones_finales = _fusionner_zones_chevauchantes(zones_marginees)

    px0, py0, px1, py1 = _BBOX_SORTIE_PAVIS
    print(f"\n{len(zones_finales)} zone(s) finale(s) après marge (+{MARGE_ZONE}pt) et fusion "
          f"(= ce qui est RÉELLEMENT croppé et envoyé à l'OCR) :")
    for z in zones_finales:
        marque = ""
        if z.x0 <= px1 and z.x1 >= px0 and z.y0 <= py1 and z.y1 >= py0:
            marque = "   <-- contient la bbox de sortie du mot 'Pavis'"
        print(f"  finale : ({z.x0:.1f}, {z.y0:.1f}, {z.x1:.1f}, {z.y1:.1f}){marque}")

    print("\nUtilise la zone marquée ci-dessus comme --bbox pour diagnostic_ocr_zone.py --page "
          f"{args.page} (elle doit correspondre EXACTEMENT à ce que Tesseract a vu en prod).")


if __name__ == "__main__":
    main()
