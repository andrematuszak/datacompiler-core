"""Pipeline orchestration for PDF extraction, diagnostics, OCR and rendering."""

import argparse
import logging
import tempfile
from pathlib import Path

from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.model.document import Document
from datacompiler.frontend.extract import extraire
from datacompiler.frontend.layout import segmenter_page
from datacompiler.frontend import diagnose_document
from datacompiler.frontend.ocr.paddle import PaddleOCRBackend
from datacompiler.frontend.ocr.mistral import MistralBackend
from datacompiler.frontend.ocr.vector_zones import recuperer_texte_vectorise
from datacompiler.frontend.routing import (
    FALLBACK_OR_MANUAL_REVIEW,
    FULL_PAGE_MISTRAL_OCR,
    TARGETED_PADDLE_OCR,
    format_page_routes,
    route_page,
)
from datacompiler.model.metadata import LanguageInfo
from datacompiler.compile import resoudre
from datacompiler.backend import EXTENSIONS, FORMATS, _strategy_for_cli_format, resolve_deprecated_strategy
from datacompiler.backend.faithful_pdf import render_faithful_pdf
from datacompiler.backend.flow_pdf import render_flow_pdf
from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf
from datacompiler.translation.language import detect_page_language

logger = logging.getLogger(__name__)
# Page-level OCR routes are user-facing summaries; detailed diagnostics remain developer-only.
progress = logging.getLogger("datacompiler.progress")


def executer_pipeline(pdf_path, strategy="rebuilt", sauver_json=False,
                      dpi=300, dpi_ocr_vectoriel=300, paddle_lang=None,
                      ocr_mode="auto", render=True):

    """Run the PDF pipeline in six stages.

    Set ``render=False`` when a caller will edit the resolved document before
    producing its output. Rendering remains enabled by default for compatibility.
    Exécute le pipeline de compilation de PDF en 6 étapes claires :
    The six stages are:
    1. Native-text extraction.
    2. Page diagnostics.
    3. OCR enrichment.
    4. Segmentation.
    5. Content compilation and resolution.
    6. Final rendering (or deferred rendering when ``render=False``).
    """
    if ocr_mode == "force":
        raise NotImplementedError(
            "Forced full-page OCR is not implemented. "
            "Automatic per-page routing may use Mistral; use ocr_mode='vector' "
            "for targeted OCR, or 'skip' to disable OCR."
        )
    if ocr_mode not in {"auto", "skip", "vector"}:
        raise ValueError(f"Unknown OCR mode: {ocr_mode!r}")

    strategy = resolve_deprecated_strategy(strategy)
    pdf_path = str(Path(pdf_path).resolve())
    progress.info("Traitement : %s", Path(pdf_path).name)
    logger.info("[1/6] Extracting: %s", pdf_path)
    doc = extraire(Document(), pdf_path)

    logger.info("[2/6] Running diagnostics...")
    diagnose_document(doc)
    for page in doc.pages:
        page.routing = route_page(page, ocr_mode=ocr_mode)

    logger.debug(
        "Diagnostics complete. Full-page OCR recommendation: %s",
        getattr(doc.diagnostic, "recommend_full_ocr", False)
    )


    logger.info("[3/6] Processing OCR...")

    paddle_pages_by_language = {}
    mistral_pages = []
    if ocr_mode == "skip":
        logger.info("      [OCR] 'skip' mode: OCR is disabled.")
    else:
        for page in doc.pages:
            if paddle_lang:
                page.language = LanguageInfo(
                    code=paddle_lang,
                    confidence=1.0,
                    source="user_override",
                )
                for word in page.native.words:
                    word.language = paddle_lang
            elif page.native.words:
                try:
                    detect_page_language(page, source="native_text")
                except RuntimeError as exc:
                    logger.warning("Automatic language detection is unavailable: %s", exc)

        paddle_pages = [
            page for page in doc.pages
            if page.routing and page.routing.strategy == TARGETED_PADDLE_OCR
        ]
        mistral_pages = [
            page for page in doc.pages
            if page.routing and page.routing.strategy == FULL_PAGE_MISTRAL_OCR
        ]

        for page in paddle_pages:
            language = paddle_lang or page.language.code
            if not language:
                page.routing.category = "needs_review"
                page.routing.strategy = FALLBACK_OR_MANUAL_REVIEW
                page.routing.backend = None
                page.routing.reasons.append("native text language could not be detected for PaddleOCR")
                logger.warning(
                    "Page %s: targeted OCR skipped because its language could not be determined; "
                    "set paddle_lang explicitly.",
                    page.number,
                )
                continue
            if paddle_lang:
                page.language = LanguageInfo(
                    code=paddle_lang,
                    confidence=1.0,
                    source="user_override",
                )
            paddle_pages_by_language.setdefault(language, []).append(page.number)

    for route_summary in format_page_routes(doc.pages):
        progress.info(route_summary)

    if ocr_mode != "skip":
        for language, page_numbers in paddle_pages_by_language.items():
            logger.info(
                "Running targeted PaddleOCR on page(s) %s using language %s.",
                ", ".join(str(number) for number in page_numbers),
                language,
            )
            backend_paddle = PaddleOCRBackend(lang=language, dpi=dpi_ocr_vectoriel)
            recuperer_texte_vectorise(
                doc,
                pdf_path,
                backend_paddle,
                lang=language,
                dpi=dpi_ocr_vectoriel,
                pages=page_numbers,
            )

        if mistral_pages:
            page_numbers = [page.number for page in mistral_pages]
            MistralBackend().ocraliser(doc, pdf_path, pages=page_numbers)
            for page in mistral_pages:
                if page.ocr.words:
                    try:
                        detect_page_language(page, source="post_ocr")
                    except RuntimeError as exc:
                        logger.warning("Post-OCR language detection is unavailable: %s", exc)

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
    fichier_sortie = None
    if render:
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
    else:
        logger.info("[6/6] Rendering deferred until document editing is complete.")

    if sauver_json:
        json_path = base + ".document.json"
        doc.save(json_path)
        logger.info("      Document JSON: %s", json_path)
    if fichier_sortie:
        logger.info("      Wrote: %s", fichier_sortie)
        progress.info("Terminé : %s", fichier_sortie)
    return doc


# English entry point for the public API. Keep the French name as a
# compatibility alias for existing users.
run_pipeline = executer_pipeline


def traduire_document(doc, pdf_path, target_lang, source_lang=None, *, edit=False):
    """Translate a processed document: XLIFF export, DeepL pre-translation, translated rebuilt PDF.

    Writes ``<name>.<target_lang>.xlf`` (review-ready XLIFF) and ``<name>_<target_lang>_rebuilt.pdf``
    next to the source PDF, and returns the path of the translated PDF.
    """
    from datacompiler.translation import (
        edit_translation_pdf, export_xliff, import_xliff, render_translated_pdf,
    )
    from datacompiler.translation.providers import translate_xliff_file

    base = str(Path(pdf_path).with_suffix(""))
    xliff_traduit = f"{base}.{target_lang}.xlf"
    sortie = f"{base}_{target_lang}_rebuilt.pdf"
    with tempfile.TemporaryDirectory() as dossier:
        xliff_source = Path(dossier) / "source.xlf"
        units = export_xliff(doc, xliff_source, target_language=target_lang, source_language=source_lang)
        translate_xliff_file(xliff_source, xliff_traduit)
    traduction = import_xliff(xliff_traduit, expected_units=units)
    if edit:
        application = edit_translation_pdf(
            doc, traduction, sortie, expected_units=units,
        )
        if application is None:
            return None
    else:
        application = render_translated_pdf(doc, traduction, sortie, expected_units=units)
    for avertissement in application.layout_warnings:
        logger.warning("Translated layout: %s", avertissement)
    return sortie


def _document_source_language(doc):
    """Return the most common confidently detected page language, if available."""
    languages = [
        page.language.code
        for page in getattr(doc, "pages", [])
        if getattr(page, "language", None) is not None and page.language.code
    ]
    if not languages:
        return None
    return max(sorted(set(languages)), key=languages.count)


# Format de sortie imposé par chaque stratégie de rendu en ligne de commande.
_FORMAT_PAR_STRATEGIE = {
    "overlay": "faithful-pdf",
    "rasterized": "faithful-pdf",
    "clean_overlay": "faithful-pdf",  # obsolète : redirigé vers rebuilt
    "rebuilt": "rebuilt-pdf",
    "flow": "flow-pdf",
}


def _configurer_journal_client():
    """Console utilisateur : avertissements et erreurs, plus deux lignes de progression."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s", force=True)
    progress.setLevel(logging.INFO)
    progress.propagate = False
    for ancien in tuple(progress.handlers):
        if getattr(ancien, "_datacompiler_client_handler", False):
            progress.removeHandler(ancien)
            ancien.close()

    gestionnaire = logging.StreamHandler()
    gestionnaire._datacompiler_client_handler = True
    gestionnaire.setFormatter(logging.Formatter("%(message)s"))
    progress.addHandler(gestionnaire)


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="PDF extraction and reconstruction pipeline")
    parser.add_argument("pdf")
    parser.add_argument("--format", choices=["faithful-pdf", "flow-pdf", "rebuilt-pdf", "markdown", "html", "docx"],
                        default=None,
                        help="Output format (default: rebuilt-pdf, a new PDF following the resolved reading order). "
                             "faithful-pdf requires --strategy")
    parser.add_argument("--strategy", choices=["clean_overlay", "flow", "overlay", "rasterized", "rebuilt"],
                        default=None,
                        help="Rendering strategy, required with --format faithful-pdf: overlay (keeps the source PDF "
                             "and adds hidden text only for corrected or recovered words) or rasterized. "
                             "clean_overlay is deprecated and runs rebuilt. Alone, --strategy selects the matching format")
    parser.add_argument("--target-lang", default=None,
                        help="Also translate the document into this language (e.g. en). Requires "
                             "DEEPL_AUTH_KEY and datacompiler[translation]; the text is sent to DeepL")
    parser.add_argument("--source-lang", default=None,
                        help="Source language for translation (default: detect from the document)")
    parser.add_argument("--no-translate", action="store_true",
                        help="Never translate, even if --target-lang is given (useful to test files)")
    parser.add_argument("--edit-translation", action="store_true",
                        help="Open the lightweight desktop editor after machine translation; requires --target-lang")
    parser.add_argument("-editor", "--editor", action="store_true",
                        help="Open the editor for resolved document text; with --target-lang, edit the translation")
    parser.add_argument("--dpi", type=int, default=300, help="DPI for final PDF rendering")
    parser.add_argument("--dpi-ocr-vectoriel", "--vector-ocr-dpi", dest="dpi_ocr_vectoriel", type=int, default=300,
                        help="DPI for targeted vector OCR, independent of --dpi")
    parser.add_argument("--paddle-lang", default=None,
                        help="PaddleOCR language for targeted vector-text OCR (default: detect from PDF text)")
    parser.add_argument("--ocr-mode", choices=["auto", "force", "skip", "vector"], default="auto",
                        help="OCR policy: automatic, force (unsupported), skip, or vector-only")
    args = parser.parse_args()

    if args.ocr_mode == "force":
        parser.error(
            "--ocr-mode force is not implemented in this release; "
            "use --ocr-mode vector for targeted OCR"
        )
    if args.edit_translation and (not args.target_lang or args.no_translate):
        parser.error("--edit-translation requires --target-lang and cannot be combined with --no-translate")

    if args.format is None:
        args.format = _FORMAT_PAR_STRATEGIE.get(args.strategy, "rebuilt-pdf")
    if args.format == "faithful-pdf" and args.strategy is None:
        parser.error("--format faithful-pdf requires --strategy overlay or rasterized")
    if args.strategy and args.format != _FORMAT_PAR_STRATEGIE[args.strategy]:
        parser.error(f"--strategy {args.strategy} does not apply to --format {args.format}")
    if args.editor and args.format != "rebuilt-pdf":
        parser.error("--editor requires the rebuilt-pdf output format")

    _configurer_journal_client()

    document = executer_pipeline(
        args.pdf,
        strategy=_strategy_for_cli_format(args.format, args.strategy),
        sauver_json=False,
        dpi=args.dpi, dpi_ocr_vectoriel=args.dpi_ocr_vectoriel,
        paddle_lang=args.paddle_lang, ocr_mode=args.ocr_mode,
        render=not (args.editor or args.edit_translation),
    )

    if args.no_translate:
        if args.target_lang:
            progress.info("Traduction ignorée (--no-translate).")
    if args.target_lang and not args.no_translate:
        if args.source_lang:
            for page in getattr(document, "pages", []):
                page.language = LanguageInfo(
                    code=args.source_lang,
                    confidence=1.0,
                    source="user_override",
                )
                for word in page.native.words + page.ocr.words:
                    word.language = args.source_lang
        try:
            sortie = traduire_document(
                document,
                args.pdf,
                args.target_lang,
                args.source_lang or _document_source_language(document),
                edit=args.edit_translation or args.editor,
            )
        except (RuntimeError, ValueError) as exc:
            parser.exit(1, f"Translation failed: {exc}\n")
        if sortie:
            progress.info("Traduit : %s", sortie)
        else:
            progress.info("Éditeur fermé sans enregistrement du PDF.")
    elif args.editor:
        from datacompiler.translation import edit_document_pdf

        output_path = str(Path(args.pdf).with_suffix("")) + "_rebuilt.pdf"
        try:
            result = edit_document_pdf(document, output_path)
        except (RuntimeError, ValueError) as exc:
            parser.exit(1, f"Editor failed: {exc}\n")
        if result is not None:
            progress.info("Édité : %s", output_path)
        else:
            progress.info("Éditeur fermé sans enregistrement du PDF.")


if __name__ == "__main__":
    main()
