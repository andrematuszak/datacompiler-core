"""Mesure reproductible d'un petit corpus PDF sans enregistrer son texte.

Usage:
    python tools/pdf_corpus_report.py document1.pdf document2.pdf --output rapport.json

Le rapport conserve le nom du fichier, son SHA-256, des mesures par page et
les alertes géométriques. Aucun texte extrait n'est écrit dans le rapport.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pdfplumber


def evaluer_pdf(path: Path) -> dict:
    debut = time.perf_counter()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pages = []

    with pdfplumber.open(path) as pdf:
        for numero, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(return_chars=True)
            invalides = []
            debordements = 0

            for word in words:
                x0, top, x1, bottom = (
                    word["x0"], word["top"], word["x1"], word["bottom"]
                )
                if (
                    x0 < 0
                    or top < 0
                    or x1 > page.width + 0.5
                    or bottom > page.height + 0.5
                    or x1 <= x0
                    or bottom <= top
                ):
                    invalides.append("outside_page" if x0 < 0 or top < 0 or x1 > page.width + 0.5 or bottom > page.height + 0.5 else "degenerate")

                chars = word.get("chars", [])
                if chars and (
                    min(c["x0"] for c in chars) < x0 - 0.02
                    or min(c["top"] for c in chars) < top - 0.02
                    or max(c["x1"] for c in chars) > x1 + 0.02
                    or max(c["bottom"] for c in chars) > bottom + 0.02
                ):
                    debordements += 1

            pages.append(
                {
                    "page": numero,
                    "width_pt": round(page.width, 2),
                    "height_pt": round(page.height, 2),
                    "char_count": len(page.chars),
                    "word_count": len(words),
                    "invalid_bbox_count": len(invalides),
                    "degenerate_bbox_count": invalides.count("degenerate"),
                    "out_of_page_bbox_count": invalides.count("outside_page"),
                    "word_boxes_not_enclosing_chars": debordements,
                }
            )

    total_words = sum(page["word_count"] for page in pages)
    total_invalides = sum(page["invalid_bbox_count"] for page in pages)
    if not pages:
        severity = "critical"
    elif total_invalides:
        severity = "medium"
    elif not total_words:
        severity = "high"
    else:
        severity = "none"

    return {
        "file": path.name,
        "sha256": digest,
        "page_count": len(pages),
        "word_count": total_words,
        "elapsed_seconds": round(time.perf_counter() - debut, 4),
        "severity": severity,
        "pages": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="+", type=Path, help="PDF à mesurer")
    parser.add_argument("--output", type=Path, help="Écrire le rapport JSON à cet emplacement")
    args = parser.parse_args()

    rapport = {
        "schema_version": 1,
        "measurements": [evaluer_pdf(path) for path in args.pdf],
    }
    contenu = json.dumps(rapport, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(contenu, encoding="utf-8")
    else:
        print(contenu, end="")


if __name__ == "__main__":
    main()
