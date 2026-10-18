from types import SimpleNamespace

import pymupdf
import pytest

from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf
from datacompiler.model.document import Document, Page, ResolvedContainer, Word
from datacompiler.model.geometry import BBox
from datacompiler.model.metadata import Metadata
from datacompiler.translation.editor import _load_layout, _save_layout
from datacompiler.translation.xliff import (
    TranslationUnit,
    XliffTranslation,
    apply_xliff_translation,
)


SOURCE_BBOX = BBox(20, 20, 52, 42)
SOURCE_GLYPH_RECTS = (
    (24.0, 25.0, 28.0, 37.0),
    (36.0, 25.0, 40.0, 37.0),
)
BACKGROUND_RECT = (10.0, 10.0, 100.0, 60.0)


def _write_source_pdf(path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=180, height=120)
    page.draw_rect(pymupdf.Rect(*BACKGROUND_RECT), color=(0, 0, 1), fill=(0.9, 0.9, 0.9))
    for bounds in SOURCE_GLYPH_RECTS:
        page.draw_rect(pymupdf.Rect(*bounds), color=None, fill=(0, 0, 0))
    pdf.save(path)
    pdf.close()


def _source_document(source_path):
    word = Word(
        id=1,
        text="source",
        bbox=SOURCE_BBOX,
        font_size=10,
        source="ocr_vectoriel",
        is_vectorized=True,
    )
    return Document(
        metadata=Metadata(source_pdf=str(source_path), filename="source.pdf"),
        pages=[
            Page(
                number=1,
                width=180,
                height=120,
                resolved=ResolvedContainer(words=[word]),
            )
        ],
    )


def _translated_document(source_path):
    document = _source_document(source_path)
    unit = TranslationUnit(
        id="p1-l1", page=1, word_ids=[1], source="source", block_id="p1-b1",
    )
    application = apply_xliff_translation(
        document,
        XliffTranslation(
            source_language="fr",
            target_language="en",
            units={"p1-l1": TranslationUnit(
                id="p1-l1", page=1, word_ids=[1], source="source",
                target="translated phrase",
            )},
        ),
        expected_units=[unit],
    )
    return application.document


def _assert_glyphs_masked_and_background_kept(pdf_path):
    with pymupdf.open(pdf_path) as rendered:
        page = rendered[0]
        drawing_rects = {
            tuple(round(value, 1) for value in drawing["rect"])
            for drawing in page.get_drawings()
        }
        assert drawing_rects.isdisjoint(SOURCE_GLYPH_RECTS)
        assert BACKGROUND_RECT in drawing_rects
        assert "translated phrase" in page.get_text()


@pytest.mark.parametrize(
    "layout_bbox",
    [
        BBox(70, 70, 145, 98),
        BBox(20, 20, 31, 40),
    ],
    ids=("moved", "resized"),
)
def test_translated_block_uses_immutable_source_mask_geometry(
    tmp_path, layout_bbox,
):
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "rebuilt.pdf"
    _write_source_pdf(source_path)
    document = _translated_document(source_path)
    translated = document.pages[0].resolved.words[0]
    assert translated.source_glyph_bboxes == ((20, 20, 52, 42),)
    document = Document.from_dict(document.to_dict())
    translated = document.pages[0].resolved.words[0]
    translated.bbox = layout_bbox

    render_rebuilt_pdf(document, str(output_path))

    _assert_glyphs_masked_and_background_kept(output_path)


def test_split_manual_block_keeps_source_masks_after_layout_reload(tmp_path):
    source_path = tmp_path / "source.pdf"
    layout_path = tmp_path / "layout.json"
    output_path = tmp_path / "rebuilt.pdf"
    _write_source_pdf(source_path)
    split_document = _translated_document(source_path)
    translated = split_document.pages[0].resolved.words[0]
    translated.text = ""
    translated.resolved_text = ""
    split_word = Word(
        id=2,
        text="translated phrase",
        resolved_text="translated phrase",
        bbox=BBox(70, 70, 145, 98),
        font_size=10,
        source="manual_translation",
        reconstructed=True,
        source_glyph_bboxes=translated.source_glyph_bboxes,
    )
    split_word._translation_unit_id = "manual-p1-1"
    split_word._translation_block_id = "manual-p1-1"
    split_word._translation_segments = []
    split_document.pages[0].resolved.words.append(split_word)
    _save_layout(SimpleNamespace(document=split_document), layout_path)

    reloaded_document = _translated_document(source_path)
    _load_layout(SimpleNamespace(document=reloaded_document), layout_path)
    restored_split = next(
        word for word in reloaded_document.pages[0].resolved.words
        if getattr(word, "_translation_unit_id", None) == "manual-p1-1"
    )
    assert restored_split.source_glyph_bboxes == ((20, 20, 52, 42),)

    render_rebuilt_pdf(reloaded_document, str(output_path))

    _assert_glyphs_masked_and_background_kept(output_path)
