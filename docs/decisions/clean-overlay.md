# `clean_overlay` strategy decision

`clean_overlay` was created in `faithful_pdf.py` to fix two problems of the
`overlay` strategy: original vector glyph drawings stayed visible under the new
text, and wrong native text stayed selectable under the corrected text.

It only solved the second one, and at a cost:

- Its `_copier_images_et_dessins` copies every drawing, so glyph curves are not
  removed. Only `rebuilt_pdf.py` has the `exclure` parameter that skips them.
- All inserted words use `fill_opacity=0.015`, and native text is not copied, so
  native text is no longer visible in the output.
- It does write words in the resolved reading order, but `rebuilt` does the same
  and also keeps the text visible.

`rebuilt_pdf.py` is the corrected rewrite of the same idea, so `clean_overlay`
is deprecated:

- `executer_pipeline(strategy="clean_overlay")` and `--strategy clean_overlay`
  log a warning and run `rebuilt` (the output file is named `*_rebuilt.pdf`).
- `render_faithful_pdf(strategy="clean_overlay")` still works and logs a warning.
- Removal: not before 0.4.0, in a release whose changelog says so.

`overlay` stays as the conservative strategy: the source PDF is kept and hidden
text is added only for corrected or recovered words. It does not apply the
resolved reading order to the native text.
