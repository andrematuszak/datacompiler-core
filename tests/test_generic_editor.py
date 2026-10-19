from types import SimpleNamespace

import pymupdf
import pytest

from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf
from datacompiler.model.document import Document, Page, ResolvedContainer, Word
from datacompiler.model.geometry import BBox
from datacompiler.model.metadata import Metadata
from datacompiler.translation.editor import (
    _apply_editor_text,
    _load_layout,
    _prepare_generic_words,
    _save_layout,
)


def _document(source_path, word):
    return Document(
        metadata=Metadata(source_pdf=str(source_path), filename="source.pdf"),
        pages=[
            Page(
                number=1,
                width=200,
                height=120,
                resolved=ResolvedContainer(words=[word]),
            )
        ],
    )


def test_generic_word_ids_are_stable_and_do_not_reorder_words(tmp_path):
    source_path = tmp_path / "source.pdf"
    first = Word(id=7, text="first", bbox=BBox(10, 20, 40, 32), source="native")
    second = Word(id=8, text="second", bbox=BBox(50, 20, 90, 32), source="native")
    document = _document(source_path, first)
    document.pages[0].resolved.words.append(second)

    words = _prepare_generic_words(document)
    first_ids = [word._translation_unit_id for word in words]
    assert first_ids == ["generic-p1-w7", "generic-p1-w8"]
    assert _prepare_generic_words(document) == words
    assert [word._translation_unit_id for word in words] == first_ids
    assert document.pages[0].resolved.words == [first, second]


def test_generic_native_text_edit_roundtrips_sidecar_and_renders(tmp_path):
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "rebuilt.pdf"
    layout_path = tmp_path / "layout.json"
    pdf = pymupdf.open()
    page = pdf.new_page(width=200, height=120)
    page.insert_text((20, 40), "Original wording", fontsize=12)
    pdf.save(source_path)
    pdf.close()

    original = Word(
        id=1, text="Original wording", bbox=BBox(20, 26, 112, 43),
        font="Helvetica", font_size=12, source="native",
    )
    document = _document(source_path, original)
    following = Word(
        id=2, text="Following text", bbox=BBox(20, 50, 100, 66),
        font="Helvetica", font_size=12, source="native",
    )
    document.pages[0].resolved.words.append(following)
    _prepare_generic_words(document)
    _apply_editor_text(original, "Edited wording", generic=True)
    original.bbox = BBox(50, 70, 150, 92)
    original.font_size = 14
    original.bold = True
    _save_layout(SimpleNamespace(document=document), layout_path)

    reloaded_word = Word(
        id=1, text="Original wording", bbox=BBox(20, 26, 112, 43),
        font="Helvetica", font_size=12, source="native",
    )
    reloaded = _document(source_path, reloaded_word)
    reloaded_following = Word(
        id=2, text="Following text", bbox=BBox(20, 50, 100, 66),
        font="Helvetica", font_size=12, source="native",
    )
    reloaded.pages[0].resolved.words.append(reloaded_following)
    _prepare_generic_words(reloaded)
    _load_layout(SimpleNamespace(document=reloaded), layout_path)

    assert reloaded_word._translation_unit_id == "generic-p1-w1"
    assert reloaded_word.text == "Original wording"
    assert reloaded_word.resolved_text == "Edited wording"
    assert reloaded_word.bbox == BBox(50, 70, 150, 92)
    assert reloaded_word.font_size == 14
    assert reloaded_word.bold is True
    assert reloaded.pages[0].resolved.words == [reloaded_word, reloaded_following]
    render_rebuilt_pdf(reloaded, str(output_path))

    with pymupdf.open(output_path) as rendered:
        text = rendered[0].get_text()
    assert "Edited wording" in text
    assert "Original wording" not in text


@pytest.mark.parametrize(
    ("replacement", "layout_bbox"),
    [
        ("replacement", BBox(20, 20, 52, 42)),
        ("recognized", BBox(70, 70, 110, 92)),
    ],
    ids=("text-replacement", "moved-with-original-text"),
)
def test_generic_vector_edit_masks_recognized_source_glyphs(
    tmp_path, replacement, layout_bbox,
):
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "rebuilt.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=180, height=120)
    page.draw_rect(
        pymupdf.Rect(10, 10, 100, 60), color=(0, 0, 1), fill=(0.9, 0.9, 0.9),
    )
    source_glyph_rects = ((24, 25, 28, 37), (36, 25, 40, 37))
    for rect in source_glyph_rects:
        page.draw_rect(pymupdf.Rect(*rect), color=None, fill=(0, 0, 0))
    pdf.save(source_path)
    pdf.close()

    word = Word(
        id=1, text="recognized", bbox=BBox(20, 20, 52, 42),
        font_size=10, source="ocr_vectoriel", is_vectorized=True,
    )
    document = _document(source_path, word)
    _prepare_generic_words(document)
    word.resolved_text = replacement
    word.bbox = layout_bbox
    render_rebuilt_pdf(document, str(output_path))

    with pymupdf.open(output_path) as rendered:
        page = rendered[0]
        drawing_rects = {
            tuple(round(value, 1) for value in drawing["rect"])
            for drawing in page.get_drawings()
        }
        assert drawing_rects.isdisjoint(source_glyph_rects)
        assert (10.0, 10.0, 100.0, 60.0) in drawing_rects
        assert replacement in page.get_text()
