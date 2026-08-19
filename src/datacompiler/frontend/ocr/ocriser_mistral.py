import os
import sys
import json
import random
import base64
import pymupdf
from pathlib import Path
from mistralai import Mistral

def ocriser_pdf(pdf_path: str, output_path: str = None):
    # 1. Vérification de la clé API
    api_key = "atbgsXtCtdm2dmb3J5J4iWPMSn78UeY8"
    if not api_key:
        raise ValueError("La variable d'environnement MISTRAL_API_KEY est manquante.")

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        raise FileNotFoundError(f"Le fichier {pdf_path} n'existe pas.")

    print(f" Chargement du client Mistral...")
    client = Mistral(api_key=api_key)

    # 2. Téléversement du PDF
    print(f" Upload du document : {pdf_file.name}...")
    with open(pdf_file, "rb") as f:
        uploaded_file = client.files.upload(
            file={
                "file_name": pdf_file.name,
                "content": f.read(),
            },
            purpose="ocr"
        )

    # 3. Récupération de l'URL signée pour le traitement
    signed_url = client.files.get_signed_url(file_id=uploaded_file.id)

    # 4. Exécution de l'OCR Mistral
    print(" Traitement OCR en cours via Mistral OCR...")
    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": signed_url.url,
        },
        include_image_base64=False
    )

    # 5. Sauvegarde ou affichage du résultat
    if output_path:
        # Convertit la réponse Pydantic / Objet en dictionnaire / JSON
        res_dict = ocr_response.model_dump() if hasattr(ocr_response, "model_dump") else str(ocr_response)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(res_dict, f, ensure_ascii=False, indent=2)
        print(f" Résultat OCR sauvegardé dans : {output_path}")

    return ocr_response

def ocriser_zone_aléatoire(pdf_path: str, output_path: str = "zone_ocr.json"):
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("La variable d'environnement MISTRAL_API_KEY est manquante.")

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Le fichier {pdf_path} est introuvable.")

    # 1. Ouvrir le PDF et récupérer la Page 1
    doc = pymupdf.open(pdf_path)
    page = doc[0]
    w, h = page.rect.width, page.rect.height

    # 2. Générer une bounding box (Rect) aléatoire sur la page 1
    # On garantit une zone minimale (150px de largeur/hauteur min)
    x0 = random.uniform(0, max(1, w - 150))
    y0 = random.uniform(0, max(1, h - 150))
    x1 = random.uniform(x0 + 100, w)
    y1 = random.uniform(y0 + 100, h)
    crop_rect = pymupdf.Rect(x0, y0, x1, y1)

    print(f"📐 Zone aléatoire générée (Page 1) : x0={x0:.1f}, y0={y0:.1f}, x1={x1:.1f}, y1={y1:.1f}")

    # 3. Découper (crop) et rastériser la zone à 300 DPI
    pix = page.get_pixmap(clip=crop_rect, dpi=300)
    png_bytes = pix.tobytes("png")

    # Sauvegarder l'image découpée pour contrôle visuel
    crop_image_path = "zone_hasard.png"
    pix.save(crop_image_path)
    print(f"📸 Image de la zone sauvegardée sous '{crop_image_path}'")

    # 4. Encodage Base64 pour l'envoyer à Mistral sans passer par un téléversement de fichier
    b64_image = base64.b64encode(png_bytes).decode("utf-8")
    data_url = f"data:image/png;base64,{b64_image}"

    # 5. Appel de Mistral OCR sur l'image découpée
    client = Mistral(api_key=api_key)
    print("🤖 Envoi du fragment à Mistral OCR...")

    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "image_url",
            "image_url": data_url,
        }
    )

    # 6. Exportation du résultat
    res_dict = ocr_response.model_dump() if hasattr(ocr_response, "model_dump") else str(ocr_response)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(res_dict, f, ensure_ascii=False, indent=2)

    print(f"✅ OCR terminé ! Résultat sauvegardé dans '{output_path}'")
    return res_dict

if __name__ == "__main__":
    pdf_file = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/test-impots-revenu.pdf"
    ocriser_zone_aléatoire(pdf_file)

    input_pdf = sys.argv[1]
    output_json = sys.argv[2] if len(sys.argv) > 2 else "resultat_ocr.json"

    ocriser_pdf(input_pdf, output_json)