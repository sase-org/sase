from __future__ import annotations

import importlib
import json
import os
import time
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
from sase.chops.builtin import run_builtin_chop


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


def test_managed_tmp_reap_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    importlib.import_module("sase.scripts.sase_chop_managed_tmp_reap")

    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        "sase.core.managed_tmp_reaper.managed_tmpdir_root", lambda: managed_root
    )

    run_builtin_chop("managed_tmp_reap", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "managed_tmp_reap:" in out
    assert "removed=0" in out
    assert "reason=nothing_stale" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "nothing_stale"
    assert result["counters"] == {
        "capped": 0,
        "deindexed": 0,
        "removed": 0,
        "scanned": 0,
        "subdirs": 0,
    }


def test_epic_launch_flush_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_epic_launch_flush")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        script,
        "flush_orphaned_deferrals",
        lambda: SimpleNamespace(
            pending_scanned=2,
            active=0,
            young=2,
            flushed=0,
            settled_reaped=0,
            errors=0,
        ),
    )

    run_builtin_chop("epic_launch_flush", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "epic_launch_flush:" in out
    assert "pending=2" in out
    assert "young=2" in out
    assert "reason=nothing_due" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "nothing_due"
    assert result["counters"] == {
        "active": 0,
        "errors": 0,
        "flushed": 0,
        "pending": 2,
        "settled_reaped": 0,
        "young": 2,
    }


def test_managed_tmp_reap_emits_action_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    importlib.import_module("sase.scripts.sase_chop_managed_tmp_reap")

    managed_root = tmp_path / "managed"
    stale = managed_root / "editors" / "note.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("scratch", encoding="utf-8")
    ancient = time.time() - 400 * 24 * 3600
    os.utime(stale, (ancient, ancient))

    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        "sase.core.managed_tmp_reaper.managed_tmpdir_root", lambda: managed_root
    )

    run_builtin_chop("managed_tmp_reap", ["--context", str(context_path)])

    assert not stale.exists()
    out = capsys.readouterr().out
    assert "reclaimed 1 entries" in out
    assert "removed=1" in out
    assert "subdirs=1" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["counters"] == {
        "capped": 0,
        "deindexed": 0,
        "removed": 1,
        "scanned": 1,
        "subdirs": 1,
    }
