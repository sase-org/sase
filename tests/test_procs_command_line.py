"""Command-line proc tag, retention bucket, and submission contract."""

from __future__ import annotations

import sys

from sase.procs import (
    COMMAND_LINE_PROC_HISTORY_LIMIT,
    COMMAND_LINE_PROC_TAG,
)
from sase.procs.command_line import (
    COMMAND_LINE_PROC_HISTORY_LIMIT as MODULE_HISTORY_LIMIT,
)
from sase.procs.command_line import COMMAND_LINE_PROC_TAG as MODULE_TAG
from sase.procs.command_line import submit_command_line_proc


def test_command_line_proc_tag_value() -> None:
    assert COMMAND_LINE_PROC_TAG == "command-line"
    assert MODULE_TAG == "command-line"


def test_command_line_proc_history_limit_value() -> None:
    assert COMMAND_LINE_PROC_HISTORY_LIMIT == 50
    assert MODULE_HISTORY_LIMIT == 50


def test_submit_command_line_proc_builds_a_tagged_ordinary_proc(
    monkeypatch,
) -> None:
    captured: dict = {}
    sentinel = object()
    monkeypatch.setattr(
        "sase.procs.command_line.submit_proc_request",
        lambda request: (captured.setdefault("request", request), sentinel)[1],
    )

    result = submit_command_line_proc(
        ["bead", "list", "--status", "open"],
        cwd="/tmp",
        project="sase",
        width=120,
        session_id="session-a",
    )

    assert result is sentinel
    request = captured["request"]
    assert request.argv == [
        sys.executable,
        "-m",
        "sase",
        "bead",
        "list",
        "--status",
        "open",
    ]
    assert request.command == ["sase", "bead", "list", "--status", "open"]
    assert request.label == ": bead list --status open"
    assert tuple(request.tags) == ("command-line",)
    assert request.origin == "ace"
    assert request.env == {
        "PYTHONUNBUFFERED": "1",
        "FORCE_COLOR": "1",
        "COLUMNS": "120",
    }
    assert request.operation is None
    assert request.service is None
    assert tuple(request.concurrency_keys) == ()
    assert request.project == "sase"
    assert request.session_id == "session-a"
    assert str(request.cwd) == "/tmp"
