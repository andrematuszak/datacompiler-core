"""diagnostic_ocr_zone_reel.py — Appelle DIRECTEMENT le code de
production (rendre_zone_image + TesseractBackend.ocraliser_zone, donc
_extraire_deux_passes en interne) sur une zone donnée, étage par étage --
au lieu de réimplémenter l'appel OCR à la main comme diagnostic_ocr_zone.py.

Pourquoi ce script existe : diagnostic_ocr_zone.py, sur une bbox et un
DPI quasi identiques à ceux réellement utilisés en prod pour le mot
"Pavis", donne un résultat différent (l'avis à confiance faible, jamais
Pavis à 69%). Bbox et rendu ont été vérifiés identiques sur le papier --
donc la divergence vient probablement d'un détail d'implémentation entre
la réimplémentation du diagnostic et le vrai code, pas d'autre chose.
Plutôt que de continuer à comparer sur le papier, ce script élimine le
risque en import-ant et appelant le vrai code à chaque étage.

Usage :
    python diagnostic_ocr_zone_reel.py test-impots-revenu.pdf --page 0 \
        --bbox 78.2 213.5 103.7 224.1 --lang fra --dpi 300

(bbox par défaut ci-dessus = la zone réelle qui produit "Pavis", telle
que calculée par diagnostic_zones_reelles.py)
"""

import argparse

import fitz

from datacompiler.frontend.extract.pymupdf import rendre_zone_image
from datacompiler.frontend.ocr.tesseract import TesseractBackend, _extraire_deux_passes, _extraire_tesseract
from datacompiler.model.document import BBox


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--page", type=int, required=True, help="index de page (0-based, comme fitz)")
    parser.add_argument("--bbox", type=float, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    parser.add_argument("--lang", default="fra")
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()

    doc = fitz.open(args.pdf)
    page = doc[args.page]
    zone = BBox(*args.bbox)

    # Étage 0 : le crop réel, via la vraie fonction de rendu.
    image, scale = rendre_zone_image(page, zone, dpi=args.dpi)
    print(f"Crop réel : {image.size[0]}x{image.size[1]}px (scale={scale})")
    image.save("_diag_reel_crop.png")

    # Étage 1 : PSM 3 seul, fonction réelle _extraire_tesseract (pas de filtre, pas de fusion).
    print("\n--- PSM 3 seul (_extraire_tesseract réel, aucun filtre) ---")
    for m in _extraire_tesseract(image, args.lang, psm=3):
        print(f"  {m['text']!r}  conf={m['confidence']}  bbox_px=({m['x0']},{m['y0']},{m['x1']},{m['y1']})")

    # Étage 2 : PSM 6 seul, même fonction réelle.
    print("\n--- PSM 6 seul (_extraire_tesseract réel, aucun filtre) ---")
    for m in _extraire_tesseract(image, args.lang, psm=6):
        print(f"  {m['text']!r}  conf={m['confidence']}  bbox_px=({m['x0']},{m['y0']},{m['x1']},{m['y1']})")

    # Étage 3 : la fusion réelle (filtre bruit + confiance inclus).
    print("\n--- _extraire_deux_passes réel (fusion PSM3+PSM6, filtre bruit/confiance) ---")
    for m in _extraire_deux_passes(image, args.lang):
        print(f"  {m['text']!r}  conf={m['confidence']}  bbox_px=({m['x0']},{m['y0']},{m['x1']},{m['y1']})")

    # Étage 4 : le point d'entrée EXACT utilisé par vector_zones.py -- si
    # ça diverge encore des étages précédents, le problème est dans
    # ocraliser_zone lui-même (conversion pixel->points, offset), pas dans
    # l'extraction Tesseract.
    print("\n--- TesseractBackend.ocraliser_zone (point d'entrée réel de vector_zones.py) ---")
    backend = TesseractBackend(lang=args.lang, dpi=args.dpi)
    mots = backend.ocraliser_zone(image, offset=(zone.x0, zone.y0), lang=args.lang, dpi=args.dpi)
    for w in mots:
        print(f"  {w.text!r}  conf={w.confidence}  bbox_pdf=({w.bbox.x0:.1f},{w.bbox.y0:.1f},{w.bbox.x1:.1f},{w.bbox.y1:.1f})")


if __name__ == "__main__":
    main()
