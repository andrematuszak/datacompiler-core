# PDF corpus checks (#12, #19)

Run a corpus measurement from the repository root:

```powershell
python tools/pdf_corpus_report.py path\to\sample-a.pdf path\to\sample-b.pdf --output $env:TEMP\pdf-corpus.json
```

The report contains file hashes, page dimensions, character and word counts,
elapsed time, bounding-box counts, and a severity summary. It never stores
extracted text. Keep sensitive samples and generated reports outside the
repository. Compare measurements with the rendered PDF when investigating a
selection-box defect; numerical containment is a regression signal, not a
substitute for visual review.

## Anonymized tax notice baseline

Measured locally on 2026-10-12. The source PDF is in the companion
`datacompiler` repository and is deliberately not copied into this repository.

| Measure | Result |
| --- | ---: |
| Pages | 3 |
| Extracted words (PyMuPDF and pdfplumber) | 590 |
| pdfplumber word boxes containing their associated characters | 590 / 590 |
| pdfplumber zero-area boxes | 1 |
| pdfplumber boxes extending outside page bounds | 0 |

The zero-area item is on page 1, with `x0 == x1 == 527.224 pt` and height
`14 pt`. It is a one-character extraction result. The text is intentionally
omitted. This is a medium-severity corpus alert for investigation in a
separate issue; the corpus task records it but does not change extraction
behavior. The rendered first-page review showed the PyMuPDF word selection
boxes aligned with the visible text.

## Corpus completion criteria

- Include at least three structurally different PDFs, with page count and
  source type recorded. The anonymized tax notice is the first real sample;
  add other public or anonymized samples before treating #19 as complete.
- Save the generated JSON report outside Git when it contains identifiable
  local paths. Keep the compact, text-free findings table above in this doc.
- For each alert, record the affected page, geometry, severity, and a
  separate follow-up issue. Do not make unrelated fixes as part of the corpus
  sweep.
- For #12, compare selection rectangles with visible segments and require
  each extracted word box to enclose its associated character boxes within
  0.02 pt. Include a rendered-page review for each sample with alerts.
