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
    include_comments: bool = False,
) -> TranslationApplication:
    """Apply imported XLIFF targets to a copy and write a rebuilt translated PDF.

    Translated text stays in its source segment box; when needed, its font size
    is reduced to fit. Original document data remains unchanged. Missing
    targets preserve their source text and are listed. PDF comments are off by
    default; set ``include_comments=True`` to add the review annotations.
    """
    application = apply_xliff_translation(
        document, translation, expected_units=expected_units,
    )
    from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf

    render_rebuilt_pdf(
        application.document, output_path,
        source_pdf=source_pdf or document.metadata.source_pdf,
        dpi=dpi,
        include_translation_comments=include_comments,
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
