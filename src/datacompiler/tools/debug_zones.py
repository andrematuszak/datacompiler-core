"""Diagnostic : que renvoie Paddle dans l'en-tête de la page 2, et que deviennent ses bbox ?

Usage (depuis la racine du dépôt, venv activé) :
    python debug_zones.py [tests/fixtures/impots-revenu/impots-revenu.pdf] [y_min y_max]

Ne modifie rien : il « espionne » deux fonctions de vector_zones le temps d'une exécution.
Affiche, pour la bande y_min..y_max (120..165 par défaut = cellules « enfants mineurs ... » et
« NOMBRE DE PARTS ») :
  1. les zones vectorielles serrées, puis les zones fusionnées envoyées à Paddle ;
  2. pour chaque zone fusionnée, ce que Paddle renvoie (texte + bbox BRUTE en pt page) ;
  3. les mêmes mots APRÈS _assigner_taille_lissee (calibrage par ligne visuelle).
"""
import sys

from datacompiler.frontend.extract import extraire
from datacompiler.frontend.ocr import vector_zones as vz
from datacompiler.frontend.ocr.paddle import PaddleOCRBackend
from datacompiler.model.document import Document, BBox

PDF = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/impots-revenu/impots-revenu.pdf"
Y_MIN = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
Y_MAX = float(sys.argv[3]) if len(sys.argv) > 3 else 165.0


def _dans_bande(y0, y1):
    return Y_MIN <= (y0 + y1) / 2 <= Y_MAX


def _fmt(b):
    return f"x0={b.x0:6.1f} y0={b.y0:6.1f} x1={b.x1:6.1f} y1={b.y1:6.1f}"


def main(backend=None, pdf=PDF):
    doc = extraire(Document(), pdf)
    page = doc.pages[0]
    zones = [z for z in vz.zones_texte_vectorise_probable(page) if _dans_bande(z[1], z[3])]

    print("=== 1. ZONES SERRÉES (encre vectorielle) ===")
    for z in sorted(zones, key=lambda z: (z[1], z[0])):
        print("   ", [round(v, 1) for v in z])
    marginees = [BBox(z[0] - vz.MARGE_ZONE, z[1] - vz.MARGE_ZONE, z[2] + vz.MARGE_ZONE, z[3] + vz.MARGE_ZONE)
                 for z in zones]
    print("=== ZONES FUSIONNÉES (marge %.1f pt, ce que reçoit Paddle ; approx. : sans le clipping sur natifs) ===" % vz.MARGE_ZONE)
    for b in sorted(vz._fusionner_zones_chevauchantes(marginees), key=lambda b: (b.y0, b.x0)):
        print("   ", _fmt(b))

    # --- espions ---------------------------------------------------------------------------
    original_fusion = vz.fusionner_zone_multi_backend
    print("\n=== 2. SORTIE BRUTE DE PADDLE PAR ZONE ENVOYÉE (pt page) ===")

    def espion_fusion(image, offset, backends, **kw):
        mots = original_fusion(image, offset, backends, **kw)
        dpi = kw.get("dpi") or 300
        w_pt = (image.size[0] if hasattr(image, "size") else image.shape[1]) * 72 / dpi
        h_pt = (image.size[1] if hasattr(image, "size") else image.shape[0]) * 72 / dpi
        if _dans_bande(offset[1], offset[1] + h_pt):
            print(f"  zone envoyée : x0={offset[0]:6.1f} y0={offset[1]:6.1f} x1={offset[0] + w_pt:6.1f} y1={offset[1] + h_pt:6.1f}")
            for m in mots:
                print(f"      {m.text!r:26} {_fmt(m.bbox)} conf={m.confidence}")
            if not mots:
                print("      (aucun mot)")
        return mots

    original_taille = vz._assigner_taille_lissee

    def espion_taille(mots, dessins=None, zones_par_mot=None):
        avant = {id(m): (m.bbox.x0, m.bbox.y0, m.bbox.x1, m.bbox.y1) for m in mots if m.bbox}
        original_taille(mots, dessins, zones_par_mot)
        print("\n=== 3. APRÈS CALIBRAGE PAR LIGNE (_assigner_taille_lissee) : avant -> après ===")
        for m in sorted(mots, key=lambda m: (m.bbox.y0, m.bbox.x0)):
            if m.bbox and _dans_bande(m.bbox.y0, m.bbox.y1):
                a = avant[id(m)]
                print(f"  {m.text!r:26} y0 {a[1]:6.1f} -> {m.bbox.y0:6.1f} | x0 {a[0]:6.1f} -> {m.bbox.x0:6.1f} "
                      f"| x1 {a[2]:6.1f} -> {m.bbox.x1:6.1f} | y1 {a[3]:6.1f} -> {m.bbox.y1:6.1f}")

    vz.fusionner_zone_multi_backend = espion_fusion
    vz._assigner_taille_lissee = espion_taille
    try:
        vz.recuperer_texte_vectorise(doc, pdf, backend or PaddleOCRBackend(lang="fr", dpi=300), lang="fr", dpi=300)
    finally:
        vz.fusionner_zone_multi_backend = original_fusion
        vz._assigner_taille_lissee = original_taille


if __name__ == "__main__":
    main()
