"""Reorder native words to match an external reference sequence, typically OCR Markdown tokens, using rank matching rather than a text diff."""

from collections import defaultdict, deque


def ordre_par_correspondance(mots_natifs, tokens_reference, cle_texte=lambda m: m.text):
    """Sort native words by their next unused position in the reference-token sequence, keeping unmatched words at the end."""
    files_par_texte = defaultdict(deque)
    for j, tok in enumerate(tokens_reference):
        files_par_texte[tok].append(j)

    rangs = {}
    for m in mots_natifs:
        file_ = files_par_texte.get(cle_texte(m))
        rangs[id(m)] = file_.popleft() if file_ else float("inf")

    return sorted(mots_natifs, key=lambda m: rangs[id(m)])
