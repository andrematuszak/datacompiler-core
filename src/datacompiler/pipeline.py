"""Orchestrateur du moteur : frontend (extraction, diagnostic, OCR),
compile (arbitrage native/OCR), backend (rendu)."""

import argparse
import logging
import os
from pathlib import Path

from datacompiler.model.document import Document
from datacompiler.frontend.extract import extraire
from datacompiler.frontend import diagnostiquer, ocraliser, report as diagnostic_report
from datacompiler.frontend.ocr.tesseract import TesseractBackend
from datacompiler.frontend.ocr.vector_zones import recuperer_texte_vectorise
from datacompiler.compile import resoudre
from datacompiler.backend import EXTENSIONS, FORMATS
from datacompiler.backend.faithful_pdf import render_faithful_pdf

logger = logging.getLogger(__name__)


def executer_pipeline(pdf_path, format_sortie="faithful-pdf", sauver_json=True,
                      faithful_strategy="overlay", dpi=300, tesseract_lang="fra"):
    pdf_path = str(Path(pdf_path).resolve())
    logger.info("[1/6] Extraction : %s", pdf_path)
    doc = extraire(Document(), pdf_path)

    logger.info("[2/6] Diagnostic...")
    diagnostiquer(doc)
    diagnostic_report.afficher(doc)

    logger.debug(
        "Diagnostic terminé. Recommandation OCR : %s",
        getattr(doc.diagnostic, "recommend_ocr", False)
    )

    if doc.diagnostic.recommend_ocr and (api_key := os.getenv("MISTRAL_API_KEY")):
        logger.info("[3/6] Appel OCR...")
        ocraliser(doc, pdf_path, backend_name="mistral", api_key=api_key)
    elif doc.diagnostic.recommend_ocr:
        logger.warning("[3/6] OCR recommandé, mais MISTRAL_API_KEY absent : poursuite avec le texte natif.")
    else:
        logger.info("[3/6] OCR non nécessaire.")

    # Indépendant de MISTRAL_API_KEY et de recommend_ocr (page-entière) :
    # cible uniquement les zones de texte vectorisé repérées par
    # diagnostic/vector_text.py, comble un vide géométrique plutôt
    # qu'arbitrer un désaccord natif/OCR. No-op silencieux si aucune zone
    # détectée sur aucune page.
    logger.info("[4/6] OCR ciblé (texte vectorisé)...")
    recuperer_texte_vectorise(doc, pdf_path, TesseractBackend(lang=tesseract_lang, dpi=dpi), lang=tesseract_lang, dpi=dpi)

    logger.info("[5/6] Compilation...")
    resoudre(doc)

    base = str(Path(pdf_path).with_suffix(""))
    logger.info("[6/6] Rendu (%s)...", format_sortie)
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
        logger.info("      Document JSON : %s", json_path)
    logger.info("      Écrit : %s", fichier_sortie)
    return doc


def main():
    """Entrée CLI."""
    parser = argparse.ArgumentParser(description="Pipeline de nettoyage de PDF")
    parser.add_argument("pdf")
    parser.add_argument("--format", choices=["faithful-pdf", "rebuilt-pdf", "markdown", "html", "docx"], default="faithful-pdf")
    parser.add_argument("--faithful-strategy", choices=["overlay", "rasterized", "clean_overlay"], default="overlay", help="Stratégie de rendu PDF fidèle")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--tesseract-lang", default="fra", help="Langue Tesseract pour l'OCR ciblé du texte vectorisé")
    parser.add_argument("--no-json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true", help="Active l'affichage des logs de niveau DEBUG")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    executer_pipeline(args.pdf, args.format, not args.no_json, args.faithful_strategy, args.dpi, args.tesseract_lang)


if __name__ == "__main__":
    main()