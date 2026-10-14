"""Optional language identification for text and document segments."""

from __future__ import annotations

from datacompiler.compile.layout import grouper_par_ligne


def detect_language(text: str) -> str | None:
    """Return a two-letter language code, or ``None`` for empty/uncertain text.

    Detection is optional so the core package remains lightweight. Install the
    ``language`` extra to enable it. The function deliberately returns no
    guess for very short text, where language identification is unreliable.
    """
    normalized = " ".join((text or "").split())
    if len(normalized) < 30 or len(normalized.split()) < 5:
        return None
    try:
        from langdetect import DetectorFactory, detect_langs
    except ImportError as exc:
        raise RuntimeError(
            "Language detection requires the optional dependency; install "
            "datacompiler[language]."
        ) from exc

    # langdetect uses randomized feature ordering; pin it for repeatable output.
    DetectorFactory.seed = 0
    try:
        candidates = detect_langs(normalized)
    except Exception:
        return None
    if not candidates or candidates[0].prob < 0.70:
        return None
    return candidates[0].lang


def detect_document_languages(document) -> dict[str, str]:
    """Detect each resolved visual line and store its language on its words."""
    detected = {}
    for page in document.pages:
        words_on_page = page.resolved.words
        groups = grouper_par_ligne(words_on_page)
        if len(groups) == 1 and len(words_on_page) > 1 and not hasattr(words_on_page[0], "layout_line"):
            groups = []
            current = []
            previous_y = None
            for word in words_on_page:
                y = word.bbox.y0 if word.bbox else previous_y
                if current and y is not None and previous_y is not None and abs(y - previous_y) > 3:
                    groups.append(current)
                    current = []
                current.append(word)
                if y is not None:
                    previous_y = y
            if current:
                groups.append(current)
        for line_number, words in enumerate(groups, 1):
            text = " ".join((word.output_text or "").strip() for word in words).strip()
            language = detect_language(text)
            if language:
                unit_id = f"p{page.number}-l{line_number}"
                detected[unit_id] = language
                for word in words:
                    word.language = language
    return detected


def detect_document_language(document) -> str | None:
    """Detect the dominant language from native PDF text and annotate its words."""
    words = [word for page in document.pages for word in page.native.words]
    language = detect_language(" ".join((word.text or "") for word in words))
    if language:
        for word in words:
            word.language = language
    return language
