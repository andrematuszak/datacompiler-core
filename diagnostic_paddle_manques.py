"""Diagnostic : que retourne PaddleOCR sur les zones où ':', 'la', et le
tiret de 'rendez-vous' manquent ? À lancer depuis la racine du repo.

Objectif : voir si Paddle ne détecte RIEN à cet endroit (case vide dans le
résultat), ou s'il détecte quelque chose mais avec une confiance trop basse
/ un texte fusionné avec le mot voisin (ex. 'rendezvous' en un seul bloc
plutôt que 'rendez' + '-' + 'vous' séparés).
"""
import fitz
from datacompiler.frontend.ocr.paddle import PaddleOcrBackend

PDF = "tests/fixtures/impots-revenu/impots-revenu.pdf"

# Zones approximatives à inspecter (x0,y0,x1,y1) -- à ajuster si besoin
# une fois qu'on voit le rendu réel :
ZONES = {
    "deux_points_numero_fiscal": (60, 175, 220, 195),
    "la_avant_les_pages": (14, 660, 300, 700),  # bas de page, "Plus de détails dans la (les)..."
    "tiret_rendezvous": (14, 780, 544, 825),
}

doc = fitz.open(PDF)
page = doc[0]
backend = PaddleOcrBackend()

for nom, (x0, y0, x1, y1) in ZONES.items():
    clip = fitz.Rect(x0, y0, x1, y1)
    pix = page.get_pixmap(clip=clip, dpi=300)
    img_path = f"/tmp/zone_{nom}.png"
    pix.save(img_path)
    from PIL import Image
    image = Image.open(img_path)
    resultats = backend.ocraliser_zone(image, offset=(x0, y0), dpi=300, lang="fr")
    print(f"--- {nom} ---")
    for r in resultats:
        print(" ", repr(r.text), r.bbox, "confiance=", getattr(r, "confidence", "?"))
    if not resultats:
        print("  (RIEN détecté)")
