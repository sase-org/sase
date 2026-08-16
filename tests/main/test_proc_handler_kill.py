"""Behavior tests for the ``sase proc kill`` handler."""

from __future__ import annotations

import json

import pytest

from sase.procs import get_proc
from tests.main.proc_handler_helpers import dispatch, stored, proc_home

__all__ = ["proc_home"]


def test_kill_resolves_prefix_and_marks_active_proc_killed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI exposes the store kill path through the same prefix resolver."""
    monkeypatch.setattr("sase.main.proc_handler._reconcile_quietly", lambda: None)
    stored(
        "aaaaaaaaaaaa",
        label="Global launch",
        kind="detached",
        status="running",
        finished_at=None,
        exit_code=None,
    )

    assert dispatch(["proc", "kill", "aaa"]) == 0

    assert "Killed proc aaaaaa." in capsys.readouterr().out
    proc = get_proc("aaaaaaaaaaaa")
    assert proc is not None
    assert proc.status == "killed"


def test_kill_terminal_proc_is_a_json_noop(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Killing completed work succeeds without mutating its terminal state."""
    stored("aaaaaaaaaaaa", status="success")

    assert dispatch(["proc", "kill", "aaa", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert payload["changed"] is False
    assert payload["proc"]["status"] == "success"


def test_kill_reports_bad_proc_references(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unknown kill targets are usage errors, just like ``proc show``."""
    assert dispatch(["proc", "kill", "zzz"]) == 2
    assert "no proc matches reference" in capsys.readouterr().err


def test_kill_resolves_named_proc_shell(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``proc kill`` accepts a fully qualified named proc shell."""
    monkeypatch.setattr("sase.main.proc_handler._reconcile_quietly", lambda: None)
    stored(
        "aaaaaaaaaaaa",
        label="Named launch",
        kind="detached",
        status="running",
        finished_at=None,
        exit_code=None,
        shell_name="agent--build",
    )

    assert dispatch(["proc", "kill", "agent--build"]) == 0

    assert "Killed proc aaaaaa." in capsys.readouterr().out
