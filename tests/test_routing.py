"""Regression tests for page-level OCR routing."""

from datacompiler.frontend.routing import route_document, route_page
from datacompiler.model.document import Document, Page, Word


def _page() -> Page:
    return Page(number=1, width=595, height=842)


def test_full_page_scan_routes_to_mistral():
    page = _page()
    page.diagnostic.has_full_page_images = True

    decision = route_page(page)

    assert decision.category == "full_page_scan"
    assert decision.strategy == "full_page_mistral_ocr"
    assert decision.backend == "mistral"


def test_handwritten_scan_uses_the_specific_category():
    page = _page()
    page.diagnostic.has_full_page_images = True
    page.diagnostic.handwritten_likely = True

    assert route_page(page).category == "full_page_scan_handwriting_likely"


def test_native_vector_glyphs_always_route_to_targeted_paddle():
    page = _page()
    page.native.words = [Word(id=1, text="Native")]
    page.diagnostic.has_native_text = True
    page.diagnostic.vectorized_text_detected = True

    decision = route_page(page)

    assert decision.category == "mixed_native_and_glyphs"
    assert decision.strategy == "targeted_paddle_ocr"
    assert decision.backend == "paddle"


def test_routing_is_attached_independently_per_page():
    native_page = _page()
    native_page.diagnostic.has_native_text = True
    scan_page = Page(number=2, width=595, height=842)
    scan_page.diagnostic.has_full_page_images = True

    document = route_document(Document(pages=[native_page, scan_page]))

    assert document.pages[0].routing.strategy == "preserve_native"
    assert document.pages[1].routing.strategy == "full_page_mistral_ocr"


def test_routing_and_language_are_serialized():
    page = _page()
    page.diagnostic.has_full_page_images = True
    page.language.code = "pl"
    page.language.confidence = 0.99
    page.language.source = "post_ocr"

    document = route_document(Document(pages=[page]))
    reloaded = Document.from_dict(document.to_dict())

    assert reloaded.pages[0].routing.strategy == "full_page_mistral_ocr"
    assert reloaded.pages[0].language.code == "pl"
    assert reloaded.pages[0].language.source == "post_ocr"
