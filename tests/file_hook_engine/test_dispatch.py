"""Dispatch, batch, and runner tests for the file-hook engine."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.file_hooks.audit import list_file_hook_audits, safe_file_hook_error_diagnostic
from sase.file_hooks.engine import dispatch_file_hook_events, emit_file_hook_events
from sase.file_hooks.runner import _prune_file_hook_state, execute_batch
from sase.notifications.priority import is_error
from sase.notifications.store import load_notifications

from .helpers import audits, clear_agent_env, event, hook, init_repo


def test_emit_persists_versioned_batch_and_detaches_once_per_commit(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    spawned: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(argv: list[str], **kwargs: Any) -> MagicMock:
        spawned.append((argv, kwargs))
        return MagicMock()

    first = emit_file_hook_events(
        [event(repo)],
        hooks=[hook("render")],
        commit_sha="a" * 40,
        popen=fake_popen,
    )
    second = emit_file_hook_events(
        [event(repo)],
        hooks=[hook("render")],
        commit_sha="a" * 40,
        popen=fake_popen,
    )

    assert first is not None
    assert second == first
    assert len(spawned) == 1
    argv, kwargs = spawned[0]
    assert argv[-3:] == ["file-hook", "exec-batch", str(first)]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is subprocess.DEVNULL
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["commit_sha"] == "a" * 40
    assert payload["runs"][0]["command"] == "true"
    assert payload["runs"][0]["abs_path"] == str(repo / "report.md")
    assert payload["runs"][0]["cause"] == "user"


def test_emit_records_non_user_cause_in_batch_payload(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)

    batch_path = emit_file_hook_events(
        [event(repo, cause="referenced_by")],
        hooks=[hook("render", causes=("referenced_by",))],
        commit_sha="b" * 40,
        popen=lambda *args, **kwargs: MagicMock(),
    )

    assert batch_path is not None
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    assert payload["runs"][0]["cause"] == "referenced_by"


def test_excluded_agent_produces_no_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    clear_agent_env(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "research.7.cld")

    result = dispatch_file_hook_events(
        [event(repo, agent_name="research.7.cld")],
        hooks=[hook("render", agent_name_globs=("!research.*.cld",))],
        popen=lambda *args, **kwargs: MagicMock(),
        producer="commit",
    )

    assert result.outcome == "no_match"
    assert result.batch_path is None
    assert result.audit_path is not None
    assert "no_match" in audits()


def test_detached_spawn_failure_is_non_gating_and_leaves_no_pending_batch(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)

    result = dispatch_file_hook_events(
        [event(repo)],
        hooks=[hook("render")],
        popen=lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("no spawn token=super-secret")
        ),
        producer="commit",
    )

    assert result.outcome == "producer_error"
    assert result.batch_path is None
    assert result.error is not None
    assert "OSError" in result.error
    assert "super-secret" not in result.error
    assert "token=<redacted>" in result.error
    batches = Path(os.environ["SASE_HOME"]).expanduser() / "file_hooks" / "batches"
    assert list(batches.glob("*.json")) == []
    notifications = [
        notification
        for notification in load_notifications()
        if notification.sender == "file-hooks"
    ]
    assert len(notifications) == 1
    assert is_error(notifications[0])
    assert notifications[0].files[0] == result.audit_path


def test_runner_reports_success_failure_and_timeout_and_is_idempotent(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    target = repo / "report.md"
    target.write_text("# report\n", encoding="utf-8")
    python = shlex.quote(sys.executable)
    success_code = shlex.quote("import sys; print(sys.argv[-1])")
    failure_code = shlex.quote("print('bad'); raise SystemExit(3)")
    timeout_code = shlex.quote("import time; time.sleep(1)")
    hooks = [
        hook("success", f"{python} -c {success_code}"),
        hook("failure", f"{python} -c {failure_code}"),
        hook(
            "timeout",
            f"{python} -c {timeout_code}",
            timeout_seconds=0.01,
        ),
    ]
    batch_path = emit_file_hook_events(
        [event(repo)],
        hooks=hooks,
        popen=lambda *args, **kwargs: MagicMock(),
    )
    assert batch_path is not None

    assert execute_batch(batch_path) == 0
    assert execute_batch(batch_path) == 0

    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    assert payload["status"] == "finished"
    assert [run["status"] for run in payload["runs"]] == ["finished"] * 3
    assert payload["runs"][0]["exit_code"] == 0
    assert payload["runs"][1]["exit_code"] == 3
    assert "timeout" in payload["runs"][2]["failure"]

    notifications = [
        notification
        for notification in load_notifications()
        if notification.sender == "file-hooks"
    ]
    assert len(notifications) == 3
    success = next(n for n in notifications if "success" in n.tags)
    failure = next(n for n in notifications if "failure" in n.tags)
    timeout = next(n for n in notifications if "timeout" in n.tags)
    assert success.notes[0] == "✅ success: report.md"
    assert Path(success.files[0]).read_text(encoding="utf-8").endswith(f"{target}\n")
    assert is_error(failure)
    assert failure.action_data["error_report_path"] == failure.files[0]
    assert is_error(timeout)


def test_pruning_removes_only_expired_audit_files(tmp_path: Path) -> None:
    root = Path(os.environ["SASE_HOME"]).expanduser() / "file_hooks"
    old = root / "runs" / "old.log"
    recent = root / "logs" / "recent.log"
    old_audit = root / "audit" / "old.json"
    old.parent.mkdir(parents=True)
    recent.parent.mkdir(parents=True)
    old_audit.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    recent.write_text("recent", encoding="utf-8")
    old_audit.write_text("{}\n", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 100, now - 100))
    os.utime(old_audit, (now - 100, now - 100))

    removed = _prune_file_hook_state(now=now, retention_seconds=50)

    assert set(removed) == {old, old_audit}
    assert not old.exists()
    assert not old_audit.exists()
    assert recent.exists()


def test_dispatch_records_no_hooks_without_a_batch(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)

    result = dispatch_file_hook_events([event(repo)], hooks=[])

    assert result.outcome == "no_hooks"
    assert result.batch_path is None
    assert result.audit_path is not None
    assert list_file_hook_audits()[0].outcome == "no_hooks"
    notifications = [
        notification
        for notification in load_notifications()
        if notification.sender == "file-hooks"
    ]
    assert notifications == []


def test_safe_error_diagnostic_redacts_secrets_and_truncates() -> None:
    class TokenError(RuntimeError):
        pass

    short = safe_file_hook_error_diagnostic(TokenError("api_key=abcd1234 leftover"))
    assert "api_key=<redacted>" in short
    assert "abcd1234" not in short
    long = safe_file_hook_error_diagnostic(RuntimeError("x" * 800))
    assert long.endswith("...")
    assert len(long) == 500


def test_notification_failure_does_not_hide_producer_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    monkeypatch.setattr(
        "sase.notifications.store.append_notification",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("notify boom")),
    )

    result = dispatch_file_hook_events(
        [event(repo)],
        hooks=[hook("render")],
        popen=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no spawn")),
        producer="artifact",
    )

    assert result.outcome == "producer_error"
    assert result.audit_path is not None
    assert Path(result.audit_path).is_file()
