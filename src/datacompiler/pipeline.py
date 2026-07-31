"""Orchestrateur du moteur : frontend (extraction, diagnostic, OCR),
compile (arbitrage native/OCR), backend (rendu)."""


import argparse
import os
from pathlib import Path


from model import Document
from frontend.extract import extraire
from frontend.diagnostic import diagnostiquer
from frontend.diagnostic import report as diagnostic_report
from frontend.ocr import ocraliser
from compile import resoudre
from backend import EXTENSIONS, FORMATS
from backend.faithful_pdf import render_faithful_pdf




def executer_pipeline(pdf_path, format_sortie="faithful-pdf", sauver_json=True,
                      faithful_strategy="rasterized", dpi=300):
    pdf_path = str(Path(pdf_path).resolve())
    print(f"[1/5] Extraction : {pdf_path}")
    doc = extraire(Document(), pdf_path)


    print("[2/5] Diagnostic...")
    diagnostiquer(doc)
    diagnostic_report.afficher(doc)


    if doc.diagnostic.recommend_ocr and (api_key := os.getenv("MISTRAL_API_KEY")):
        print("[3/5] Appel OCR...")
        ocraliser(doc, pdf_path, api_key)
    elif doc.diagnostic.recommend_ocr:
        print("[3/5] OCR recommandé, mais MISTRAL_API_KEY absent : poursuite avec le texte natif.")
    else:
        print("[3/5] OCR non nécessaire.")


    print("[4/5] Compilation...")
    resoudre(doc)


    base = str(Path(pdf_path).with_suffix(""))
    print(f"[5/5] Rendu ({format_sortie})...")
    if format_sortie == "faithful-pdf":
        fichier_sortie = base + "_propre.pdf"
        render_faithful_pdf(doc, fichier_sortie, strategy=faithful_strategy, dpi=dpi)
    elif format_sortie in FORMATS:
        fichier_sortie = base + f"_propre.{EXTENSIONS[format_sortie]}"
        FORMATS[format_sortie](doc, fichier_sortie)
    else:
        raise ValueError(f"Format inconnu : {format_sortie}")


    if sauver_json:
        json_path = base + ".document.json"
        doc.save(json_path)
        print(f"      Document JSON : {json_path}")
    print(f"      Écrit : {fichier_sortie}")
    return doc




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de nettoyage de PDF")
    parser.add_argument("pdf")
    parser.add_argument("--format", choices=["faithful-pdf", "rebuilt-pdf", "markdown", "html", "docx"], default="faithful-pdf")
    parser.add_argument("--faithful-strategy", choices=["rasterized", "overlay"], default="rasterized")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--no-json", action="store_true")
    args = parser.parse_args()
    executer_pipeline(args.pdf, args.format, not args.no_json, args.faithful_strategy, args.dpi)