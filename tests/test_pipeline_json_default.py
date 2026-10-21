"""Le JSON intermédiaire ne doit pas être écrit par défaut."""

import inspect
import sys

from datacompiler import pipeline


def test_json_is_disabled_by_default_in_library():
    default = inspect.signature(pipeline.executer_pipeline).parameters["sauver_json"].default
    assert default is False


def test_force_ocr_mode_fails_clearly_until_full_page_ocr_is_supported():
    try:
        pipeline.executer_pipeline("unused.pdf", ocr_mode="force")
    except NotImplementedError as exc:
        assert "Forced full-page OCR is not implemented" in str(exc)
    else:
        raise AssertionError("force OCR must not silently continue without full-page OCR")


def test_auto_mode_routes_full_page_scans_to_mistral(monkeypatch):
    from datacompiler.model.document import Diagnostic, Document, Page

    page = Page(
        number=1,
        width=612,
        height=792,
        diagnostic=Diagnostic(
            has_native_text=False,
            has_full_page_images=True,
            has_images_with_text=True,
            handwritten_likely=True,
        ),
    )
    document = Document(pages=[page])
    mistral_calls = []

    class FakeMistral:
        def ocraliser(self, _document, _path, pages=None):
            mistral_calls.append(pages)

    monkeypatch.setattr(pipeline, "extraire", lambda *_args: document)
    monkeypatch.setattr(pipeline, "diagnose_document", lambda _document: None)
    monkeypatch.setattr(pipeline, "MistralBackend", FakeMistral)
    monkeypatch.setattr(pipeline, "recuperer_texte_vectorise", lambda *_args, **_kwargs: document)
    monkeypatch.setattr(pipeline, "resoudre", lambda _document: document)
    monkeypatch.setattr(pipeline, "render_flow_pdf", lambda *_args, **_kwargs: "out.pdf")

    result = pipeline.executer_pipeline("unused.pdf", strategy="flow", ocr_mode="auto")

    assert result is document
    assert mistral_calls == [[1]]
    assert page.routing.strategy == "full_page_mistral_ocr"


def test_mixed_document_routes_each_page_to_its_own_ocr_strategy(monkeypatch):
    from datacompiler.model.document import Diagnostic, Document, Page, Word

    native_page = Page(
        number=1,
        width=612,
        height=792,
        diagnostic=Diagnostic(
            has_native_text=True,
            vectorized_text_detected=True,
            native_text_quality=0.95,
            native_text_coverage=0.95,
        ),
    )
    native_page.native.words.append(Word(id=1, text="native"))
    scan_page = Page(
        number=2,
        width=612,
        height=792,
        diagnostic=Diagnostic(
            has_native_text=False,
            has_full_page_images=True,
            has_images_with_text=True,
            handwritten_likely=True,
        ),
    )
    document = Document(pages=[native_page, scan_page])
    paddle_calls = []
    mistral_calls = []

    class FakeMistral:
        def ocraliser(self, _document, _path, pages=None):
            mistral_calls.append(pages)

    monkeypatch.setattr(pipeline, "extraire", lambda *_args: document)
    monkeypatch.setattr(pipeline, "diagnose_document", lambda _document: None)
    monkeypatch.setattr(pipeline, "PaddleOCRBackend", lambda **_kwargs: object())
    monkeypatch.setattr(pipeline, "MistralBackend", FakeMistral)
    monkeypatch.setattr(
        pipeline,
        "recuperer_texte_vectorise",
        lambda _doc, _path, _backend, **kwargs: paddle_calls.append(kwargs["pages"]),
    )
    monkeypatch.setattr(pipeline, "resoudre", lambda _document: document)
    monkeypatch.setattr(pipeline, "render_flow_pdf", lambda *_args, **_kwargs: "out.pdf")

    result = pipeline.executer_pipeline(
        "unused.pdf",
        strategy="flow",
        paddle_lang="en",
        ocr_mode="auto",
    )

    assert result is document
    assert paddle_calls == [[1]]
    assert mistral_calls == [[2]]
    assert native_page.routing.strategy == "targeted_paddle_ocr"
    assert scan_page.routing.strategy == "full_page_mistral_ocr"
    assert native_page.language.source == "user_override"


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
