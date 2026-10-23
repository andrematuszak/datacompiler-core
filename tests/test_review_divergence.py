import pytest

from datacompiler.model.document import Document, OcrCandidate, Page
from datacompiler.review.divergence import (
    align_candidates, build_review, compose_text, decide, refresh_state, tokenize,
)

BASE = "Rozliczenie od 21.12.2024 do 30.06.2025\nPrace w Survmont i Monflam\nmateriał 4635.90 €\npraca 14985 €"


def cand(cid, text):
    return OcrCandidate(id=cid, model=cid, text=text)


def test_identical_candidates_have_no_divergence_and_are_validated():
    review = build_review([cand("a", BASE), cand("b", BASE)])
    assert review.divergences == []
    assert review.state == "validated"
    assert review.validated_text == BASE


def test_single_candidate_is_not_reviewable():
    review = build_review([cand("a", BASE)])
    assert review.state == "none" and review.validated_text is None


def test_two_models_disagree_on_amount_and_name_stay_open():
    b = BASE.replace("14985", "14 985").replace("Survmont", "Sumont")
    review = build_review([cand("a", BASE), cand("b", b)])
    assert len(review.divergences) == 2
    assert all(d.status == "open" for d in review.divergences)
    assert review.state == "in_review" and review.validated_text is None
    amount = next(d for d in review.divergences if "14985" in [p.text for p in d.proposals])
    assert {p.text for p in amount.proposals} == {"14985", "14 985"}
    assert amount.context_before.endswith("praca")


def test_human_decisions_validate_and_preserve_layout():
    b = BASE.replace("14985", "14 985").replace("Survmont", "Sumont")
    cands = [cand("a", BASE), cand("b", b)]
    review = build_review(cands)
    for d in review.divergences:
        texts = [p.text for p in d.proposals]
        if "14985" in texts:
            decide(d, "b")
        else:
            decide(d, "custom", "Surmont")
    refresh_state(review, cands)
    assert review.state == "validated"
    assert review.validated_text == BASE.replace("14985", "14 985").replace("Survmont", "Surmont")
    assert "\n" in review.validated_text


def test_pending_keeps_document_in_review():
    b = BASE.replace("Survmont", "Sumont")
    cands = [cand("a", BASE), cand("b", b)]
    review = build_review(cands)
    decide(review.divergences[0], "pending")
    refresh_state(review, cands)
    assert review.state == "in_review"


def test_majority_decides_text_automatically_but_never_digits():
    b = BASE.replace("Survmont", "Sumont").replace("14985", "14 985")
    c = BASE.replace("14985", "19485")
    review = build_review([cand("a", BASE), cand("b", b), cand("c", c)])
    by_text = {tuple(sorted(p.text for p in d.proposals)): d for d in review.divergences}
    name = by_text[("Sumont", "Survmont")] if ("Sumont", "Survmont") in by_text else None
    assert name is not None and name.status == "auto"          # 2 of 3 say Survmont
    assert name.decision.text == "Survmont" and name.decision.by == "auto"
    amount = next(d for d in review.divergences if any(p.text == "19485" for p in d.proposals))
    assert amount.status == "open"                              # digits: human check
    assert review.state == "in_review"


def test_omitted_and_inserted_words_merge_into_one_span():
    a = "- 520 € materiał dla mnie\n- czynsz."
    b = "- 520 € materiał\n- czynsz."
    d = align_candidates([cand("a", a), cand("b", b)])
    assert len(d) == 1 and d[0].kind == "omission"
    assert {p.text for p in d[0].proposals} == {"dla mnie", ""}


def test_insertion_before_end_and_at_start():
    d = align_candidates([cand("a", "akonto 5300 €"), cand("b", "akonto 5300 € przelew")])
    assert len(d) == 1 and (d[0].ref_start, d[0].ref_end) == (3, 3)
    assert {p.text for p in d[0].proposals} == {"", "przelew"}
    d = align_candidates([cand("a", "5300 €"), cand("b", "akonto 5300 €")])
    assert (d[0].ref_start, d[0].ref_end) == (0, 0)


def test_json_roundtrip_keeps_candidates_decisions_and_derived_status(tmp_path):
    b = BASE.replace("Survmont", "Sumont")
    cands = [cand("a", BASE), cand("b", b)]
    page = Page(number=1, width=100, height=100)
    page.ocr.candidates = cands
    page.review = build_review(cands)
    decide(page.review.divergences[0], "a", reason="lecture sur le scan")
    refresh_state(page.review, cands)
    doc = Document(pages=[page])
    path = tmp_path / "doc.json"
    doc.save(str(path))
    loaded = Document.load(str(path))
    p = loaded.pages[0]
    assert [c.id for c in p.ocr.candidates] == ["a", "b"]
    assert p.review.state == "validated"
    assert p.review.divergences[0].status == "resolved"
    assert p.review.validated_text == BASE


def test_old_json_without_review_still_loads():
    doc = Document.from_dict({"schema_version": "1.0", "pages": [{"number": 1, "width": 1, "height": 1}]})
    assert doc.pages[0].review.state == "none" and doc.pages[0].ocr.candidates == []


def test_illegible_marker_is_never_accepted_automatically():
    a = "Prace w [?] i Monflam"
    b = "Prace w [?] i Monflam"
    c = "Prace w Survmont i Monflam"
    review = build_review([cand("a", a), cand("b", b), cand("c", c)])
    assert len(review.divergences) == 1
    assert review.divergences[0].status == "open"
    assert review.state == "in_review"
