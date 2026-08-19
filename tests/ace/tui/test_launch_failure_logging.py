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
    from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
    from sase.ace.tui.proc_queue import ProcInfo

    class _TaskApp(LaunchProcMixin):
        def __init__(self) -> None:
            self.notifications: list[tuple[str, str | None]] = []

        def notify(self, msg: str, *, severity: str | None = None) -> None:
            self.notifications.append((msg, severity))

    app = _TaskApp()
    app._on_launch_proc_complete(
        TrackedProcCompletion(
            proc_info=ProcInfo(
                proc_id="task-1",
                proc_type="launch",
                cl_name="cl",
                project_file="/tmp/proj.sase",
                status="error",
                message="launch cl started",
                started_at=datetime.now(),
                display_name="launch cl",
            ),
            success=False,
            message="worker died",
            output="captured output",
            payload=None,
            error="worker died",
        )
    )

    assert app.notifications == [
        ("Launch failed - press ,L for the log entry", "error")
    ]
    record = _assert_persisted("single")
    assert record["display_name"] == "launch cl"
    assert record["stage"] == "launch_proc"
    assert record["proc_id"] == "task-1"
    assert record["output"] == "captured output"


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
