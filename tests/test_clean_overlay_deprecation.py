"""`clean_overlay` est obsolète : il redirige vers `rebuilt` avec un avertissement."""

import logging

import pytest

pymupdf = pytest.importorskip("pymupdf")

from datacompiler.backend import resolve_deprecated_strategy
from datacompiler.backend.faithful_pdf import render_faithful_pdf
from datacompiler.model.document import Document, Page, ResolvedContainer
from datacompiler.model.metadata import Metadata
from datacompiler.pipeline import executer_pipeline


def _creer_pdf(chemin):
    document = pymupdf.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((40, 80), "Bonjour le monde", fontsize=14)
    document.save(chemin)
    document.close()


def test_other_strategies_are_unchanged(caplog):
    with caplog.at_level(logging.WARNING):
        for strategy in ("overlay", "rebuilt", "rasterized", "flow"):
            assert resolve_deprecated_strategy(strategy) == strategy
    assert not caplog.records


def test_clean_overlay_resolves_to_rebuilt_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        assert resolve_deprecated_strategy("clean_overlay") == "rebuilt"
    assert "deprecated" in caplog.text


def test_pipeline_runs_rebuilt_for_clean_overlay(tmp_path, caplog):
    source = tmp_path / "essai.pdf"
    _creer_pdf(source)
    with caplog.at_level(logging.WARNING):
        executer_pipeline(str(source), strategy="clean_overlay", ocr_mode="skip")
    assert "deprecated" in caplog.text
    assert (tmp_path / "essai_rebuilt.pdf").exists()
    assert not (tmp_path / "essai_propre.pdf").exists()


def test_direct_faithful_call_still_works_and_warns(tmp_path, caplog):
    source = tmp_path / "essai.pdf"
    _creer_pdf(source)
    document = Document(
        metadata=Metadata(filename="essai.pdf", source_pdf=str(source)),
        pages=[Page(number=1, width=300, height=200, resolved=ResolvedContainer(words=[]))],
    )
    with caplog.at_level(logging.WARNING):
        sortie, _ = render_faithful_pdf(document, str(tmp_path / "sortie.pdf"), strategy="clean_overlay")
    assert "deprecated" in caplog.text
    assert pymupdf.open(sortie).page_count == 1
