from types import SimpleNamespace

import pymupdf
import pytest

from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf
from datacompiler.model.document import Document, Page, ResolvedContainer, Word
from datacompiler.model.geometry import BBox
from datacompiler.model.metadata import Metadata
from datacompiler.translation.editor import (
    _align_words,
    _load_layout,
    _replace_word_with_blocks,
    _save_layout,
)
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
    page = split_document.pages[0]
    split_words = []
    for index, (text, bounds) in enumerate((
        ("translated", BBox(70, 70, 105, 98)),
        ("phrase", BBox(105, 70, 145, 98)),
    ), start=1):
        split_word = Word(
            id=index + 1,
            text=text,
            resolved_text=text,
            bbox=bounds,
            font_size=10,
            source="manual_translation",
            reconstructed=True,
            source_glyph_bboxes=translated.source_glyph_bboxes,
        )
        split_word._translation_unit_id = f"manual-p1-{index}"
        split_word._translation_block_id = split_word._translation_unit_id
        split_word._translation_segments = []
        split_words.append(split_word)
    tombstones = {
        "p1-l1": {
            "page": 1,
            "source": "source",
            "text": "",
            "bbox": [20, 20, 52, 42],
            "source_glyph_bboxes": [[20, 20, 52, 42]],
            "font_size": 10,
            "deleted": True,
            "split_into": [word._translation_unit_id for word in split_words],
        }
    }
    page._translation_layout_tombstones = tombstones
    _replace_word_with_blocks(page, [translated], translated, split_words)
    _save_layout(SimpleNamespace(document=split_document), layout_path)

    reloaded_document = _translated_document(source_path)
    _load_layout(SimpleNamespace(document=reloaded_document), layout_path)
    reloaded_page = reloaded_document.pages[0]
    assert [
        word._translation_unit_id for word in reloaded_page.resolved.words
        if word.source == "manual_translation"
    ] == ["manual-p1-1", "manual-p1-2"]
    assert all(
        word.source_glyph_bboxes == ((20, 20, 52, 42),)
        for word in reloaded_page.resolved.words
        if word.source == "manual_translation"
    )

    render_rebuilt_pdf(reloaded_document, str(output_path))

    with pymupdf.open(output_path) as rendered:
        page = rendered[0]
        drawing_rects = {
            tuple(round(value, 1) for value in drawing["rect"])
            for drawing in page.get_drawings()
        }
        assert drawing_rects.isdisjoint(SOURCE_GLYPH_RECTS)
        assert BACKGROUND_RECT in drawing_rects
        page_text = page.get_text()
        assert "translated" in page_text
        assert "phrase" in page_text
        assert "source" not in page_text


def test_split_blocks_replace_original_at_its_reading_order_position():
    before = Word(id=1, text="before", source="xliff_translation")
    original = Word(id=2, text="original", source="xliff_translation")
    after = Word(id=3, text="after", source="xliff_translation")
    page = Page(
        number=1,
        width=180,
        height=120,
        resolved=ResolvedContainer(words=[before, original, after]),
    )
    editor_words = [before, original, after]
    first = Word(id=4, text="first", source="manual_translation")
    second = Word(id=5, text="second", source="manual_translation")

    _replace_word_with_blocks(page, editor_words, original, [first, second])

    assert page.resolved.words == [before, first, second, after]
    assert editor_words == [before, first, second, after]


def test_deleted_translation_masks_glyphs_and_survives_layout_reload(tmp_path):
    source_path = tmp_path / "source.pdf"
    layout_path = tmp_path / "layout.json"
    output_path = tmp_path / "rebuilt.pdf"
    _write_source_pdf(source_path)
    document = _translated_document(source_path)
    translated = document.pages[0].resolved.words[0]
    translated._translation_deleted = True
    _save_layout(SimpleNamespace(document=document), layout_path)

    reloaded_document = _translated_document(source_path)
    _load_layout(SimpleNamespace(document=reloaded_document), layout_path)
    restored = reloaded_document.pages[0].resolved.words[0]
    assert restored._translation_deleted is True
    assert restored.resolved_text == "translated phrase"

    render_rebuilt_pdf(reloaded_document, str(output_path))

    with pymupdf.open(output_path) as rendered:
        page = rendered[0]
        drawing_rects = {
            tuple(round(value, 1) for value in drawing["rect"])
            for drawing in page.get_drawings()
        }
        assert drawing_rects.isdisjoint(SOURCE_GLYPH_RECTS)
        assert BACKGROUND_RECT in drawing_rects
        assert "translated phrase" not in page.get_text()


@pytest.mark.parametrize(
    ("axis", "anchor", "expected"),
    [
        ("horizontal", "left", BBox(100, 20, 120, 40)),
        ("horizontal", "center", BBox(110, 20, 130, 40)),
        ("horizontal", "right", BBox(120, 20, 140, 40)),
        ("vertical", "top", BBox(10, 200, 30, 220)),
        ("vertical", "center", BBox(10, 210, 30, 230)),
        ("vertical", "bottom", BBox(10, 220, 30, 240)),
    ],
)
def test_alignment_uses_last_selected_reference_without_resizing_or_reordering(
    axis, anchor, expected,
):
    first = Word(id=1, text="first", bbox=BBox(10, 20, 30, 40))
    reference = Word(id=2, text="reference", bbox=BBox(100, 200, 140, 240))
    reading_order = [first, reference]
    page = Page(
        number=1,
        width=180,
        height=120,
        resolved=ResolvedContainer(words=reading_order),
    )
    original_reference_box = BBox(100, 200, 140, 240)

    _align_words([first, reference], reference, axis, anchor)

    assert first.bbox == expected
    assert (first.bbox.x1 - first.bbox.x0, first.bbox.y1 - first.bbox.y0) == (20, 20)
    assert reference.bbox == original_reference_box
    assert page.resolved.words == [first, reference]


def test_alignment_geometry_persists_through_layout_sidecar(tmp_path):
    source_path = tmp_path / "source.pdf"
    layout_path = tmp_path / "layout.json"
    _write_source_pdf(source_path)
    document = _translated_document(source_path)
    translated = document.pages[0].resolved.words[0]
    translated.bbox = BBox(70, 70, 120, 90)
    _save_layout(SimpleNamespace(document=document), layout_path)

    reloaded = _translated_document(source_path)
    _load_layout(SimpleNamespace(document=reloaded), layout_path)

    assert reloaded.pages[0].resolved.words[0].bbox == BBox(70, 70, 120, 90)
