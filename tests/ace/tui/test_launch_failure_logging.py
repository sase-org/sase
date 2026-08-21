"""Per-category launch-failure persistence tests.

Asserts that each live TUI launch path (chop, payloadless durable launch
proc) durably records a ``launch_failures.jsonl`` entry with the correct
``kind`` when the launch fails. ``~/.sase`` is isolated per test, so the
canonical log paths resolve into a tmpdir automatically.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.logs import (
    clear_registered_errors,
    launch_failures_jsonl_path,
    launch_failures_log_path,
)


@pytest.fixture(autouse=True)
def _clear_registered_errors() -> Iterator[None]:
    clear_registered_errors()
    yield
    clear_registered_errors()


def _records() -> list[dict[str, Any]]:
    path = launch_failures_jsonl_path()
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().strip().splitlines()
        if line.strip()
    ]


def _assert_persisted(kind: str) -> dict[str, Any]:
    records = _records()
    assert records, f"no launch-failure record persisted for kind={kind}"
    record = records[-1]
    assert record["kind"] == kind
    assert "traceback" in record and record["traceback"]
    # The human-readable sidecar log is always written too.
    assert launch_failures_log_path().exists()
    return record


def _payloadless_completion(
    *,
    output: str = "",
    log_path: Path | None = None,
    error: str | None = "worker died",
) -> Any:
    from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
    from sase.ace.tui.proc_observer import ObservedProc as ProcInfo

    return TrackedProcCompletion(
        proc_info=ProcInfo(
            proc_id="task-1",
            proc_type="launch",
            cl_name="cl",
            project_file="",
            status="error",
            message="terminal proc message",
            started_at=datetime.now(),
            display_name="launch cl",
            command=["sase", "run", "do work"],
            phase="launch",
            exit_code=1,
            log_path="" if log_path is None else str(log_path),
        ),
        success=False,
        message="worker died",
        output=output,
        payload=None,
        error=error,
    )


def test_chop_failure_persists_record() -> None:
    from sase.ace.tui.actions.axe_chop_run import AxeChopRunMixin

    class _ChopApp(AxeChopRunMixin):
        def __init__(self) -> None:
            self.notifications: list[tuple[str, str | None]] = []

        def notify(self, msg: str, *, severity: str | None = None) -> None:
            self.notifications.append((msg, severity))

        def _schedule_axe_async_refresh(self) -> None:
            pass

    match = SimpleNamespace(
        chop=SimpleNamespace(name="my-chop"),
        lumberjack=SimpleNamespace(chop_timeout=30, wait_runners=None),
    )
    app = _ChopApp()
    with (
        patch(
            "sase.ace.tui.actions.axe_chop_run.load_axe_config",
            return_value=object(),
        ),
        patch(
            "sase.ace.tui.actions.axe_chop_run.find_configured_chop",
            return_value=match,
        ),
        patch(
            "sase.ace.tui.actions.axe_chop_run.run_configured_chop_once",
            side_effect=RuntimeError("chop boom"),
        ),
    ):
        asyncio.run(app._launch_chop_run_async("lumber", "my-chop"))
    record = _assert_persisted("chop")
    assert record["chop"] == "my-chop"
    assert record["lumberjack"] == "lumber"
    assert app.notifications[-1] == (
        "Failed to launch chop 'my-chop': chop boom - press ,L for the log entry",
        "error",
    )


def test_payloadless_launch_task_failure_persists_record() -> None:
    from sase.ace.tui.actions.agent_workflow._launch_procs import LaunchProcMixin

    class _TaskApp(LaunchProcMixin):
        def __init__(self) -> None:
            self.notifications: list[tuple[str, str | None]] = []

        def notify(self, msg: str, *, severity: str | None = None) -> None:
            self.notifications.append((msg, severity))

    app = _TaskApp()
    app._on_launch_proc_complete(_payloadless_completion(output="captured output"))

    assert app.notifications == [
        ("Launch failed - press ,L for the log entry", "error")
    ]
    record = _assert_persisted("single")
    assert record["display_name"] == "launch cl"
    assert record["stage"] == "launch_proc"
    assert record["proc_id"] == "task-1"
    assert record["output"] == "captured output"
    assert record["status"] == "error"
    assert record["phase"] == "launch"
    assert record["exit_code"] == 1
    assert record["command"] == "sase run 'do work'"
    assert record["proc_message"] == "terminal proc message"
    assert "project_file" not in record


def test_payloadless_launch_failure_recovers_proc_log_tail_and_prompt(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.actions.agent_workflow._launch_procs import (
        _log_payloadless_launch_failure,
    )

    log_path = tmp_path / "proc.log"
    log_path.write_text(
        "".join(f"line {idx}\n" for idx in range(80))
        + "XPromptArgumentError: invalid priority\n"
        + "".join(f"tail {idx}\n" for idx in range(80, 250)),
        encoding="utf-8",
    )
    error_id = "err_260617_143000_7f3a9c"
    prompt = "p" * 250

    _log_payloadless_launch_failure(
        _payloadless_completion(output="", log_path=log_path),
        error_id=error_id,
        submitted_prompt=prompt,
    )

    record = _assert_persisted("single")
    assert record["error_id"] == error_id
    assert record["exc_message"] == "worker died"
    assert len(record["prompt_preview"]) == 200
    assert record["log_path"] == str(log_path)
    assert "XPromptArgumentError: invalid priority" in record["output"]
    assert "tail 249" in record["output"]
    assert "line 0" not in record["output"]
    human = launch_failures_log_path().read_text()
    assert "process output:" in human
    assert "    XPromptArgumentError: invalid priority" in human


def test_payloadless_launch_failure_prefers_preloaded_output() -> None:
    from sase.ace.tui.actions.agent_workflow._launch_procs import (
        _log_payloadless_launch_failure,
    )

    with patch("sase.procs.read_proc_log_tail") as read_tail:
        _log_payloadless_launch_failure(
            _payloadless_completion(output="already captured"),
            error_id="err_260617_143000_7f3a9c",
        )

    read_tail.assert_not_called()
    record = _assert_persisted("single")
    assert record["output"] == "already captured"


def test_payloadless_launch_output_is_char_bounded() -> None:
    from sase.ace.tui.actions.agent_workflow import _launch_procs

    large = (
        "discarded-prefix"
        + ("x" * _launch_procs._FAILED_LAUNCH_OUTPUT_CHAR_LIMIT)
        + "new"
    )
    _launch_procs._log_payloadless_launch_failure(
        _payloadless_completion(output=large),
        error_id="err_260617_143000_7f3a9c",
    )

    record = _assert_persisted("single")
    assert len(record["output"]) == _launch_procs._FAILED_LAUNCH_OUTPUT_CHAR_LIMIT
    assert record["output"].startswith(
        _launch_procs._FAILED_LAUNCH_OUTPUT_TRUNCATED_MARKER
    )
    assert record["output"].endswith("new")
    assert "discarded-prefix" not in record["output"]


def test_chop_missing_script_outcome_persists_record() -> None:
    from sase.ace.tui.actions.axe_chop_run import AxeChopRunMixin
    from sase.axe.chop_runner_types import ChopRunOutcome

    class _ChopApp(AxeChopRunMixin):
        def __init__(self) -> None:
            self.notifications: list[tuple[str, str | None]] = []

        def notify(self, msg: str, *, severity: str | None = None) -> None:
            self.notifications.append((msg, severity))

        def _schedule_axe_async_refresh(self) -> None:
            pass

    match = SimpleNamespace(
        chop=SimpleNamespace(name="my-chop"),
        lumberjack=SimpleNamespace(chop_timeout=30, wait_runners=None),
    )
    outcome = ChopRunOutcome(
        lumberjack_name="lumber",
        chop_name="my-chop",
        status="missing_script",
        run_id="run-1",
        error=RuntimeError("script not found"),
        traceback="script traceback",
    )
    app = _ChopApp()
    with (
        patch(
            "sase.ace.tui.actions.axe_chop_run.load_axe_config",
            return_value=object(),
        ),
        patch(
            "sase.ace.tui.actions.axe_chop_run.find_configured_chop",
            return_value=match,
        ),
        patch(
            "sase.ace.tui.actions.axe_chop_run.run_configured_chop_once",
            return_value=outcome,
        ),
    ):
        asyncio.run(app._launch_chop_run_async("lumber", "my-chop"))

    assert app.notifications[-1] == (
        "Chop 'my-chop': script not found - press ,L for the log entry",
        "error",
    )
    record = _assert_persisted("chop")
    assert record["chop"] == "my-chop"
    assert record["lumberjack"] == "lumber"
    assert record["status"] == "missing_script"
    assert record["run_id"] == "run-1"
