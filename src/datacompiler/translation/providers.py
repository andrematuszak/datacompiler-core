"""Optional machine-translation and segment-quality providers."""

from __future__ import annotations

import os

from .xliff import TranslationUnit, XliffTranslation


class DeepLTranslator:
    """Translate XLIFF units with DeepL's official Python SDK."""

    name = "deepl"

    def __init__(
        self,
        auth_key: str | None = None,
        *,
        context: str | None = None,
        glossary: str | None = None,
        formality: str | None = None,
    ):
        try:
            import deepl
        except ImportError as exc:
            raise RuntimeError(
                "DeepL translation requires the optional dependency; install "
                "datacompiler[translation]."
            ) from exc
        key = auth_key or os.environ.get("DEEPL_AUTH_KEY")
        if not key:
            raise ValueError("Set DEEPL_AUTH_KEY or pass auth_key to DeepLTranslator.")
        self._client = deepl.DeepLClient(key)
        self.context = context
        self.glossary = glossary
        self.formality = formality

    def translate(
        self,
        translation: XliffTranslation,
        *,
        source_language: str | None = None,
        force: bool = False,
        quality_estimator=None,
        review_threshold: float = 0.65,
    ) -> XliffTranslation:
        """Fill missing targets and optionally attach per-unit quality estimates."""
        if not 0.0 <= review_threshold <= 1.0:
            raise ValueError("review_threshold must be between 0 and 1")
        units = list(translation.units.values())
        pending = [u for u in units if force or not (u.target or "").strip()]
        source_language = source_language or translation.source_language
        sources = [u.source for u in pending]
        results = []
        # DeepL accepts lists of texts. Keep batches comfortably below its
        # request-size and item-count ceilings.
        for offset in range(0, len(sources), 40):
            batch = sources[offset:offset + 40]
            options = {
                "target_lang": translation.target_language.upper(),
                "split_sentences": "nonewlines",
                "preserve_formatting": True,
                "model_type": "prefer_quality_optimized",
            }
            if source_language:
                options["source_lang"] = source_language.upper()
            if self.context:
                options["context"] = self.context
            if self.glossary:
                if not source_language:
                    raise ValueError("DeepL glossaries require source_language.")
                options["glossary"] = self.glossary
            if self.formality:
                options["formality"] = self.formality
            results.extend(self._client.translate_text(batch, **options))

        for unit, result in zip(pending, results):
            unit.target = result.text
            unit.provider = self.name
        if quality_estimator is not None and pending:
            scores = quality_estimator.score(pending)
            if len(scores) != len(pending):
                raise ValueError("Quality estimator returned the wrong number of scores")
            for unit, score in zip(pending, scores):
                if score is not None:
                    unit.quality_score = max(0.0, min(1.0, float(score)))
                    unit.quality_model = getattr(
                        quality_estimator, "model_name", type(quality_estimator).__name__,
                    )
                    unit.review_recommended = unit.quality_score < review_threshold
        translation.target_language = translation.target_language.upper()
        return translation


class CometKiwiQualityEstimator:
    """Estimate reference-free translation quality with Unbabel COMETKiwi."""

    def __init__(self, model_name: str = "Unbabel/wmt22-cometkiwi-da", *, gpus: int = 0):
        try:
            from comet import download_model, load_from_checkpoint
        except ImportError as exc:
            raise RuntimeError(
                "COMETKiwi scoring requires the optional dependency; install "
                "datacompiler[translation-quality]."
            ) from exc
        checkpoint = download_model(model_name)
        self._model = load_from_checkpoint(checkpoint)
        self.model_name = model_name
        self.gpus = gpus

    def score(self, units: list[TranslationUnit]) -> list[float]:
        """Return model quality estimates for source/target segment pairs."""
        data = [
            {"src": unit.source, "mt": unit.target or ""}
            for unit in units
        ]
        output = self._model.predict(data, batch_size=8, gpus=self.gpus)
        return [float(value) for value in output.scores]


def translate_xliff_file(
    source_path,
    output_path,
    *,
    auth_key: str | None = None,
    context: str | None = None,
    glossary: str | None = None,
    formality: str | None = None,
    quality_estimator=None,
    review_threshold: float = 0.65,
) -> XliffTranslation:
    """Translate an XLIFF file with DeepL and write a review-ready XLIFF copy."""
    from .xliff import import_xliff, write_xliff_translation

    translation = import_xliff(source_path)
    translator = DeepLTranslator(
        auth_key, context=context, glossary=glossary, formality=formality,
    )
    translator.translate(
        translation, quality_estimator=quality_estimator,
        review_threshold=review_threshold,
    )
    write_xliff_translation(translation, output_path)
    return translation
