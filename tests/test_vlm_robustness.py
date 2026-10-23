import sys
import types
from types import SimpleNamespace

sys.modules.setdefault("pymupdf", types.ModuleType("pymupdf"))

import pytest

from datacompiler.frontend.ocr import vlm


class FakeStatusError(Exception):
    def __init__(self, status_code, message=""):
        super().__init__(message or f"status {status_code}")
        self.status_code = status_code


def ok(text="Rozliczenie od 21.12.2024"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), logprobs=None)],
        model_dump_json=lambda: "{}",
    )


def empty(code=429):
    return SimpleNamespace(
        choices=None,
        error={"message": "Provider returned error", "code": code},
    )


class FakeClient:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(vlm.time, "sleep", lambda _s: None)


def call(client, **kw):
    return vlm.transcribe_image(
        client, "data:image/png;base64,AA", "nvidia/x:free", "prompt",
        status_error_type=FakeStatusError, **kw,
    )


def test_choiceless_reply_is_retried_without_logprobs():
    client = FakeClient(empty(), ok())
    cand = call(client)
    assert cand.text.startswith("Rozliczenie")
    assert "logprobs" in client.requests[0] and "logprobs" not in client.requests[1]
    assert cand.metadata["logprobs_requested"] is False
    assert cand.confidence is None


def test_choiceless_reply_retried_once_after_pause_when_allowed():
    client = FakeClient(empty(), empty(), ok())
    assert call(client, retry_429=True).text
    assert len(client.requests) == 3


def test_persistent_choiceless_reply_exposes_the_upstream_error():
    client = FakeClient(empty(), empty())
    with pytest.raises(vlm.EmptyCompletionError) as info:
        call(client)
    assert "Provider returned error" in str(info.value)
    assert "no OCR completion choices" in str(info.value)


def test_402_is_never_retried():
    client = FakeClient(FakeStatusError(402), ok())
    with pytest.raises(FakeStatusError):
        call(client, retry_429=True)
    assert len(client.requests) == 1


def test_logprob_rejection_falls_back_without_logprobs():
    client = FakeClient(FakeStatusError(400, "logprobs not supported"), ok())
    assert call(client).text
    assert "logprobs" not in client.requests[1]


def test_multi_model_skips_a_failing_model_and_keeps_the_others():
    class Router(FakeClient):
        def _create(self, **request):
            self.requests.append(request)
            return empty() if request["model"] == "a/bad:free" else ok("tekst")

    client = Router()
    cands = vlm.transcribe_with_models(
        client, "data:image/png;base64,AA", ["a/bad:free", "b/good:free"], "p",
        status_error_type=FakeStatusError,
    )
    assert [c.model for c in cands] == ["b/good:free"]


def test_all_models_failing_gives_one_clear_error():
    client = FakeClient(*[empty() for _ in range(8)])
    with pytest.raises(RuntimeError, match="No VLM produced"):
        vlm.transcribe_with_models(
            client, "data:image/png;base64,AA", ["a/x:free"], "p",
            status_error_type=FakeStatusError,
        )


def test_report_records_ok_and_failed_models():
    class Router(FakeClient):
        def _create(self, **request):
            self.requests.append(request)
            return empty() if request["model"] == "a/bad:free" else ok("tekst")

    report = []
    vlm.transcribe_with_models(
        Router(), "data:image/png;base64,AA", ["a/bad:free", "b/good:free"], "p",
        status_error_type=FakeStatusError, report=report,
    )
    assert [(r["model"], r["status"]) for r in report] == [
        ("a/bad:free", "failed"), ("b/good:free", "ok"),
    ]
    assert "no OCR completion choices" in report[0]["error"]


def test_debug_report_is_written_with_candidates_and_review(tmp_path):
    from datacompiler.review.divergence import build_review
    from datacompiler.model.document import OcrCandidate

    a = OcrCandidate(id="a", model="m/a", text="praca 14985 €\nczynsz")
    b = OcrCandidate(id="b", model="m/b", text="praca 14 985 €\nczynsz")
    review = build_review([a, b])
    path = vlm.write_debug_report(
        tmp_path, 1, configured_models=["m/a", "m/b"], models_source="env",
        report=[{"model": "m/a", "status": "ok"}, {"model": "m/b", "status": "ok"}],
        candidates=[a, b], review=review,
    )
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["models_source"] == "env" and len(data["candidates"]) == 2
    assert data["review"]["state"] == "in_review"
    assert data["review"]["divergences"][0]["proposals"]
    assert (tmp_path / "page1_a.txt").read_text(encoding="utf-8") == "praca 14985 €\nczynsz"


def test_rate_limit_waits_with_growing_delays(monkeypatch):
    delays = []
    monkeypatch.setattr(vlm.time, "sleep", delays.append)
    client = FakeClient(FakeStatusError(429), FakeStatusError(429), ok())
    assert call(client, retry_429=True).text
    assert delays == [10, 30]


def test_rate_limit_gives_up_after_two_waits():
    client = FakeClient(FakeStatusError(429), FakeStatusError(429), FakeStatusError(429))
    with pytest.raises(FakeStatusError):
        call(client, retry_429=True)
    assert len(client.requests) == 3


def test_debug_report_accepts_a_failed_run(tmp_path):
    path = vlm.write_debug_report(
        tmp_path, 1, configured_models=["m/a"], models_source="env",
        report=[{"model": "m/a", "status": "failed", "error": "HTTP 429"}],
        candidates=[], review=None,
    )
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["review"] is None and data["model_results"][0]["status"] == "failed"


def test_502_is_retried_with_growing_delays(monkeypatch):
    delays = []
    monkeypatch.setattr(vlm.time, "sleep", delays.append)
    client = FakeClient(FakeStatusError(502), FakeStatusError(502), ok())
    assert call(client, retry_429=True).text
    assert delays == [10, 30]


def test_a_model_failing_with_502_is_skipped_and_others_run():
    class Router(FakeClient):
        def _create(self, **request):
            self.requests.append(request)
            if request["model"] == "a/down:free":
                raise FakeStatusError(502, "Provider returned error")
            return ok("tekst")

    report = []
    cands = vlm.transcribe_with_models(
        Router(), "data:image/png;base64,AA", ["a/down:free", "b/good:free"], "p",
        status_error_type=FakeStatusError, report=report,
    )
    assert [c.model for c in cands] == ["b/good:free"]
    assert report[0]["status"] == "failed" and "502" in report[0]["error"]


def test_bad_api_key_aborts_instead_of_skipping():
    client = FakeClient(FakeStatusError(401, "invalid key"))
    with pytest.raises(FakeStatusError):
        vlm.transcribe_with_models(
            client, "data:image/png;base64,AA", ["a/x:free", "b/y:free"], "p",
            status_error_type=FakeStatusError,
        )
    assert len(client.requests) == 1


def test_single_model_down_gives_one_clear_error_with_the_reason():
    client = FakeClient(*[FakeStatusError(502, "Provider returned error") for _ in range(5)])
    with pytest.raises(RuntimeError) as info:
        vlm.transcribe_with_models(
            client, "data:image/png;base64,AA", ["nvidia/x:free"], "p",
            status_error_type=FakeStatusError,
        )
    assert "No VLM produced" in str(info.value) and "502" in str(info.value)
