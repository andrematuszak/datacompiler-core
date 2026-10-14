"""Synthetic Paddle-to-clean-overlay regression for issue #6/#18."""

import pymupdf
from PIL import Image

from datacompiler.backend.faithful_pdf import render_faithful_pdf
from datacompiler.frontend.extract.extract_pymupdf import rendre_zone_image
from datacompiler.frontend.ocr.paddle import PaddleOCRBackend
from datacompiler.model.document import Document as ModelDocument
from datacompiler.model.document import Page as ModelPage, ResolvedContainer
from datacompiler.model.metadata import Metadata
from datacompiler.model.geometry import BBox


class SimulatedPaddle:
    def ocr(self, _image):
        # PaddleOCR 3-style output. Empty dt_polys with populated rec_boxes
        # reproduces the response shape that previously yielded zero words.
        return [{
            "rec_texts": ["Alpha", "Beta"],
            "rec_scores": [0.95, 0.91],
            "dt_polys": [],
            "rec_boxes": [[20, 30, 55, 45], [70, 30, 100, 45]],
        }]


def test_paddle_words_survive_clean_overlay_once_with_page_offset(tmp_path, monkeypatch):
    source_path = tmp_path / "synthetic.pdf"
    output_path = tmp_path / "synthetic_clean.pdf"
    source = pymupdf.open()
    source.new_page(width=200, height=100)
    source.save(source_path)
    source.close()

    monkeypatch.setattr(PaddleOCRBackend, "_engine_instances", {})
    monkeypatch.setattr(PaddleOCRBackend, "_get_engine", classmethod(lambda cls, lang="fr", **kwargs: SimulatedPaddle()))
    backend = object.__new__(PaddleOCRBackend)
    backend.lang = "fr"
    backend.dpi = 72
    backend.extra_kwargs = {}
    words = backend.ocraliser_zone(
        Image.new("RGB", (160, 80), "white"), offset=(10, 12), dpi=72
    )

    assert [word.text for word in words] == ["Alpha", "Beta"]
    assert [(word.bbox.x0, word.bbox.y0) for word in words] == [(30, 42), (80, 42)]

    document = ModelDocument(
        metadata=Metadata(filename="synthetic.pdf", source_pdf=str(source_path)),
        pages=[ModelPage(
            number=1,
            width=200,
            height=100,
            resolved=ResolvedContainer(words=words),
        )],
    )
    _, report = render_faithful_pdf(
        document, str(output_path), strategy="clean_overlay"
    )

    rendered = pymupdf.open(output_path)
    try:
        extracted = rendered[0].get_text("words")
    finally:
        rendered.close()

    assert report["mots_inseres"] == 2
    assert [word[4] for word in extracted] == ["Alpha", "Beta"]
    assert len(extracted) == 2
    # Les zones d'extraction sont séparées : aucune sélection ne doit couvrir
    # simultanément les deux mots, et les positions doivent garder l'offset.
    assert extracted[0][2] < extracted[1][0]
    assert abs(extracted[0][0] - 30) < 1
    assert abs(extracted[1][0] - 80) < 1


def test_fractional_crop_uses_actual_pixmap_origin_for_page_coordinates(monkeypatch):
    page = pymupdf.open()
    page_obj = page.new_page(width=200, height=100)
    crop_bbox = BBox(10.13, 12.27, 40.31, 30.42)
    image, scale, offset = rendre_zone_image(page_obj, crop_bbox, dpi=300)

    backend = object.__new__(PaddleOCRBackend)
    backend.lang = "fr"
    backend.dpi = 300
    backend.extra_kwargs = {}
    monkeypatch.setattr(backend, "_extraire", lambda _image: [{
        "text": "mot", "confidence": 0.9, "x0": 0, "y0": 0, "x1": 12, "y1": 12,
    }])
    word = backend.ocraliser_zone(image, offset=offset, dpi=300)[0]

    assert abs(word.bbox.x0 - offset[0]) < 1e-9
    assert abs(word.bbox.y0 - offset[1]) < 1e-9
    # The actual pixmap origin is pixel-aligned and therefore differs from
    # the requested fractional clip origin in at least one axis.
    assert offset != (crop_bbox.x0, crop_bbox.y0)
    assert abs(word.bbox.x1 - (offset[0] + 12 / scale)) < 1e-9
    page.close()
