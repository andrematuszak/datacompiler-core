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
from datacompiler.translation.xliff import TranslationUnit, XliffTranslation, apply_xliff_translation
from datacompiler.utils.colors import normalize_hex_color


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


def _assert_text_color(pdf_path, text, expected_rgb):
    with pymupdf.open(pdf_path) as rendered:
        spans = [
            span
            for block in rendered[0].get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
            if text in span["text"]
        ]
    assert spans
    assert all(span["color"] == expected_rgb for span in spans)


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
    original.editor_color = normalize_hex_color("#c28")
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
    assert reloaded_word.editor_color == "#CC2288"
    assert reloaded.pages[0].resolved.words == [reloaded_word, reloaded_following]
    render_rebuilt_pdf(reloaded, str(output_path))

    with pymupdf.open(output_path) as rendered:
        text = rendered[0].get_text()
    assert "Edited wording" in text
    assert "Original wording" not in text
    _assert_text_color(output_path, "Edited wording", 0xCC2288)


def test_color_override_is_independent_from_source_glyph_sample(tmp_path):
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "rebuilt.pdf"
    layout_path = tmp_path / "translated.layout.json"
    pdf = pymupdf.open()
    page = pdf.new_page(width=180, height=120)
    page.draw_rect(pymupdf.Rect(20, 20, 55, 44), color=None, fill=(0.1, 0.2, 0.3))
    pdf.save(source_path)
    pdf.close()

    source = Word(
        id=1, text="source", bbox=BBox(20, 20, 55, 44),
        source="native", font_size=12, color="#19334D",
    )
    base = _document(source_path, source)
    unit = TranslationUnit(
        id="p1-l1", page=1, word_ids=[1], source="source", block_id="p1-b1",
    )
    translated_document = apply_xliff_translation(
        base,
        XliffTranslation(
            source_language="fr",
            target_language="en",
            units={"p1-l1": TranslationUnit(
                id="p1-l1", page=1, word_ids=[1], source="source", target="translated",
            )},
        ),
        expected_units=[unit],
    ).document
    translated = translated_document.pages[0].resolved.words[0]
    translated.editor_color = "#0A7BCD"
    translated.source_glyph_bboxes = ((20, 20, 55, 44),)
    _save_layout(SimpleNamespace(document=translated_document), layout_path)

    reloaded_document = apply_xliff_translation(
        base,
        XliffTranslation(
            source_language="fr",
            target_language="en",
            units={"p1-l1": TranslationUnit(
                id="p1-l1", page=1, word_ids=[1], source="source", target="translated",
            )},
        ),
        expected_units=[unit],
    ).document
    _load_layout(SimpleNamespace(document=reloaded_document), layout_path)
    translated = reloaded_document.pages[0].resolved.words[0]
    assert translated.editor_color == "#0A7BCD"

    render_rebuilt_pdf(
        reloaded_document, str(output_path), source_pdf=str(source_path),
    )

    _assert_text_color(output_path, "translated", 0x0A7BCD)


def test_manual_block_color_persists_and_renders(tmp_path):
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "rebuilt.pdf"
    layout_path = tmp_path / "manual.layout.json"
    pdf = pymupdf.open()
    pdf.new_page(width=180, height=100)
    pdf.save(source_path)
    pdf.close()

    manual = Word(
        id=1, text="Manual label", resolved_text="Manual label",
        bbox=BBox(20, 20, 110, 38), source="manual_translation",
        font_size=12, reconstructed=True, editor_color="#2A9944",
    )
    manual._translation_unit_id = "manual-p1-1"
    manual._translation_segments = []
    document = _document(source_path, manual)
    _save_layout(SimpleNamespace(document=document), layout_path)

    restored = Word(
        id=1, text="Manual label", resolved_text="Manual label",
        bbox=BBox(20, 20, 110, 38), source="manual_translation",
        font_size=12, reconstructed=True,
    )
    restored._translation_unit_id = "manual-p1-1"
    restored._translation_segments = []
    reloaded = _document(source_path, restored)
    _load_layout(SimpleNamespace(document=reloaded), layout_path)
    assert restored.editor_color == "#2A9944"

    render_rebuilt_pdf(reloaded, str(output_path))

    _assert_text_color(output_path, "Manual label", 0x2A9944)


def test_link_token_color_does_not_recolor_neighboring_words(tmp_path):
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "rebuilt.pdf"
    pdf = pymupdf.open()
    pdf.new_page(width=240, height=100)
    pdf.save(source_path)
    pdf.close()

    words = [
        Word(id=1, text="Voir", bbox=BBox(20, 20, 44, 36), font_size=12, source="native"),
        Word(
            id=2, text="impots.gouv.fr", bbox=BBox(49, 20, 127, 36),
            font_size=12, source="native", editor_color="#3657C8",
        ),
        Word(id=3, text="maintenant", bbox=BBox(132, 20, 197, 36), font_size=12, source="native"),
    ]
    document = _document(source_path, words[0])
    document.pages[0].resolved.words.extend(words[1:])
    _prepare_generic_words(document)
    render_rebuilt_pdf(document, str(output_path))

    _assert_text_color(output_path, "Voir", 0x000000)
    _assert_text_color(output_path, "impots.gouv.fr", 0x3657C8)
    _assert_text_color(output_path, "maintenant", 0x000000)


def test_invalid_editor_color_is_rejected_when_loading_sidecar(tmp_path):
    from datacompiler.translation.editor import _load_layout
    import json

    source_path = tmp_path / "source.pdf"
    word = Word(id=1, text="source", bbox=BBox(10, 20, 50, 32), source="native")
    document = _document(source_path, word)
    _prepare_generic_words(document)
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(json.dumps({
        "schema_version": 1,
        "units": {
            "generic-p1-w1": {
                "page": 1, "generic": True, "base_text": "source",
                "text": "source", "bbox": [10, 20, 50, 32],
                "editor_color": "not-a-color",
            },
        },
    }))

    with pytest.raises(ValueError, match="Invalid color"):
        _load_layout(SimpleNamespace(document=document), layout_path)


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
