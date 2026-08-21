"""Toast + registry invariant tests for registered launch/chop errors."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.failure_messages import notify_registered_error
from sase.ace.tui.keymaps import load_keymap_registry
from sase.logs import clear_registered_errors, last_registered_error


@pytest.fixture(autouse=True)
def _clear_registered_errors() -> Iterator[None]:
    clear_registered_errors()
    yield
    clear_registered_errors()


class _ToastApp:
    def __init__(self, registry: object | None = None) -> None:
        self._keymap_registry = registry
        self.notifications: list[tuple[str, str | None]] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))


def test_notify_registered_error_uses_default_chord_without_registry() -> None:
    app = _ToastApp()

    registered = notify_registered_error(
        app, "Launch failed", error_id="err_260617_143000_7f3a9c"
    )

    assert app.notifications == [
        ("Launch failed - press ,L for the log entry", "error")
    ]
    last = last_registered_error()
    assert last is registered
    assert last is not None
    assert last.summary == "Launch failed"
    assert last.source_id == "launch_failures"
    assert last.error_id == "err_260617_143000_7f3a9c"


def test_notify_registered_error_names_configured_chord() -> None:
    registry = load_keymap_registry(
        {"keymaps": {"modes": {"leader_mode": {"keys": {"jump_to_last_error": "E"}}}}}
    )
    app = _ToastApp(registry)

    notify_registered_error(app, "Launch failed", error_id="err_260617_143000_abcdef")

    assert app.notifications == [
        ("Launch failed - press ,E for the log entry", "error")
    ]
    last = last_registered_error()
    assert last is not None
    assert last.summary == "Launch failed"


def test_payloadless_launch_failure_registers_and_toasts_chord() -> None:
    from sase.ace.tui.actions.agent_workflow._launch_procs import LaunchProcMixin
    from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
    from sase.ace.tui.proc_observer import ObservedProc as ProcInfo

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
    last = last_registered_error()
    assert last is not None
    assert last.summary == "Launch failed"
    assert last.source_id == "launch_failures"


def test_chop_launch_exception_registers_and_toasts_chord() -> None:
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

    assert app.notifications[-1] == (
        "Failed to launch chop 'my-chop': chop boom - press ,L for the log entry",
        "error",
    )
    last = last_registered_error()
    assert last is not None
    assert last.summary == "Failed to launch chop 'my-chop': chop boom"
    assert last.source_id == "launch_failures"


def test_old_log_panel_hint_is_gone_and_chord_hint_has_one_source() -> None:
    src = Path(__file__).resolve().parents[3] / "src"
    old_hits: list[Path] = []
    new_hits: list[Path] = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "see Logs in SASE Admin Center" in text:
            old_hits.append(path)
        if "for the log entry" in text:
            new_hits.append(path)
    assert old_hits == []
    assert [path.name for path in new_hits] == ["failure_messages.py"]
