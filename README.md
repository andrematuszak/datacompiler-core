# DataCompiler

This README documents the DataCompiler 0.2.0 release.

DataCompiler extracts and resolves PDF text, then creates a reconstructed PDF
that follows the resolved reading order. It can also prepare translations for
review and open a desktop editor to correct text and layout.

## Requirements

- Source installation requires Python **3.11 or later**.
- The published 0.2.0 wheel supports **CPython 3.12 on macOS 26 or later
  (Apple Silicon / arm64)** only.
- Tkinter and a graphical desktop session are required only for the editors.
- An Internet connection may be required on the first PaddleOCR run to download
  its models, and when using OpenRouter, DeepL, or Matecat services.

## Installation

### Published wheel

The v0.2.0 release provides a wheel for CPython 3.12 on macOS 26 or later
(Apple Silicon / arm64). Install it with:

```bash
python3.12 -m pip install "https://github.com/andrematuszak/datacompiler-core/releases/download/v0.2.0/datacompiler-0.2.0-cp312-cp312-macosx_26_0_arm64.whl"
```

This wheel is not compatible with other Python versions, operating systems, or
macOS architectures.

### Install from source

For other supported Python environments, install from a source checkout.
Create and activate a virtual environment from the repository root:

```bash
python3 -m venv .venv                  # macOS / Linux
source .venv/bin/activate
# Windows PowerShell: py -3.11 -m venv .venv
# then: .venv\Scripts\Activate.ps1
```

Install DataCompiler and its base dependencies:

```bash
python -m pip install -e .
```

PaddlePaddle and PaddleOCR are required base dependencies for the documented
reconstruction workflow. They add a substantial native runtime; the first OCR
run may also download model files. The Mistral client is available separately
as an optional extra. Other optional extras are:

```bash
python -m pip install -e ".[translation]"                      # DeepL translation
python -m pip install -e ".[translation,translation-quality]"   # DeepL + COMETKiwi
python -m pip install -e ".[mistral]"                           # Optional Mistral OCR client
python -m pip install -e ".[openai]"                            # OpenRouter NVIDIA OCR client
python -m pip install -e ".[dev]"                               # Tests and development tools
```

`langdetect` is a base dependency, so language detection does not require a
separate `language` extra. Full-page NVIDIA OCR requires the optional
`openai` extra and `OPENROUTER_API_KEY`.

## Command-line usage

After installation, the `datacompiler` command is available in the virtual
environment:

```bash
datacompiler path/to/document.pdf
```

The recommended workflow is reconstruction. By default, the command creates
`document_rebuilt.pdf`, a new PDF following the resolved reading order. Its
reconstructed text is visible and selectable; images and non-text drawings are
preserved. You can select the default explicitly:

```bash
datacompiler document.pdf --strategy rebuilt
```

Other CLI output formats and strategies are available. For example,
`--format faithful-pdf` requires `--strategy overlay` or `--strategy
rasterized`; `--format flow-pdf` creates a flow-layout PDF. The `clean_overlay`
strategy is deprecated and redirects to `rebuilt` with a warning.

### OCR

The default `--ocr-mode auto` routes each page independently. Healthy native
text is preserved, mixed native text and vectorized glyphs use targeted
PaddleOCR, and full-page image scans without native text use
`nvidia/nemotron-3.5-super-vl:free` through OpenRouter. The model receives each rendered
page separately and transcribes it in its original language; language
detection then runs on the OCR text. Set `OPENROUTER_API_KEY` in the
environment and install the `openai` extra to use this route. The initial
handwriting signal is a heuristic for this simple scan category; it is not a
general handwriting classifier. OCR routes are logged as page categories and
strategies without printing the detailed diagnostic signals.

For targeted PaddleOCR, the language is detected from each page's native text
when possible. If it cannot be detected, specify the PaddleOCR language:

```bash
datacompiler document.pdf --paddle-lang en-us
```

`--ocr-mode vector` enables only targeted vector-text OCR; `--ocr-mode skip`
disables OCR and is not the recommended workflow. NVIDIA OCR preserves the
model's page transcription as Markdown; it does not infer word coordinates or
table geometry. Language detection for scan pages runs after OCR and is
recorded as post-OCR provenance. `--ocr-mode force` remains unsupported;
automatic page-level routing selects NVIDIA OCR for full-page scans.

### Machine translation and editing

CLI translation uses DeepL. Install the `translation` extra and set
`DEEPL_AUTH_KEY` in the environment; segment text is sent to DeepL. The source
language is detected by default, or you can specify it:

```bash
export DEEPL_AUTH_KEY="..."  # Set an environment variable on Windows.
datacompiler document.pdf --target-lang en-us
datacompiler document.pdf --target-lang en-us --source-lang fr
```

The command creates `document.en.xlf` (XLIFF for review) and
`document_en_rebuilt.pdf`. `--no-translate` prevents a DeepL request even when
`--target-lang` is present.

The CLI offers two editing paths:

```bash
# Edit resolved text without translating.
datacompiler document.pdf --editor

# Translate, then open the translation editor.
datacompiler document.pdf --target-lang en --edit-translation
```

`--edit-translation` requires `--target-lang` and cannot be combined with
`--no-translate`. `--editor` opens the generic resolved-text editor for pages
without VLM transcription. VLM pages use the existing desktop editor with the
Dots transcription as the default when available. Each non-empty line is an
editable segment; draw a box around each line on the scan, then move or resize
it as needed. The rebuilt PDF keeps the scan unchanged and adds an invisible,
searchable text layer at those box positions. The session is saved beside the
source as `<name>.review.json`, and line geometry and edits as
`<name>_rebuilt.layout.json`; rerunning resumes from these files without calling the
VLMs again. Saving requires every active VLM line to have a box.
`--editor` requires the rebuilt PDF output format. The generic and translation
editors require Tkinter and a graphical desktop session.

Without `--editor`, the CLI stays non-interactive and writes its normal output
immediately; use `datacompiler document.pdf --editor` when you want the process
to wait for line placement and transcription editing before producing the rebuilt PDF.

In the editor, select a block to change its text, size, bold/italic style,
superscript or subscript, color, position, and dimensions. The native color
picker sets text color; **Source color** clears the override. Custom text color
is independent of sampled glyph-path colors and is saved in the layout
sidecar. The current editor button is labeled **Couleur source**.

You can add a text block, delete or restore a block, and split the selected
block into two editable blocks. To merge or align multiple blocks, select them
in the list with Ctrl/Cmd-click or Shift-click. Merging requires all selected
blocks to belong to the same page. Alignment uses the last-selected block as
the reference and supports left, right, top, bottom, horizontal-center, and
vertical-center anchors; it preserves block sizes and reading order. A newly
added text block is placed on the first page.

Saving writes the PDF and an associated `.layout.json` sidecar. This
versioned sidecar preserves corrections using stable segment IDs (or resolved
word IDs in the generic editor) and is automatically reapplied the next time
the editor opens. Vector glyph paths replaced by text are excluded from the
rebuilt output to prevent the old glyphs from appearing underneath; unrelated
graphics remain preserved.

## Python API

`executer_pipeline` processes the document and writes a reconstructed PDF by
default:

```python
from datacompiler import executer_pipeline

document = executer_pipeline("document.pdf", strategy="rebuilt")
print(f"Pages processed: {len(document.pages)}")
```

To edit resolved text without translating, use `edit_document_pdf`. For a
translation workflow, export XLIFF units, import the reviewed XLIFF, and use
`render_translated_pdf` for a direct render or `edit_translation_pdf` to review
and adjust the translated layout:

```python
from datacompiler.translation import (
    export_xliff, import_xliff, render_translated_pdf,
)

units = export_xliff(
    document, "document-fr-en.xlf",
    source_language="fr", target_language="en",
)
# Translate/review the XLIFF in a compatible tool, then:
translation = import_xliff(
    "document-fr-en-reviewed.xlf", expected_units=units,
)
application = render_translated_pdf(
    document, translation, "document-en-rebuilt.pdf",
    expected_units=units,
)
print("Translated segments:", len(application.translated_units))
```

To open the editor on resolved text without translation, call
`edit_document_pdf(document, "document-rebuilt.pdf")`. To edit the translated
output instead of rendering it directly, replace `render_translated_pdf` with:

```python
from datacompiler.translation import edit_translation_pdf

application = edit_translation_pdf(
    document, translation, "document-en-lqa.pdf",
    expected_units=units,
)
```

XLIFF export uses version 1.2. A line crossing multiple detected table cells
is split by cell. Page, word, and block IDs are preserved in a DataCompiler
note; import validates those IDs and does not replace the document's source
text.

`render_translated_pdf` keeps translated segments in their original boxes,
without reflow or line wrapping. It does not automatically reduce the font size
to fit text. Segments without a translation retain their source text. PDF
comments are off by default; pass `include_comments=True` to
`render_translated_pdf` to include the source and translated text, engine,
quality estimate, and review notes. COMETKiwi estimates are uncalibrated and
are not probabilities that a translation is correct.

### Matecat review

DataCompiler can submit an XLIFF file to Matecat and import it after human
review. The source PDF is not uploaded, but segment text is sent to the
configured Matecat server. The review session takes place in Matecat's web
interface.

```python
from datacompiler.translation import (
    MatecatClient, submit_document_to_matecat, import_matecat_xliff,
    render_translated_pdf,
)

client = MatecatClient()  # Reads MATECAT_API_KEY and MATECAT_BASE_URL.
project, units = submit_document_to_matecat(
    document, client, "document-fr-en.xlf",
    source_language="fr-FR", target_language="en-US",
    project_name="Document for review",
)
print("Project created:", project.project_id)
if project.editor_url:
    print("Editor:", project.editor_url)
elif project.project_id and project.project_password:
    print(client.get_project_urls(project.project_id, project.project_password))

# After review in Matecat:
translation = import_matecat_xliff(
    client, project, "document-fr-en-reviewed.xlf", expected_units=units,
)
render_translated_pdf(
    document, translation, "document-en-rebuilt.pdf", expected_units=units,
)
```

Set `MATECAT_API_KEY` to the API key required by Matecat.
`MATECAT_BASE_URL` defaults to `https://www.matecat.com` and can point to
another instance. Keep credentials in the environment, not in the repository.
The integration uses Matecat's public APIs to create a project, retrieve its
details, and export the XLIFF. IDs and source text are validated on import to
avoid associating translations with the wrong segments.

### Translation quality

The `translation-quality` extra adds COMETKiwi, a local reference-free quality
estimator. It can annotate XLIFF segments below the default 0.65 threshold and
mark them for review. The model is large, and downloading it may require
accepting its license on Hugging Face.

```python
from datacompiler.translation import (
    CometKiwiQualityEstimator, translate_xliff_file,
)

quality = CometKiwiQualityEstimator()  # Downloads the model.
translation = translate_xliff_file(
    "document-fr-en.xlf", "document-fr-en-machine.xlf",
    context="French tax form; preserve legal references.",
    # glossary="GLOSSARY_ID",  # Optional.
    quality_estimator=quality,
)
```

### Language detection

Language detection uses native PDF text before targeted OCR and supplies a
language to PaddleOCR when available. It is also available through
`detect_document_languages(document)` to annotate resolved lines and
`detect_language(text)` for a single text sample. Very short or uncertain text
may not produce a language detection result.

## Tests

Install development tools and run the test suite:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

To display coverage:

```bash
python -m pytest --cov=datacompiler --cov-report=term-missing
```

For bitmap images, `ImageElement.contains_text` remains `null` (unknown):
the Tesseract-based image OCR probe was removed. The value is not changed to
`false`, so that an unperformed analysis is not presented as a negative result.
