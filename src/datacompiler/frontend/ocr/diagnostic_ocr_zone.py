"""diagnostic_ocr_zone.py — Isole une zone d'une page PDF et compare
plusieurs combinaisons DPI x PSM Tesseract, avec confiance par mot.

Objectif : confirmer/infirmer une hypothèse AVANT de toucher à
tesseract.py, conformément à "diagnostic avant correctif". Aucune
dépendance au reste du pipeline datacompiler -- juste fitz + pytesseract,
pour pouvoir tourner ce script seul sur un poste de dev.

Usage :
    python diagnostic_ocr_zone.py test-impots-revenu.pdf --page 1 \
        --bbox 40 380 220 420 --lang fra --etiquette "Reference Pavis"

    python diagnostic_ocr_zone.py test-impots-revenu.pdf --page 1 \
        --bbox 15 330 45 360 --lang fra --etiquette "Icone Sur place"

Comment trouver la bbox :
    - via diagnostic_json.py chercher (mots reconstructed/ocr_ proches)
    - ou en repérant la zone dans frontend/diagnostic/vector_text.py
      (zones_texte_vectorise_probable) et en imprimant ses bbox

--page est en INDEX 0 (comme fitz), pas le numéro affiché sur le PDF.
"""

import argparse
import io

import fitz
import pytesseract

import sys
import shutil
import pytesseract

if sys.platform == "win32":
    # Chemin par défaut pour Windows
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

elif sys.platform == "darwin":
    # Chemin pour macOS
    # shutil.which permet de trouver automatiquement l'emplacement si Tesseract est dans le PATH.
    # Sinon, on donne le chemin Homebrew par défaut (processeurs M1/M2/M3 ou Intel).
    chemin_mac = shutil.which('tesseract') 
    if not chemin_mac:
        # Fallback classique si shutil.which ne le trouve pas directement
        chemin_mac = '/opt/homebrew/bin/tesseract' # ou '/usr/local/bin/tesseract' pour les vieux Mac Intel
    
    pytesseract.pytesseract.tesseract_cmd = chemin_mac

from PIL import Image

# Même jeu de PSM que tesseract.py, + PSM 7 (ligne unique) et 11 (texte
# épars sans ordre) pour tester l'hypothèse "segmentation de bloc trop
# large casse les élisions/petits tokens isolés".
_PSM_A_TESTER = {
    3: "auto (défaut page)",
    6: "bloc uniforme",
    7: "ligne unique",
    11: "texte épars, sans ordre",
}

_DPI_A_TESTER = [300, 400, 600]


def _cropper_zone(pdf_path: str, page_index: int, bbox: tuple, dpi: int) -> Image.Image:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        rect = fitz.Rect(*bbox)
        scale = dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
        return Image.open(io.BytesIO(pix.tobytes("png")))
    finally:
        doc.close()


def _ocr_avec_details(image: Image.Image, lang: str, psm: int) -> list:
    donnees = pytesseract.image_to_data(
        image, lang=lang, config=f"--psm {psm}", output_type=pytesseract.Output.DICT
    )
    mots = []
    for j in range(len(donnees["text"])):
        texte = donnees["text"][j].strip()
        if not texte:
            continue
        conf = float(donnees["conf"][j])
        mots.append((texte, conf))
    return mots


def diagnostiquer(pdf_path: str, page_index: int, bbox: tuple, lang: str, etiquette: str):
    print(f"\n{'=' * 70}")
    print(f"Zone : {etiquette or bbox}  |  page {page_index}  |  bbox {bbox}")
    print(f"{'=' * 70}")

    for dpi in _DPI_A_TESTER:
        image = _cropper_zone(pdf_path, page_index, bbox, dpi)
        # Sauvegarde du crop pour inspection visuelle -- vérifier à l'oeil
        # que la bbox cadre bien la zone attendue avant de juger l'OCR.
        crop_path = f"_diag_crop_dpi{dpi}.png"
        image.save(crop_path)

        for psm, description in _PSM_A_TESTER.items():
            resultats = _ocr_avec_details(image, lang, psm)
            texte_brut = " ".join(t for t, _ in resultats) or "(rien détecté)"
            details = ", ".join(f"{t!r}({c:.0f}%)" for t, c in resultats)
            print(f"  DPI={dpi:>3} PSM={psm} ({description:<22}) -> {texte_brut}")
            print(f"      détail par token : {details}")

    print(f"\n  Crops sauvegardés : _diag_crop_dpi{{300,400,600}}.png (vérifier le cadrage à l'oeil)")


def main():
    parser = argparse.ArgumentParser(description="Diagnostic OCR isolé sur une zone de PDF")
    parser.add_argument("pdf")
    parser.add_argument("--page", type=int, required=True, help="index de page (0-based, comme fitz)")
    parser.add_argument("--bbox", type=float, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    parser.add_argument("--lang", default="fra")
    parser.add_argument("--etiquette", default="", help="nom lisible de la zone pour l'affichage")
    args = parser.parse_args()

    diagnostiquer(args.pdf, args.page, tuple(args.bbox), args.lang, args.etiquette)


if __name__ == "__main__":
    main()
