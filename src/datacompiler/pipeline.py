"""Orchestrateur du moteur : frontend (extraction, diagnostic, OCR),
compile (arbitrage native/OCR), backend (rendu)."""

import argparse
import logging
import os
from pathlib import Path

from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.model.document import Document
from datacompiler.frontend.extract import extraire
from datacompiler.frontend import diagnostiquer, ocraliser, report as diagnostic_report
from datacompiler.frontend.ocr.tesseract import TesseractBackend
from datacompiler.frontend.ocr.paddle import PaddleOCRBackend
from datacompiler.frontend.ocr.vector_zones import recuperer_texte_vectorise
from datacompiler.compile import resoudre
from datacompiler.backend import EXTENSIONS, FORMATS
from datacompiler.backend.faithful_pdf import render_faithful_pdf
from datacompiler.backend.flow_pdf import render_flow_pdf
from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf

logger = logging.getLogger(__name__)


def executer_pipeline(pdf_path, strategy="overlay", sauver_json=True,
                      dpi=300, dpi_ocr_vectoriel=300, tesseract_lang="fra", paddle_lang="fr"):
    """
    dpi : DPI du RENDU final (faithful/rasterized) -- indépendant de l'OCR,
    garder bas pour limiter la taille de fichier.
    dpi_ocr_vectoriel : DPI dédié à l'OCR ciblé des zones de texte
    vectorisé (recuperer_texte_vectorise). Découplé de `dpi`, mais laissé
    à 300 (même valeur que dpi) PAR DÉFAUT -- ⚠️ ROLLBACK : un essai à 600
    en global a corrigé "Pavis" mais causé une régression confirmée sur
    d'autres zones (mots natifs disparus, "célibataires" -> "TRES" sur le
    tableau RÉSIDENCE de la page 2). Un DPI élevé aide sur un mot court et
    isolé, mais pas garanti sur une zone dense/complexe -- un défaut
    global n'est pas la bonne granularité. Piste à creuser : DPI
    conditionnel à la taille de la zone, pas un défaut unique pour toutes
    les zones. Le paramètre reste disponible pour des tests ciblés
    (diagnostic_ocr_zone_reel.py), juste plus comme valeur par défaut du
    pipeline complet tant que ce n'est pas résolu proprement.
    tesseract_lang / paddle_lang : DEUX paramètres distincts, PAS un seul
    `lang` partagé -- Tesseract attend un code ISO 639-2 ("fra"),
    PaddleOCR attend ISO 639-1 ("fr"). Réutiliser tesseract_lang pour les
    deux planterait ou ferait tourner PaddleOCR dans une langue non
    reconnue, silencieusement.
    """
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
    # DPI dédié (dpi_ocr_vectoriel), PAS le DPI de rendu -- cf. docstring
    # de executer_pipeline.
    # Deux backends fournis -> fusionnés zone par zone (fusion_ocr.py).
    # PaddleOCR non installé/indisponible dégrade gracieusement vers
    # Tesseract seul (cf. fusion_ocr.fusionner_zone_multi_backend) --
    # aucune vérification de disponibilité nécessaire ici.
    logger.info("[4/6] OCR ciblé (texte vectorisé)...")
    backends_ocr_vectoriel = {
        "tesseract": TesseractBackend(lang=tesseract_lang, dpi=dpi_ocr_vectoriel),
        #"paddleocr": PaddleOCRBackend(lang=paddle_lang, dpi=dpi_ocr_vectoriel),
    }
    recuperer_texte_vectorise(
        doc, pdf_path, backends_ocr_vectoriel,
        lang=tesseract_lang, dpi=dpi_ocr_vectoriel,
    )

    logger.info("[5/6] Compilation...")
    resoudre(doc)

    base = str(Path(pdf_path).with_suffix(""))
    logger.info("[6/6] Rendu (stratégie : %s)...", strategy)
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
        raise ValueError(f"Stratégie inconnue : {strategy}")

    if sauver_json:
        json_path = base + ".document.json"
        doc.save(json_path)
        logger.info("      Document JSON : %s", json_path)
    logger.info("      Écrit : %s", fichier_sortie)
    return doc


def main():
    """Entrée CLI."""
    parser = argparse.ArgumentParser(description="Pipeline de compilation de PDF")
    parser.add_argument("pdf")
    parser.add_argument("--format", choices=["faithful-pdf", "flow-pdf", "rebuilt-pdf", "markdown", "html", "docx"], 
                        default="faithful-pdf", help="Format de sortie")
    parser.add_argument("--strategy", choices=["clean_overlay", "flow", "overlay", "rasterized", "rebuilt"], 
                        default="overlay", help="Stratégie de rendu : overlay (défaut), clean_overlay, rasterized, flow, rebuilt, markdown, html, docx")
    parser.add_argument("--dpi", type=int, default=300, help="DPI du rendu final (faithful/rasterized)")
    parser.add_argument("--dpi-ocr-vectoriel", type=int, default=300,
                        help="DPI dédié à l'OCR ciblé des zones de texte vectorisé (découplé de --dpi) -- "
                             "600 corrige 'Pavis' mais régresse d'autres zones, cf. docstring executer_pipeline")
    parser.add_argument("--tesseract-lang", default="fra", help="Langue Tesseract pour l'OCR ciblé du texte vectorisé (code ISO 639-2, ex. 'fra')")
    parser.add_argument("--paddle-lang", default="fr", help="Langue PaddleOCR pour l'OCR ciblé du texte vectorisé (code ISO 639-1, ex. 'fr')")
    parser.add_argument("--no-json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true", help="Active l'affichage des logs de niveau DEBUG")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    executer_pipeline(
        args.pdf, strategy=args.strategy, sauver_json=not args.no_json,
        dpi=args.dpi, dpi_ocr_vectoriel=args.dpi_ocr_vectoriel,
        tesseract_lang=args.tesseract_lang, paddle_lang=args.paddle_lang,
    )


if __name__ == "__main__":
    main()
