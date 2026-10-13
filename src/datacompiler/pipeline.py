"""Pipeline orchestration for PDF extraction, diagnostics, OCR and rendering."""

import argparse
import logging
from pathlib import Path

from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.model.document import Document
from datacompiler.frontend.extract import extraire
from datacompiler.frontend.layout import segmenter_page
from datacompiler.frontend import diagnose_document, display_report
from datacompiler.frontend.ocr.paddle import PaddleOCRBackend
from datacompiler.frontend.ocr.vector_zones import recuperer_texte_vectorise
from datacompiler.compile import resoudre
from datacompiler.backend import EXTENSIONS, FORMATS, _strategy_for_cli_format, resolve_deprecated_strategy
from datacompiler.backend.faithful_pdf import render_faithful_pdf
from datacompiler.backend.flow_pdf import render_flow_pdf
from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf

logger = logging.getLogger(__name__)
# Messages de progression destinés à l'utilisateur final (deux lignes au total).
# Tout le reste du journal est réservé au développement.
progress = logging.getLogger("datacompiler.progress")


def executer_pipeline(pdf_path, strategy="overlay", sauver_json=False,
                      dpi=300, dpi_ocr_vectoriel=300, paddle_lang="fr",
                      ocr_mode="auto"):

    """Run extraction, diagnostics, OCR enrichment, resolution, and rendering."""
    strategy = resolve_deprecated_strategy(strategy)
    pdf_path = str(Path(pdf_path).resolve())
    progress.info("Traitement : %s", Path(pdf_path).name)
    logger.info("[1/6] Extracting: %s", pdf_path)
    doc = extraire(Document(), pdf_path)

    logger.info("[2/6] Running diagnostics...")
    diagnose_document(doc)
    # Le rapport de diagnostic est écrit avec print() : on ne l'affiche que
    # si le journal INFO est actif (usage développeur).
    if logger.isEnabledFor(logging.INFO):
        display_report(doc)

    logger.debug(
        "Diagnostics complete. Full-page OCR recommendation: %s (not enabled in this pipeline)",
        getattr(doc.diagnostic, "recommend_full_ocr", False)
    )


    logger.info("[3/6] Processing OCR...")

    if ocr_mode == "skip":
        logger.info("      [OCR] 'skip' mode: OCR is disabled.")
    else:
        # A) Branche OCR Pleine Page
        do_full_ocr = (ocr_mode == "force") or (
            ocr_mode == "auto" and getattr(doc.diagnostic, "recommend_full_ocr", False)
        )
        if do_full_ocr:
            logger.info("      [OCR] Full-page OCR recommended (recommend_full_ocr=%s, mode=%s), but the global engine is disabled...",
                        getattr(doc.diagnostic, "recommend_full_ocr", False), ocr_mode)
            # ocraliser(doc, pdf_path, backend_name="paddle", lang=paddle_lang)
        else:
            logger.info("      [OCR] Full-page OCR is not required.")

        # B) Branche OCR Ciblé (Zones vectorielles)
        if ocr_mode in ("auto", "vector"):
            logger.info("      [OCR] Checking vector-text regions...")
            backend_paddle = PaddleOCRBackend(lang=paddle_lang, dpi=dpi_ocr_vectoriel)
            recuperer_texte_vectorise(
                doc, pdf_path, backend_paddle,
                lang=paddle_lang, dpi=dpi_ocr_vectoriel,
            )


    segmentation_activee = False
    for page in doc.pages:
        # Run segmentation only when recommended by page diagnostics.
        if getattr(page.diagnostic, "recommend_segmentation", False):
            segmenter_page(page)
            segmentation_activee = True

    if segmentation_activee:
        logger.info("[4/6] Segmented complex pages.")
    else:
        logger.info("[4/6] No segmentation required.")


    logger.info("[5/6] Resolving document content...")
    resoudre(doc)

    base = str(Path(pdf_path).with_suffix(""))
    logger.info("[6/6] Rendering with strategy %s...", strategy)
    if strategy in ("overlay", "clean_overlay", "rasterized"):
        fichier_sortie = base + "_propre.pdf"
        render_faithful_pdf(doc, fichier_sortie, strategy=strategy, dpi=dpi)
    elif strategy == "flow":
        fichier_sortie = base + "_flow.pdf"
        render_flow_pdf(doc, fichier_sortie)
    elif strategy == "rebuilt":
        fichier_sortie = base + "_rebuilt.pdf"
        render_rebuilt_pdf(doc, fichier_sortie, source_pdf=pdf_path, dpi=dpi)
    elif strategy in FORMATS:
        fichier_sortie = base + f"_propre.{EXTENSIONS[strategy]}"
        FORMATS[strategy](doc, fichier_sortie)
    else:
        raise ValueError(f"Unknown rendering strategy: {strategy}")

    if sauver_json:
        json_path = base + ".document.json"
        doc.save(json_path)
        logger.info("      Document JSON: %s", json_path)
    logger.info("      Wrote: %s", fichier_sortie)
    progress.info("Terminé : %s", fichier_sortie)
    return doc


# English entry point for the public API. Keep the French name as a
# compatibility alias for existing users.
run_pipeline = executer_pipeline


def _configurer_journal_client():
    """Console utilisateur : avertissements et erreurs, plus deux lignes de progression."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s", force=True)
    progress.setLevel(logging.INFO)
    progress.propagate = False
    gestionnaire = logging.StreamHandler()
    gestionnaire.setFormatter(logging.Formatter("%(message)s"))
    progress.addHandler(gestionnaire)


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="PDF extraction and reconstruction pipeline")
    parser.add_argument("pdf")
    parser.add_argument("--format", choices=["faithful-pdf", "flow-pdf", "rebuilt-pdf", "markdown", "html", "docx"],
                        default="faithful-pdf", help="Output format")
    parser.add_argument("--strategy", choices=["clean_overlay", "flow", "overlay", "rasterized", "rebuilt"],
                        default="overlay",
                        help="Rendering strategy: overlay (default: keeps the source PDF and adds hidden text only for "
                             "corrected or recovered words), rebuilt (new PDF following the resolved reading order), "
                             "rasterized, flow, or clean_overlay (deprecated: runs rebuilt)")
    parser.add_argument("--dpi", type=int, default=300, help="DPI for final PDF rendering")
    parser.add_argument("--dpi-ocr-vectoriel", "--vector-ocr-dpi", dest="dpi_ocr_vectoriel", type=int, default=300,
                        help="DPI for targeted vector OCR, independent of --dpi")
    parser.add_argument("--paddle-lang", default="fr", help="PaddleOCR language for targeted vector-text OCR (ISO 639-1 code, e.g. 'fr')")
    parser.add_argument("--ocr-mode", choices=["auto", "force", "skip", "vector"], default="auto",
                        help="OCR policy: automatic, force full-page, skip, or vector-only")
    args = parser.parse_args()

    _configurer_journal_client()

    executer_pipeline(
        args.pdf,
        strategy=_strategy_for_cli_format(args.format, args.strategy),
        sauver_json=False,
        dpi=args.dpi, dpi_ocr_vectoriel=args.dpi_ocr_vectoriel,
        paddle_lang=args.paddle_lang, ocr_mode=args.ocr_mode,
    )


if __name__ == "__main__":
    main()
