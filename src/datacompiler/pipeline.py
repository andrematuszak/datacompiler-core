"""Orchestrateur du moteur : frontend (extraction, diagnostic, OCR),
compile (arbitrage native/OCR), backend (rendu)."""

import argparse
import logging
import os
from pathlib import Path

from datacompiler.model.document import Document
from datacompiler.frontend.extract import extraire
from datacompiler.frontend import diagnostiquer, ocraliser, report as diagnostic_report
from datacompiler.compile import resoudre
from datacompiler.backend import EXTENSIONS, FORMATS
from datacompiler.backend.faithful_pdf import render_faithful_pdf

# Logger spécifique au module
logger = logging.getLogger(__name__)


def executer_pipeline(pdf_path, format_sortie="faithful-pdf", sauver_json=True,
                      faithful_strategy="overlay", dpi=300):
    pdf_path = str(Path(pdf_path).resolve())
    logger.info("[1/5] Extraction : %s", pdf_path)
    doc = extraire(Document(), pdf_path)

    logger.info("[2/5] Diagnostic...")
    diagnostiquer(doc)
    diagnostic_report.afficher(doc)
    
    logger.debug(
        "Diagnostic terminé. Recommandation OCR : %s", 
        getattr(doc.diagnostic, "recommend_ocr", False)
    )

    if doc.diagnostic.recommend_ocr and (api_key := os.getenv("MISTRAL_API_KEY")):
        logger.info("[3/5] Appel OCR...")
        ocraliser(doc, pdf_path, backend_name="mistral", api_key=api_key)
    elif doc.diagnostic.recommend_ocr:
        logger.warning("[3/5] OCR recommandé, mais MISTRAL_API_KEY absent : poursuite avec le texte natif.")
    else:
        logger.info("[3/5] OCR non nécessaire.")

    logger.info("[4/5] Compilation...")
    resoudre(doc)

    base = str(Path(pdf_path).with_suffix(""))
    logger.info("[5/5] Rendu (%s)...", format_sortie)
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
    parser.add_argument("--faithful-strategy", choices=["overlay", "rasterized"], default="overlay")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--no-json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true", help="Active l'affichage des logs de niveau DEBUG")
    args = parser.parse_args()

    # Configuration globale des logs lors de l'exécution CLI
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    executer_pipeline(args.pdf, args.format, not args.no_json, args.faithful_strategy, args.dpi)


if __name__ == "__main__":
    main()