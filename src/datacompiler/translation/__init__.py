"""Language detection and translation exchange helpers."""

from .language import detect_document_language, detect_document_languages, detect_language
from .xliff import (
    TranslationApplication, TranslationUnit, XliffTranslation,
    apply_xliff_translation, export_xliff, import_xliff,
)
from .render import render_translated_pdf
from .providers import (
    CometKiwiQualityEstimator, DeepLTranslator, translate_xliff_file,
)
from .matecat import (
    MatecatClient, MatecatProject, import_matecat_xliff,
    submit_document_to_matecat,
)

__all__ = [
    "TranslationUnit", "XliffTranslation", "TranslationApplication",
    "detect_language", "export_xliff", "import_xliff",
    "detect_document_languages", "detect_document_language",
    "apply_xliff_translation", "render_translated_pdf",
    "DeepLTranslator", "CometKiwiQualityEstimator", "translate_xliff_file",
    "MatecatClient", "MatecatProject", "submit_document_to_matecat",
    "import_matecat_xliff",
]
