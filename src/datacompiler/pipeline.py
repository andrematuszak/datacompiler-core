"""Orchestrateur du moteur : frontend (extraction, diagnostic, OCR),
compile (arbitrage native/OCR), backend (rendu)."""

import argparse
import logging
from pathlib import Path

from datacompiler.frontend.diagnostic.vector_text import zones_texte_vectorise_probable
from datacompiler.model.document import Document
from datacompiler.frontend.extract import extraire
from datacompiler.frontend import diagnostiquer, report as diagnostic_report
from datacompiler.frontend.ocr.paddle import PaddleOCRBackend
from datacompiler.frontend.ocr.vector_zones import recuperer_texte_vectorise
from datacompiler.compile import resoudre
from datacompiler.backend import EXTENSIONS, FORMATS
from datacompiler.backend.faithful_pdf import render_faithful_pdf
from datacompiler.backend.flow_pdf import render_flow_pdf
from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf

logger = logging.getLogger(__name__)


def executer_pipeline(pdf_path, strategy="overlay", sauver_json=True,
                      dpi=300, dpi_ocr_vectoriel=300, paddle_lang="fr",
                      ocr_mode="auto"):

    """
    Exécute le pipeline de compilation de PDF en 5 étapes claires :
      [1/5] Extraction du texte natif
      [2/5] Diagnostic de la page
      [3/5] Enrichissement OCR
      [4/5] Compilation et résolution
      [5/5] Rendu final

    ---
    Note d'architecture (OCR pleine page) :
      L'étape d'OCR pleine page globale (anciennement 'ocraliser') a été retirée
      du flux actif. Contrairement à l'OCR ciblé (qui insère directement les
      mots vectorisés dans page.native.words pour combler des trous géométriques
      délimités), l'OCR pleine page passe par un processus d'alignement global
      (diff de séquence + interpolation de bbox via alignment.py et
      conflict_resolution.py).
      
      Tant que l'algorithme d'alignement n'est pas pleinement validé sur des
      cas réels sans régression de duplication de mots, l'OCR pleine page
      est désactivé pour préserver la précision du texte natif.
    ---

    dpi : DPI du RENDU final (faithful/rasterized) -- indépendant de l'OCR,
    garder bas pour limiter la taille de fichier.
    dpi_ocr_vectoriel : DPI dédié à l'OCR ciblé des zones de texte
    vectorisé (recuperer_texte_vectorise). Découplé de `dpi`, mais laissé
    à 300 PAR DÉFAUT.
    paddle_lang : Code langue ISO 639-1 pour PaddleOCR (ex. "fr").
    """
    """
    ocr_mode : 
      - "auto"   : Fait confiance au diagnostic (pleine page si recommend_ocr, vectoriel si zones détectées)
      - "force"  : Force l'OCR pleine page quelle que soit la recommandation
      - "skip"   : Désactive tout OCR (pleine page et zones vectorielles)
      - "vector" : Exécute uniquement l'OCR ciblé sur zones vectorielles
    """
    pdf_path = str(Path(pdf_path).resolve())
    logger.info("[1/5] Extraction : %s", pdf_path)
    doc = extraire(Document(), pdf_path)

    logger.info("[2/5] Diagnostic...")
    diagnostiquer(doc)
    diagnostic_report.afficher(doc)

    logger.debug(
        "Diagnostic terminé. Recommandation OCR pleine page : %s (désactivée du flux)",
        getattr(doc.diagnostic, "recommend_ocr", False)
    )


    logger.info("[3/5] Traitement OCR...")

    if ocr_mode == "skip":
        logger.info("      [OCR] Mode 'skip' : Aucun OCR exécuté.")
    else:
        # A) Branche OCR Pleine Page
        do_full_ocr = (ocr_mode == "force") or (
            ocr_mode == "auto" and getattr(doc.diagnostic, "recommend_ocr", False)
        )
        if do_full_ocr:
            logger.info("      [OCR] Pleine page activé (recommend_ocr=%s, mode=%s)...",
                        getattr(doc.diagnostic, "recommend_ocr", False), ocr_mode)
            # ocraliser(doc, pdf_path, backend_name="paddle", lang=paddle_lang)
        else:
            logger.info("      [OCR] Pleine page non nécessaire.")

        # B) Branche OCR Ciblé (Zones vectorielles)
        if ocr_mode in ("auto", "vector"):
            logger.info("      [OCR] Vérification des zones de texte vectorisé...")
            backend_paddle = PaddleOCRBackend(lang=paddle_lang, dpi=dpi_ocr_vectoriel)
            recuperer_texte_vectorise(
                doc, pdf_path, backend_paddle,
                lang=paddle_lang, dpi=dpi_ocr_vectoriel,
            )

    logger.info("[4/5] Compilation...")
    resoudre(doc)

    base = str(Path(pdf_path).with_suffix(""))
    logger.info("[5/5] Rendu (stratégie : %s)...", strategy)
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
                        help="DPI dédié à l'OCR ciblé des zones de texte vectorisé (découplé de --dpi)")
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
        paddle_lang=args.paddle_lang
    )


if __name__ == "__main__":
    main()
