from __future__ import annotations

import importlib
from unittest.mock import Mock

import pytest


def test_error_digest_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_error_digest")

    monkeypatch.setattr("sys.argv", ["sase_chop_error_digest", "--context", "ctx"])
    monkeypatch.setattr(script, "read_chop_context", lambda _path: object())
    monkeypatch.setattr(script, "read_errors", lambda: [])
    monkeypatch.setattr(script, "read_last_error_digest_ts", lambda: None)
    notify = Mock()
    monkeypatch.setattr(script, "notify_axe_error_digest", notify)

    script.main()

    notify.assert_not_called()
    out = capsys.readouterr().out
    assert "error_digest:" in out
    assert "errors_total=0" in out
    assert "recent=0" in out
    assert "notified=0" in out
    assert "reason=no_recent_errors" in out


def test_error_digest_emits_action_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_error_digest")

    errors = [
        {"timestamp": "2099-05-12T10:00:00-04:00", "message": "older"},
        {"timestamp": "2099-05-12T10:05:00-04:00", "message": "newer"},
    ]
    written: list[str] = []
    monkeypatch.setattr("sys.argv", ["sase_chop_error_digest", "--context", "ctx"])
    monkeypatch.setattr(script, "read_chop_context", lambda _path: object())
    monkeypatch.setattr(script, "read_errors", lambda: errors)
    monkeypatch.setattr(
        script,
        "read_last_error_digest_ts",
        lambda: "2026-05-12T09:00:00-04:00",
    )
    notify = Mock()
    monkeypatch.setattr(script, "notify_axe_error_digest", notify)
    monkeypatch.setattr(script, "write_last_error_digest_ts", written.append)

    script.main()

    notify.assert_called_once_with(errors)
    assert written == ["2099-05-12T10:05:00-04:00"]
    out = capsys.readouterr().out
    assert "error_digest:" in out
    assert "errors_total=2" in out
    assert "recent=2" in out
    assert "notified=2" in out
    assert "newest=2099-05-12T10:05:00-04:00" in out
