from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.axe.chop_script_context import ChopScriptContext, write_chop_context


@pytest.fixture(autouse=True)
def _isolate_chop_result_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep an outer chop runner from overriding each test context."""

    monkeypatch.delenv("SASE_CHOP_RESULT_FILE", raising=False)


def _write_context(tmp_path: Path, result_path: Path) -> Path:
    context_path = tmp_path / "context.json"
    write_chop_context(
        ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="test",
            state_dir=str(tmp_path),
            all_changespecs_file=str(tmp_path / "all.json"),
            filtered_changespecs_file=str(tmp_path / "filtered.json"),
            result_file=str(result_path),
        ),
        str(context_path),
    )
    return context_path


def test_error_digest_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_error_digest")

    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        "sys.argv",
        ["sase_chop_error_digest", "--context", str(context_path)],
    )
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
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == 1
    assert result["status"] == "no_op"
    assert result["reason"] == "no_recent_errors"
    assert result["counters"] == {
        "errors_total": 0,
        "notified": 0,
        "recent": 0,
    }


def test_error_digest_emits_action_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_error_digest")

    errors = [
        {"timestamp": "2099-05-12T10:00:00-04:00", "message": "older"},
        {"timestamp": "2099-05-12T10:05:00-04:00", "message": "newer"},
    ]
    written: list[str] = []
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        "sys.argv",
        ["sase_chop_error_digest", "--context", str(context_path)],
    )
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
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["counters"] == {
        "errors_total": 2,
        "notified": 2,
        "recent": 2,
    }
