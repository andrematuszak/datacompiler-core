"""Synthetic Paddle-to-clean-overlay regression for issue #6/#18."""

import pymupdf
from PIL import Image

from datacompiler.backend.faithful_pdf import render_faithful_pdf
from datacompiler.frontend.ocr.paddle import PaddleOCRBackend
from datacompiler.model.document import Document as ModelDocument
from datacompiler.model.document import Page as ModelPage, ResolvedContainer
from datacompiler.model.metadata import Metadata


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

    monkeypatch.setattr(PaddleOCRBackend, "_engine_instance", SimulatedPaddle())
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
