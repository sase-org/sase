"""Behavior tests for the ``sase task show`` handler."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.main.task_handler_helpers import (
    dispatch,
    stored,
    task_home,
    write_log,
)

__all__ = ["task_home"]


def test_show_renders_detail_and_log_tail(capsys: pytest.CaptureFixture[str]) -> None:
    """The default view is the header panel followed by the log tail."""
    stored("aaaaaaaaaaaa", label="Docs", tags=["docs"])
    write_log("aaaaaaaaaaaa", "first\nsecond\nthird\n")

    assert dispatch(["task", "show", "aaa", "-l", "2"]) == 0

    out = capsys.readouterr().out
    assert "Docs" in out
    assert "✓ success" in out
    assert "second" in out and "third" in out
    assert "first" not in out


def test_show_names_detached_global_ownership(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Detached detail makes the lack of a session explicit."""
    stored("aaaaaaaaaaaa", label="Epic launch", kind="detached")

    assert dispatch(["task", "show", "aaa"]) == 0

    assert "detached (global; no session owns this task)" in capsys.readouterr().out


def test_show_output_only_prints_the_log_without_chrome(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--output-only`` stays pipe friendly."""
    stored("aaaaaaaaaaaa", label="Docs")
    write_log("aaaaaaaaaaaa", "one\ntwo\n")

    assert dispatch(["task", "show", "aaa", "-o", "-A"]) == 0

    assert capsys.readouterr().out == "one\ntwo\n"


def test_show_json_includes_the_task_and_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--format json`` emits one envelope carrying the captured output."""
    stored("aaaaaaaaaaaa", label="Docs")
    write_log("aaaaaaaaaaaa", "captured\n")

    assert dispatch(["task", "show", "aaa", "-f", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["task"]["label"] == "Docs"
    assert payload["log"] == "captured\n"


def test_show_reports_unknown_short_and_ambiguous_references(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every bad reference is a usage error naming what went wrong."""
    stored("aaaaaaaaaaaa", label="One")
    stored("aaaabbbbbbbb", label="Two", created_at="2026-07-25T12:01:00Z")

    assert dispatch(["task", "show", "zzz"]) == 2
    assert "no task matches reference" in capsys.readouterr().err

    assert dispatch(["task", "show", "aa"]) == 2
    assert "at least 3 characters" in capsys.readouterr().err

    assert dispatch(["task", "show", "aaa"]) == 2
    assert "is ambiguous" in capsys.readouterr().err


def test_show_follow_on_a_terminal_task_returns_immediately(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--follow`` prints the retained log once and exits for a done task."""
    stored("aaaaaaaaaaaa", label="Docs")
    write_log("aaaaaaaaaaaa", "alpha\nbeta\n")

    assert dispatch(["task", "show", "aaa", "-F", "-o"]) == 0

    assert capsys.readouterr().out == "alpha\nbeta\n"


def test_show_follow_json_waits_for_the_finished_task(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--follow --format json`` blocks and reports the terminal record."""
    assert (
        dispatch(
            [
                "task",
                "run",
                "-q",
                "-c",
                str(tmp_path),
                "--",
                sys.executable,
                "-c",
                "import time; time.sleep(0.3)",
            ]
        )
        == 0
    )
    task_id = capsys.readouterr().out.strip()

    assert dispatch(["task", "show", task_id, "-F", "-f", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["task"]["status"] == "success"
    assert payload["task"]["finished_at"] is not None
