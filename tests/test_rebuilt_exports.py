"""Behavior checks for the flowing HTML and DOCX exporters."""

import zipfile

import pytest

from datacompiler.backend.rebuilt_html import render_html
from datacompiler.model.document import (
    Document,
    Page,
    ResolvedContainer,
    TableElement,
    Word,
)
from datacompiler.model.geometry import BBox


def _document_with_special_text():
    word = Word(id=1, text='A < B & "C"', bbox=BBox(10, 10, 80, 24))
    table = TableElement(
        id=1,
        bbox=BBox(10, 30, 100, 60),
        rows=[["<cell>", None], ["A & B", '"quoted"']],
    )
    return Document(pages=[Page(
        number=1,
        width=200,
        height=100,
        resolved=ResolvedContainer(words=[word], tables=[table]),
    )])


def test_html_export_escapes_text_and_table_cells():
    html = render_html(_document_with_special_text())

    assert "A &lt; B &amp; &quot;C&quot;" in html
    assert "&lt;cell&gt;" in html
    assert "A &amp; B" in html
    assert "<script>" not in html


def test_docx_export_contains_text_and_table_cells(tmp_path):
    pytest.importorskip("docx")
    from datacompiler.backend.rebuilt_docx import render_docx

    output = tmp_path / "nested" / "document.docx"

    assert render_docx(_document_with_special_text(), str(output)) == str(output)
    assert output.is_file()
    with zipfile.ZipFile(output) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert "A &lt; B &amp; \"C\"" in xml
    assert "&lt;cell&gt;" in xml
    assert "A &amp; B" in xml
