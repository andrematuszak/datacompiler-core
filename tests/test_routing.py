"""Regression tests for page-level OCR routing."""

from types import ModuleType, SimpleNamespace
import sys

from datacompiler.backend.rebuilt_markdown import render_markdown
from datacompiler.frontend.ocr.mistral import MistralBackend
from datacompiler.frontend.routing import (
    FULL_PAGE_MISTRAL_OCR,
    MIXED_NATIVE_AND_GLYPHS,
    NATIVE_TEXT,
    PRESERVE_NATIVE,
    SKIP_OCR,
    TARGETED_PADDLE_OCR,
    format_page_routes,
    route_document,
    route_page,
)
from datacompiler.model.document import Diagnostic, Document, OcrBlock, Page, Word
from datacompiler.model.metadata import LanguageInfo, RoutingDecision
from datacompiler.translation import language as language_detection


def _page(number=1, **diagnostic_values):
    return Page(
        number=number,
        width=612,
        height=792,
        diagnostic=Diagnostic(**diagnostic_values),
    )


def test_full_page_scan_routes_to_mistral():
    page = _page(has_full_page_images=True)

    decision = route_page(page)

    assert decision.category == "full_page_scan"
    assert decision.strategy == FULL_PAGE_MISTRAL_OCR
    assert decision.backend == "mistral"


def test_handwritten_scan_uses_the_specific_category():
    page = _page(has_full_page_images=True, handwritten_likely=True)

    assert route_page(page).category == "full_page_scan_handwriting_likely"


def test_native_vector_glyphs_always_route_to_targeted_paddle():
    page = _page(
        has_native_text=True,
        vectorized_text_detected=True,
        native_text_quality=0.95,
        native_text_coverage=0.95,
    )

    decision = route_page(page)

    assert decision.category == MIXED_NATIVE_AND_GLYPHS
    assert decision.strategy == TARGETED_PADDLE_OCR
    assert decision.backend == "paddle"


def test_route_page_preserves_healthy_native_text_and_honors_skip():
    page = _page(
        has_native_text=True,
        native_text_quality=0.98,
        native_text_coverage=0.99,
    )

    automatic = route_page(page)
    skipped = route_page(page, ocr_mode="skip")

    assert (automatic.category, automatic.strategy) == (NATIVE_TEXT, PRESERVE_NATIVE)
    assert skipped.strategy == SKIP_OCR
    assert skipped.backend is None


def test_routing_is_attached_independently_per_page():
    native_page = _page(has_native_text=True)
    scan_page = _page(2, has_full_page_images=True)

    document = route_document(Document(pages=[native_page, scan_page]))

    assert document.pages[0].routing.strategy == PRESERVE_NATIVE
    assert document.pages[1].routing.strategy == FULL_PAGE_MISTRAL_OCR


def test_route_summaries_combine_adjacent_identical_page_decisions():
    pages = [_page(1), _page(2), _page(3)]
    for page in pages:
        page.routing = RoutingDecision(category=NATIVE_TEXT, strategy=PRESERVE_NATIVE)

    assert format_page_routes(pages) == [
        "Page 1-3: Category: native_text\n          Strategy: preserve_native"
    ]


def test_document_json_round_trip_keeps_routing_language_and_diagnostics():
    page = _page(1, has_full_page_images=True)
    page.routing = RoutingDecision(
        category="full_page_scan_handwriting_likely",
        strategy=FULL_PAGE_MISTRAL_OCR,
        backend="mistral",
    )
    page.language = LanguageInfo("pl", 0.97, "post_ocr")
    page.ocr.blocks.append(
        OcrBlock(
            type="markdown",
            content="# Example text",
            confidence=0.9,
            metadata={"dimensions": {"width": 100, "height": 200}},
        )
    )
    source = Document(
        diagnostic=Diagnostic(has_full_page_images=True),
        pages=[page],
    )

    restored_document = Document.from_dict(source.to_dict())
    restored = restored_document.pages[0]

    assert restored_document.diagnostic.has_full_page_images is True
    assert restored.routing.backend == "mistral"
    assert restored.language.source == "post_ocr"
    assert restored.ocr.blocks[0].content == "# Example text"
    assert restored.ocr.blocks[0].metadata["dimensions"]["width"] == 100


def test_post_ocr_language_detection_records_confidence_and_provenance(monkeypatch):
    page = Page(1, 612, 792)
    page.ocr.words.append(Word(id=1, text="detected text"))
    expected = LanguageInfo("en", 0.95, "post_ocr")
    monkeypatch.setattr(
        language_detection,
        "detect_language_info",
        lambda _text, source: LanguageInfo("en", 0.95, source),
    )

    result = language_detection.detect_page_language(page, source="post_ocr")

    assert result == expected
    assert page.language == expected
    assert page.ocr.words[0].language == "en"


def test_markdown_rendering_preserves_mistral_semantic_output():
    page = _page(1)
    page.routing = RoutingDecision(
        category="full_page_scan_handwriting_likely",
        strategy=FULL_PAGE_MISTRAL_OCR,
        backend="mistral",
    )
    page.ocr.blocks.append(
        OcrBlock(type="markdown", content="## Heading\n\n- First item")
    )

    output = render_markdown(Document(pages=[page]))

    assert "## Heading\n\n- First item" in output


def test_mistral_backend_requests_only_selected_pages_and_retains_structure(
    tmp_path, monkeypatch
):
    calls = []

    class FakeClient:
        def __init__(self, api_key):
            self.ocr = self

        def process(self, **request):
            calls.append(request)
            return SimpleNamespace(
                pages=[
                    SimpleNamespace(
                        index=1,
                        markdown="# Example OCR text",
                        dimensions=SimpleNamespace(width=100, height=200),
                        images=[],
                        blocks=[
                            {
                                "type": "text",
                                "content": "Example",
                                "bbox": [10, 20, 50, 60],
                                "confidence": 0.91,
                            }
                        ],
                        tables=[
                            {
                                "bbox": [10, 20, 50, 60],
                                "rows": [[
                                    {
                                        "content": "Cell",
                                        "bbox": [10, 20, 30, 40],
                                    }
                                ]],
                            }
                        ],
                    )
                ]
            )

    package = ModuleType("mistralai")
    package.__path__ = []
    client_module = ModuleType("mistralai.client")
    client_module.Mistral = FakeClient
    monkeypatch.setitem(sys.modules, "mistralai", package)
    monkeypatch.setitem(sys.modules, "mistralai.client", client_module)

    source = tmp_path / "scan.pdf"
    source.write_bytes(b"pdf bytes")
    document = Document(pages=[Page(1, 612, 792), Page(2, 612, 792)])

    MistralBackend(api_key="test-key").ocraliser(document, str(source), pages=[2])

    assert calls[0]["pages"] == [1]
    assert document.pages[0].ocr.words == []
    assert document.pages[1].ocr.engine == "mistral-mistral-ocr-latest"
    markdown = next(
        block for block in document.pages[1].ocr.blocks if block.type == "markdown"
    )
    structured_block = next(
        block for block in document.pages[1].ocr.blocks if block.type == "text"
    )
    assert markdown.content == "# Example OCR text"
    assert markdown.metadata["dimensions"]["width"] == 100
    assert structured_block.confidence == 0.91
    assert structured_block.bbox.x0 == 61.2
    assert document.pages[1].graphics.tables[0].source == "mistral"
    assert document.pages[1].graphics.tables[0].cell_bboxes[0][0].x0 == 61.2
