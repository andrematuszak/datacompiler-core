"""Tests for the generic OpenRouter VLM coordinator."""

from types import ModuleType, SimpleNamespace
import sys

import pytest
import pymupdf

from datacompiler.frontend.ocr.vlm import (
    HANDWRITING_PROMPT,
    ILLEGIBLE_MARKER,
    NVIDIA_MODEL_NAME,
    apply_candidates,
    default_vlm_models,
    ocraliser_pages,
    prompt_for_page,
    transcribe_with_models,
)
from datacompiler.model.document import Document, OcrCandidate, Page


GEMMA = "google/gemma-4-26b-a4b-it:free"


class APIStatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def _completion(text, logprobs=None):
    choice = SimpleNamespace(
        message=SimpleNamespace(content=text),
        logprobs=logprobs,
    )
    return SimpleNamespace(choices=[choice])


def _install_openai(monkeypatch, create):
    class FakeCompletions:
        def create(self, **request):
            return create(request)

    class FakeOpenAI:
        def __init__(self, *, base_url, api_key, max_retries):
            assert base_url == "https://openrouter.ai/api/v1"
            assert api_key == "test-key"
            assert max_retries == 0
            self.chat = SimpleNamespace(completions=FakeCompletions())

    openai_module = ModuleType("openai")
    openai_module.OpenAI = FakeOpenAI
    openai_module.APIStatusError = APIStatusError
    monkeypatch.setitem(sys.modules, "openai", openai_module)


def _scan_pdf(tmp_path):
    source = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(source)
    return source


def test_default_models_are_nvidia_unless_env_overrides(monkeypatch):
    monkeypatch.delenv("DATACOMPILER_VLM_MODELS", raising=False)
    assert default_vlm_models() == [NVIDIA_MODEL_NAME]
    monkeypatch.setenv("DATACOMPILER_VLM_MODELS", f"{NVIDIA_MODEL_NAME},{GEMMA}")
    assert default_vlm_models() == [NVIDIA_MODEL_NAME, GEMMA]


def test_handwriting_prompt_asks_for_illegible_marker_not_guesses():
    assert ILLEGIBLE_MARKER in prompt_for_page(handwriting=True)
    assert ILLEGIBLE_MARKER in HANDWRITING_PROMPT
    assert ILLEGIBLE_MARKER not in prompt_for_page(handwriting=False)


def test_402_skips_to_next_model_without_sleeping(monkeypatch):
    waits = []
    calls = []

    def create(**request):
        calls.append(request)
        if request["model"] == NVIDIA_MODEL_NAME:
            raise APIStatusError(402)
        return _completion("texte gemma")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("datacompiler.frontend.ocr.vlm.time.sleep", waits.append)

    candidates = transcribe_with_models(
        client,
        "data:image/png;base64,abc",
        [NVIDIA_MODEL_NAME, GEMMA],
        prompt_for_page(),
        status_error_type=APIStatusError,
    )
    assert waits == []
    assert [candidate.model for candidate in candidates] == [GEMMA]
    assert candidates[0].text == "texte gemma"
    assert candidates[0].confidence is None
    assert candidates[0].confidence_kind is None


def test_does_not_invent_confidence_without_logprobs():
    page = Page(number=1, width=100, height=100)
    apply_candidates(
        page,
        [
            OcrCandidate(id="nvidia", model=NVIDIA_MODEL_NAME, text="alpha"),
            OcrCandidate(id="gemma", model=GEMMA, text="beta"),
        ],
    )
    assert all(candidate.confidence is None for candidate in page.ocr.candidates)
    assert page.review.state == "in_review"
    assert page.ocr.blocks[0].metadata["provisional"] is True
    assert [word.text for word in page.ocr.words] == ["alpha"]


def test_logprobs_are_recorded_only_as_mean_token_logprob():
    logprobs = SimpleNamespace(
        content=[SimpleNamespace(logprob=-0.2), SimpleNamespace(logprob=-0.4)]
    )
    calls = []

    def create(**request):
        calls.append(request)
        assert request["logprobs"] is True
        assert request["top_logprobs"] == 5
        return _completion("ok", logprobs=logprobs)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    candidates = transcribe_with_models(
        client,
        "data:image/png;base64,abc",
        [NVIDIA_MODEL_NAME],
        prompt_for_page(),
        status_error_type=APIStatusError,
    )
    assert candidates[0].confidence == pytest.approx(-0.3)
    assert candidates[0].confidence_kind == "mean_token_logprob"


def test_ocraliser_pages_renders_once_and_queries_each_model(tmp_path, monkeypatch):
    calls = []

    def create(request):
        calls.append(request)
        texts = {
            NVIDIA_MODEL_NAME: "Survmont 14985",
            GEMMA: "Sumont 14 985",
        }
        return _completion(texts[request["model"]])

    _install_openai(monkeypatch, create)
    source = _scan_pdf(tmp_path)
    document = Document(pages=[Page(1, 612, 792)])
    ocraliser_pages(
        document,
        str(source),
        pages=[1],
        models=[NVIDIA_MODEL_NAME, GEMMA],
        api_key="test-key",
        handwriting_pages=[1],
    )
    assert [request["model"] for request in calls] == [NVIDIA_MODEL_NAME, GEMMA]
    assert len({request["messages"][0]["content"][0]["image_url"]["url"] for request in calls}) == 1
    assert ILLEGIBLE_MARKER in calls[0]["messages"][0]["content"][1]["text"]
    page = document.pages[0]
    assert len(page.ocr.candidates) == 2
    assert page.review.state == "in_review"
    assert page.ocr.engine == "openrouter-vlm"
    assert page.ocr.blocks[0].content == "Survmont 14985"
