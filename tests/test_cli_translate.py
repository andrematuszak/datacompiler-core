"""--target-lang déclenche la traduction ; --no-translate la désactive toujours."""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from datacompiler import pipeline
from datacompiler import translation


@pytest.fixture
def espions(monkeypatch):
    traductions = []
    edits = []
    monkeypatch.setattr(pipeline, "executer_pipeline", lambda *a, **k: "document-factice")
    monkeypatch.setattr(
        pipeline, "traduire_document",
        lambda *a, **kwargs: traductions.append((a, kwargs))
        or "sortie_en_rebuilt.pdf",
    )
    monkeypatch.setattr(
        translation, "edit_document_pdf",
        lambda *a, **kwargs: edits.append((a, kwargs)) or "document-factice",
    )
    monkeypatch.setattr(pipeline, "_configurer_journal_client", lambda: None)
    return traductions, edits


def _lancer(monkeypatch, *arguments):
    monkeypatch.setattr(sys, "argv", ["datacompiler", "x.pdf", *arguments])
    pipeline.main()


def test_no_target_lang_means_no_translation(monkeypatch, espions):
    _lancer(monkeypatch)
    assert espions == ([], [])


def test_target_lang_triggers_translation(monkeypatch, espions):
    _lancer(monkeypatch, "--target-lang", "en", "--source-lang", "fr")
    assert espions == ([
        (("document-factice", "x.pdf", "en", "fr"), {"edit": False}),
    ], [])


def test_target_lang_uses_detected_page_language_when_source_is_not_overridden(
    monkeypatch, espions
):
    document = SimpleNamespace(
        pages=[
            SimpleNamespace(language=SimpleNamespace(language="pl"))
        ]
    )
    monkeypatch.setattr(pipeline, "executer_pipeline", lambda *a, **k: document)

    _lancer(monkeypatch, "--target-lang", "en")

    assert espions[0][0][0][3] == "pl"


def test_no_translate_wins_over_target_lang(monkeypatch, espions):
    _lancer(monkeypatch, "--target-lang", "en", "--no-translate")
    assert espions == ([], [])


def test_no_translate_alone_is_accepted(monkeypatch, espions):
    _lancer(monkeypatch, "--no-translate")
    assert espions == ([], [])


def test_editor_without_target_language_opens_generic_editor(monkeypatch, espions):
    _lancer(monkeypatch, "--editor")
    assert espions == (
        [],
        [(("document-factice", "x_rebuilt.pdf"), {})],
    )


def test_editor_with_target_language_uses_translation_editor(monkeypatch, espions):
    _lancer(monkeypatch, "--target-lang", "en", "--editor")
    assert espions == ([
        (("document-factice", "x.pdf", "en", None), {"edit": True}),
    ], [])


def test_editor_with_no_translate_uses_generic_editor(monkeypatch, espions):
    _lancer(monkeypatch, "--target-lang", "en", "--no-translate", "--editor")
    assert espions == (
        [],
        [(("document-factice", "x_rebuilt.pdf"), {})],
    )


pymupdf = pytest.importorskip("pymupdf")


def _creer_pdf(chemin):
    document = pymupdf.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((40, 80), "Bonjour le monde", fontsize=14)
    document.save(chemin)
    document.close()


def test_translate_document_end_to_end_with_fake_provider(tmp_path, monkeypatch):
    from datacompiler.translation import import_xliff
    from datacompiler.translation import providers
    from datacompiler.translation.xliff import write_xliff_translation

    def faux_moteur(source, sortie, **_):
        traduction = import_xliff(source)
        for unite in traduction.units.values():
            unite.target = "EN: " + unite.source
        write_xliff_translation(traduction, sortie)
        return traduction

    monkeypatch.setattr(providers, "translate_xliff_file", faux_moteur)
    source = tmp_path / "essai.pdf"
    _creer_pdf(source)
    document = pipeline.executer_pipeline(str(source), strategy="rebuilt", ocr_mode="skip")

    sortie = pipeline.traduire_document(document, str(source), "en", "fr")

    assert sortie == str(tmp_path / "essai_en_rebuilt.pdf")
    assert (tmp_path / "essai.en.xlf").exists()
    assert "EN: Bonjour le monde" in pymupdf.open(sortie)[0].get_text()


def test_missing_deepl_key_is_reported_without_traceback(tmp_path):
    source = tmp_path / "essai.pdf"
    _creer_pdf(source)
    environnement = {k: v for k, v in os.environ.items() if k != "DEEPL_AUTH_KEY"}
    resultat = subprocess.run(
        [sys.executable, "-m", "datacompiler.pipeline", str(source), "--ocr-mode", "skip",
         "--target-lang", "en", "--source-lang", "fr"],
        capture_output=True, text=True, timeout=120, env=environnement,
    )
    assert resultat.returncode == 1
    assert "Translation failed" in resultat.stderr
    assert "Traceback" not in resultat.stderr
    assert (tmp_path / "essai_rebuilt.pdf").exists()
