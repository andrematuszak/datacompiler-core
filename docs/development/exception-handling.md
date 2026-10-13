# Exception-handling audit

This audit covers `try` statements under `src/datacompiler` (Python source
snapshot on 2026-10-12). The goal is predictable recovery and resource cleanup;
exceptions must not be swallowed just to keep a command running.

## Narrow handlers

- Lazy package registries catch `KeyError` for unknown export names.
- JSON response parsing catches `json.JSONDecodeError` and returns no detections.
- Paddle output normalization catches only `TypeError`, `ValueError`, and
  `IndexError` for malformed third-party result shapes.
- The compiler's compatibility accessors catch `AttributeError` and
  `TypeError` for supported alternate object layouts.
- Debug image writes catch `OSError`; failure of optional diagnostics must not
  fail OCR.
- PDF resource lifetimes use `finally` so source and output documents close on
  success and failure.

## Recoverable external boundaries

The PDF renderers have broad handlers around font lookup/extraction, image
copying, and individual vector drawing commands. PyMuPDF may surface errors
from its native binding across multiple exception classes. These operations
are independent: the renderer records a fallback or skipped object and
continues, while emitting a warning or traceback for diagnosis. Narrowing
these handlers to a PyMuPDF-specific exception class would require a declared
minimum-version guarantee for that class; the package currently supports
PyMuPDF >= 1.24.

PaddleOCR and Qwen model initialization also cross optional packages, native
libraries, hardware runtimes, model downloads, and device allocation. The
backend remains unavailable on failure, and `logger.exception` preserves the
traceback. This does not catch exceptions during normal OCR inference.

## Maintenance rule

Every new broad handler must state which operation can be skipped, which
fallback is used, and how the failure remains observable. Never catch
`BaseException`. Prefer a narrow exception whenever a stable expected failure
is known.
