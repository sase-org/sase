"""Behavior tests for the ``sase task kill`` handler."""

from __future__ import annotations

import json

import pytest

from sase.procs import get_proc
from tests.main.task_handler_helpers import dispatch, stored, task_home

__all__ = ["task_home"]


def test_kill_resolves_prefix_and_marks_active_task_killed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI exposes the store kill path through the same prefix resolver."""
    monkeypatch.setattr("sase.main.task_handler._reconcile_quietly", lambda: None)
    stored(
        "aaaaaaaaaaaa",
        label="Global launch",
        kind="detached",
        status="running",
        finished_at=None,
        exit_code=None,
    )

    assert dispatch(["task", "kill", "aaa"]) == 0

    assert "Killed task aaaaaa." in capsys.readouterr().out
    task = get_proc("aaaaaaaaaaaa")
    assert task is not None
    assert task.status == "killed"


def test_kill_terminal_task_is_a_json_noop(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Killing completed work succeeds without mutating its terminal state."""
    stored("aaaaaaaaaaaa", status="success")

    assert dispatch(["task", "kill", "aaa", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["changed"] is False
    assert payload["task"]["status"] == "success"


def test_kill_reports_bad_task_references(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unknown kill targets are usage errors, just like ``task show``."""
    assert dispatch(["task", "kill", "zzz"]) == 2
    assert "no task matches reference" in capsys.readouterr().err
