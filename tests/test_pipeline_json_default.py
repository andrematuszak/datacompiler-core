"""Le JSON intermédiaire ne doit pas être écrit par défaut."""

import inspect
import sys

from datacompiler import pipeline


def test_json_is_disabled_by_default_in_library():
    default = inspect.signature(pipeline.executer_pipeline).parameters["sauver_json"].default
    assert default is False


def test_cli_never_writes_json(monkeypatch, tmp_path):
    appels = []
    monkeypatch.setattr(pipeline, "executer_pipeline", lambda *a, **k: appels.append(k))
    monkeypatch.setattr(sys, "argv", ["datacompiler", str(tmp_path / "x.pdf")])
    pipeline.main()
    assert appels and appels[0]["sauver_json"] is False


def test_cli_has_no_json_option(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["datacompiler", str(tmp_path / "x.pdf"), "--no-json"])
    try:
        pipeline.main()
    except SystemExit as exc:
        assert exc.code == 2  # option inconnue : argparse refuse
    else:
        raise AssertionError("--no-json ne devrait plus exister")
