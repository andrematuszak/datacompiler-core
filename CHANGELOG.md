# Changelog

All notable changes to **DataCompiler** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-20

### Added

- A lightweight desktop editor for resolved source text and translated
  segments, with text and layout editing, typography controls, and a native
  text-color picker.
- Text-block creation, deletion/restoration, splitting, and same-page merging
  in the editor. Multi-selection alignment supports explicit geometric anchors.
- Versioned `.layout.json` sidecars that persist edits using stable segment or
  word IDs.
- XLIFF 1.2 import/export for translation review, with validation of segment
  identifiers and preservation of page, word, and block references.
- Optional integrations for DeepL machine translation, Matecat human review,
  and COMETKiwi reference-free quality estimation.
- Language detection for resolved lines and PaddleOCR language selection.

### Changed

- Rebuilt PDF output is the recommended workflow and default CLI output.
  PaddlePaddle and PaddleOCR are now base dependencies for this workflow;
  Mistral OCR remains optional.
- Rebuilt output replaces recognized vector glyphs with visible selectable
  text while preserving unrelated images and graphics. Editor glyph masks
  prevent old vector text from being duplicated beneath edited text.
- The CLI supports output-format selection; `faithful-pdf` requires an explicit
  `overlay` or `rasterized` strategy. `clean_overlay` is deprecated and
  redirects to `rebuilt`.
- Translation editing retains changes to text, geometry, typography, and color
  in a sidecar for later renders. Translated PDF output preserves source boxes
  without automatically reflowing or shrinking translated text.

### Fixed

- Preserved editor segment order and deletion state across sidecar reloads.
- Corrected vector-glyph rendering issues that could make source glyphs
  reappear or duplicate edited text.
- Improved link extraction and reconstruction, and resolved PDF pipeline
  regression issues.

## [0.1.0] - 2026-10-07

### Added

- A six-stage PDF compilation pipeline:
  1. Hybrid parallel extraction with PyMuPDF and pdfplumber.
  2. Automatic diagnostics of text quality and visual integrity.
  3. Mistral full-page OCR integration (disabled in the active pipeline; see
     Known limitations).
  4. Targeted PaddleOCR for vectorized text regions.
  5. Layout reconstruction and conflict resolution.
  6. Multiple output backends: faithful PDF, flow PDF, rebuilt PDF, Markdown,
     HTML, and DOCX.
- A command-line interface through the `datacompiler` command.
- Installation guidance and CLI/Python quick starts in the README, plus an
  `examples/basic_usage.py` script.
- `examples/basic_usage.py` can generate a sample PDF or accept an input path,
  instead of depending on a repository test document.
- Reference-PDF tests are skipped when the fixture is unavailable.
- Removal of unused `.woff`/`.woff2` and Marianne font variants, and addition
  of `backend/fonts/README.md` with font licensing information.
- Generated outputs, tool caches, and the `private/` directory in `.gitignore`.
- Python 3.11+ support (tested with Python 3.12).
- A `[dev]` extra for pytest instead of making it a base dependency.

### Known limitations

- Full-page Mistral OCR is disabled because global OCR-to-native-text alignment
  has not yet been validated.
- In the v0.1.0 CLI, `--format` is accepted but ignored; use `--strategy`.
- Only one output format is produced per run, next to the source PDF.

[0.2.0]: https://github.com/andrematuszak/datacompiler-core/releases/tag/v0.2.0
[0.1.0]: https://github.com/andrematuszak/datacompiler/releases/tag/v0.1.0
