"""Le JSON intermédiaire ne doit pas être écrit par défaut."""

import inspect
import logging
import sys
from types import SimpleNamespace

from datacompiler import pipeline


def test_json_is_disabled_by_default_in_library():
    default = inspect.signature(pipeline.executer_pipeline).parameters["sauver_json"].default
    assert default is False


def test_force_ocr_mode_fails_clearly_until_full_page_ocr_is_supported():
    try:
        pipeline.executer_pipeline("unused.pdf", ocr_mode="force")
    except NotImplementedError as exc:
        assert "Full-page OCR is not implemented" in str(exc)
    else:
        raise AssertionError("force OCR must not silently continue without full-page OCR")


def test_auto_mode_warns_if_full_page_ocr_is_recommended(monkeypatch, caplog):
    document = SimpleNamespace(
        diagnostic=SimpleNamespace(recommend_full_ocr=True),
        pages=[],
        metadata=SimpleNamespace(),
    )
    monkeypatch.setattr(pipeline, "extraire", lambda *_args: document)
    monkeypatch.setattr(pipeline, "diagnose_document", lambda _document: None)
    monkeypatch.setattr(pipeline, "PaddleOCRBackend", lambda **_kwargs: object())
    monkeypatch.setattr(pipeline, "recuperer_texte_vectorise", lambda *_args, **_kwargs: document)
    monkeypatch.setattr(pipeline, "resoudre", lambda _document: document)
    monkeypatch.setattr(pipeline, "render_flow_pdf", lambda *_args, **_kwargs: "out.pdf")

    with caplog.at_level(logging.WARNING, logger="datacompiler.pipeline"):
        result = pipeline.executer_pipeline("unused.pdf", strategy="flow", ocr_mode="auto")

    assert result is document
    assert "Full-page OCR was recommended" in caplog.text


def test_cli_never_writes_json(monkeypatch, tmp_path):
    appels = []
    monkeypatch.setattr(pipeline, "executer_pipeline", lambda *a, **k: appels.append(k))
    monkeypatch.setattr(sys, "argv", ["datacompiler", str(tmp_path / "x.pdf")])
    pipeline.main()
    assert appels and appels[0]["sauver_json"] is False


def test_cli_has_no_json_option(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["datacompiler", str(tmp_path / "x.pdf"), "--no-json"])
    try:
        pipeline.main()
    except SystemExit as exc:
        assert exc.code == 2  # option inconnue : argparse refuse
    else:
        raise AssertionError("--no-json ne devrait plus exister")
