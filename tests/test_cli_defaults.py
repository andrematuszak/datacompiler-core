"""Valeurs par défaut de la commande : rebuilt ; overlay demande --strategy ; clean_overlay obsolète."""

import inspect
import sys

import pytest

from datacompiler import pipeline


@pytest.fixture
def appels(monkeypatch):
    enregistres = []
    monkeypatch.setattr(pipeline, "executer_pipeline", lambda *a, **k: enregistres.append((a, k)))
    monkeypatch.setattr(pipeline, "_configurer_journal_client", lambda: None)
    return enregistres


def _lancer(monkeypatch, *arguments):
    monkeypatch.setattr(sys, "argv", ["datacompiler", "x.pdf", *arguments])
    pipeline.main()


def test_library_default_is_rebuilt():
    assert inspect.signature(pipeline.executer_pipeline).parameters["strategy"].default == "rebuilt"


def test_cli_default_runs_rebuilt(monkeypatch, appels):
    _lancer(monkeypatch)
    assert appels[0][1]["strategy"] == "rebuilt"


@pytest.mark.parametrize("strategie", ["overlay", "rasterized"])
def test_strategy_alone_selects_faithful_pdf(monkeypatch, appels, strategie):
    _lancer(monkeypatch, "--strategy", strategie)
    assert appels[0][1]["strategy"] == strategie


def test_clean_overlay_is_still_accepted_by_cli(monkeypatch, appels):
    _lancer(monkeypatch, "--strategy", "clean_overlay")
    assert appels[0][1]["strategy"] == "clean_overlay"  # redirigé vers rebuilt dans executer_pipeline


def test_faithful_pdf_requires_strategy(monkeypatch, appels, capsys):
    with pytest.raises(SystemExit) as erreur:
        _lancer(monkeypatch, "--format", "faithful-pdf")
    assert erreur.value.code == 2
    assert "requires --strategy" in capsys.readouterr().err
    assert not appels


def test_incompatible_format_and_strategy_is_refused(monkeypatch, appels, capsys):
    with pytest.raises(SystemExit) as erreur:
        _lancer(monkeypatch, "--format", "markdown", "--strategy", "overlay")
    assert erreur.value.code == 2
    assert "does not apply" in capsys.readouterr().err
    assert not appels


@pytest.mark.parametrize("format_sortie, attendu", [("flow-pdf", "flow"), ("markdown", "markdown"), ("rebuilt-pdf", "rebuilt")])
def test_other_formats_unchanged(monkeypatch, appels, format_sortie, attendu):
    _lancer(monkeypatch, "--format", format_sortie)
    assert appels[0][1]["strategy"] == attendu
