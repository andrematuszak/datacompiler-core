"""La commande `datacompiler` n'affiche que la progression, les avertissements et les erreurs."""

import subprocess
import sys
from unittest.mock import Mock

import pytest

pymupdf = pytest.importorskip("pymupdf")


def _creer_pdf(chemin):
    document = pymupdf.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((40, 80), "Bonjour le monde", fontsize=14)
    document.save(chemin)
    document.close()


def test_cli_output_is_minimal(tmp_path):
    source = tmp_path / "essai.pdf"
    _creer_pdf(source)

    resultat = subprocess.run(
        [sys.executable, "-m", "datacompiler.pipeline", str(source), "--ocr-mode", "skip"],
        capture_output=True, text=True, timeout=120,
    )
    sortie = resultat.stdout + resultat.stderr

    assert resultat.returncode == 0, sortie
    assert "Traitement : essai.pdf" in sortie
    assert "Terminé :" in sortie
    # Rien du journal de développement ni du rapport de diagnostic.
    for interdit in ("[1/6]", "[6/6]", "DIAGNOSTIC", "[DUPLICATE]", "Wrote:"):
        assert interdit not in sortie
    assert not list(tmp_path.glob("*.json"))


def test_verbose_option_no_longer_exists(tmp_path):
    resultat = subprocess.run(
        [sys.executable, "-m", "datacompiler.pipeline", str(tmp_path / "x.pdf"), "-v"],
        capture_output=True, text=True, timeout=60,
    )
    assert resultat.returncode == 2


def test_force_ocr_mode_is_rejected_with_an_actionable_message(monkeypatch, capsys):
    from datacompiler import pipeline

    monkeypatch.setattr(sys, "argv", ["datacompiler", "unused.pdf", "--ocr-mode", "force"])

    with pytest.raises(SystemExit) as exc:
        pipeline.main()

    assert exc.value.code == 2
    assert "--ocr-mode force is not implemented" in capsys.readouterr().err


def test_client_progress_logger_configuration_is_idempotent(monkeypatch, capsys):
    from datacompiler import pipeline

    monkeypatch.setattr(pipeline.logging, "basicConfig", Mock())
    logger = pipeline.logging.Logger("datacompiler-test-progress")
    monkeypatch.setattr(pipeline, "progress", logger)
    try:
        pipeline._configurer_journal_client()
        pipeline._configurer_journal_client()
        tagged = [
            handler for handler in logger.handlers
            if getattr(handler, "_datacompiler_client_handler", False)
        ]
        assert len(tagged) == 1
        logger.info("single progress line")
        assert capsys.readouterr().err.count("single progress line") == 1
    finally:
        for handler in tuple(logger.handlers):
            if getattr(handler, "_datacompiler_client_handler", False):
                logger.removeHandler(handler)
                handler.close()
