"""Render translated XLIFF targets into a rebuilt PDF."""

from __future__ import annotations

from datacompiler.model.document import Document
from .xliff import (
    TranslationApplication,
    TranslationUnit,
    XliffTranslation,
    apply_xliff_translation,
)


def render_translated_pdf(
    document: Document,
    translation: XliffTranslation,
    output_path: str,
    *,
    source_pdf: str | None = None,
    expected_units: list[TranslationUnit] | None = None,
    dpi: int = 300,
) -> TranslationApplication:
    """Apply imported XLIFF targets to a copy and write a rebuilt translated PDF.

    Translated lines in one source block are recomposed into a paragraph and
    wrapped inside the block's source bounds. Original document data remains
    unchanged. Missing targets preserve their source text and are listed.
    """
    application = apply_xliff_translation(
        document, translation, expected_units=expected_units,
    )
    from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf

    render_rebuilt_pdf(
        application.document, output_path,
        source_pdf=source_pdf or document.metadata.source_pdf,
        dpi=dpi,
    )
    application.layout_warnings.extend(
        note
        for page in application.document.pages
        for word in page.resolved.words
        if word.source == "xliff_translation"
        for note in word.notes
        if "text still overflows" in note
    )
    return application
