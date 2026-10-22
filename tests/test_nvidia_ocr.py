"""Tests for OpenRouter-backed full-page NVIDIA OCR."""

from types import ModuleType, SimpleNamespace
import sys

import pymupdf

from datacompiler.frontend.ocr.nvidia import MODEL_NAME, NvidiaBackend
from datacompiler.model.document import Document, Page


def test_nvidia_backend_sends_selected_rendered_page_and_retries_once(
    tmp_path, monkeypatch
):
    calls = []
    waits = []

    class APIStatusError(Exception):
        status_code = 429

    class RateLimitError(APIStatusError):
        pass

    class FakeCompletions:
        def create(self, **request):
            calls.append(request)
            if len(calls) == 1:
                raise RateLimitError()
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="Pierwszy wiersz\nDrugi wiersz")
                    )
                ]
            )

    class FakeOpenAI:
        def __init__(self, *, base_url, api_key, max_retries):
            assert base_url == "https://openrouter.ai/api/v1"
            assert api_key == "test-key"
            assert max_retries == 0
            self.chat = SimpleNamespace(
                completions=FakeCompletions(),
            )

    openai_module = ModuleType("openai")
    openai_module.OpenAI = FakeOpenAI
    openai_module.APIStatusError = APIStatusError
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setattr("datacompiler.frontend.ocr.nvidia.time.sleep", waits.append)

    source = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.new_page()
        pdf.save(source)

    document = Document(pages=[Page(1, 612, 792), Page(2, 612, 792)])
    result = NvidiaBackend(api_key="test-key").ocraliser(
        document, str(source), pages=[2]
    )

    assert result is document
    assert waits == [10]
    assert len(calls) == 2
    assert calls[0]["model"] == MODEL_NAME
    request_content = calls[0]["messages"][0]["content"]
    assert request_content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "original language" in request_content[1]["text"]
    assert document.pages[0].ocr.words == []
    assert document.pages[1].ocr.engine == MODEL_NAME
    assert [word.text for word in document.pages[1].ocr.words] == [
        "Pierwszy",
        "wiersz",
        "Drugi",
        "wiersz",
    ]
    assert document.pages[1].ocr.blocks[0].content == "Pierwszy wiersz\nDrugi wiersz"
