"""Tests for the re-run affordance on the AXE tab.

Covers:
- `_rerun_bgcmd` behavior: running/none/no-slot/happy-path (durable oneshots).
- `action_run_workflow` dispatch on the AXE tab.
- `_compute_axe_bindings` includes the re-run binding when a done bgcmd is selected.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.axe_bgcmd import AxeBgCmdMixin
from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.widgets.bgcmd_list import (
    BgCmdItem,
    LumberjackItem,
)


def _make_info(
    slot: int = 1, *, status: str = "success", exit_code: int | None = 0
) -> BackgroundCommandInfo:
    return BackgroundCommandInfo(
        command=f"echo slot {slot}",
        project="myproj",
        workspace_num=2,
        workspace_dir="/tmp/work/myproj_2",
        started_at="2026-04-23T12:00:00",
        pid=None,
        finished_at=None if status == "running" else "2026-04-23T12:00:01",
        proc_id=f"proc-{slot}",
        status=status,
        exit_code=exit_code,
    )


class _FakeRerunApp(AxeBgCmdMixin, BaseActionsMixin):
    """Minimal fake with exactly what the re-run path and dispatcher use."""

    def __init__(self) -> None:
        self.current_tab: Any = "axe"
        self.current_idx = 0
        self.axe_running = False
        self.patches = []  # type: ignore[assignment]
        self._bgcmd_slots = []
        self._bgcmd_pending_slots = {}
        self._bgcmd_dismissed = set()
        self._bgcmd_focus_slot = None
        self._axe_items = []
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.rerun_calls: list[int] = []
        self.start_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.dismiss_calls: list[tuple[int, str]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _start_bgcmd(self, *args: Any, **kwargs: Any) -> bool:  # type: ignore[override]
        self.start_calls.append((args, kwargs))
        return True

    def _dismiss_bgcmd(  # type: ignore[override]
        self, slot: int, info: BackgroundCommandInfo, *, verb: str
    ) -> None:
        self.dismiss_calls.append((slot, verb))

    # Used by the dispatch test to assert the correct slot is re-run.
    def _rerun_bgcmd(self, slot: int) -> None:  # type: ignore[override]
        self.rerun_calls.append(slot)


def test_rerun_bgcmd_running_slot_is_noop() -> None:
    """If the slot is still running, `_rerun_bgcmd` is a no-op."""
    app = _FakeRerunApp()
    app._bgcmd_slots = [(1, _make_info(1, status="running", exit_code=None))]

    AxeBgCmdMixin._rerun_bgcmd(app, 1)

    assert app.pushed_modals == []
    assert app.notifications == []
    assert app.start_calls == []
    assert app.dismiss_calls == []


def test_rerun_bgcmd_missing_info_is_noop() -> None:
    """If slot info has vanished, `_rerun_bgcmd` is a no-op."""
    app = _FakeRerunApp()

    AxeBgCmdMixin._rerun_bgcmd(app, 1)

    assert app.pushed_modals == []
    assert app.notifications == []
    assert app.start_calls == []
    assert app.dismiss_calls == []


def test_rerun_bgcmd_no_available_slot_notifies_without_prompt() -> None:
    """With nine commands running, notify and skip the prompt."""
    app = _FakeRerunApp()
    app._bgcmd_slots = [(1, _make_info(1))] + [
        (slot, _make_info(slot, status="running", exit_code=None))
        for slot in range(2, 10)
    ]
    # Slot 1 is finished, so it would be reused; keep it pending to fill all nine.
    app._bgcmd_pending_slots = {1: float("inf")}

    AxeBgCmdMixin._rerun_bgcmd(app, 1)

    assert app.pushed_modals == []
    assert app.notifications == [
        ("Maximum background commands reached (9 running)", "error"),
    ]
    assert app.start_calls == []
    assert app.dismiss_calls == []


def test_rerun_bgcmd_reuses_finished_slot_when_history_fills_every_index() -> None:
    """Finished history never blocks a rerun: the oldest finished index is reused."""
    app = _FakeRerunApp()
    app._bgcmd_slots = [(slot, _make_info(slot)) for slot in range(1, 10)]

    AxeBgCmdMixin._rerun_bgcmd(app, 4)

    assert len(app.pushed_modals) == 1
    app.pushed_callbacks[0](False)
    ((args, _kwargs),) = app.start_calls
    assert args[0] == 1  # oldest finished row's index is reused


def test_rerun_bgcmd_yes_dismisses_original_and_starts_new_slot() -> None:
    """Yes-path: start the same command in a fresh slot, dismiss the original."""
    app = _FakeRerunApp()
    info = _make_info(1)
    app._bgcmd_slots = [(1, info)]

    AxeBgCmdMixin._rerun_bgcmd(app, 1)

    # One modal pushed — the confirm modal — awaiting the y/n callback.
    assert len(app.pushed_modals) == 1
    callback = app.pushed_callbacks[0]
    assert callback is not None

    # Simulate user pressing `y`.
    callback(True)

    assert app.start_calls == [
        (
            (2, info.command, info.project, info.workspace_num),
            {"workspace_dir": info.workspace_dir, "record_history": False},
        )
    ]
    assert app.dismiss_calls == [(1, "Cleared")]


def test_rerun_bgcmd_no_keeps_original_and_starts_new_slot() -> None:
    """No-path: keep the original entry; still start in a fresh slot."""
    app = _FakeRerunApp()
    info = _make_info(1)
    app._bgcmd_slots = [(1, info), (2, _make_info(2, status="running", exit_code=None))]

    AxeBgCmdMixin._rerun_bgcmd(app, 1)
    callback = app.pushed_callbacks[0]
    # Simulate user pressing `n`.
    callback(False)

    assert app.dismiss_calls == []
    assert app.start_calls == [
        (
            (3, info.command, info.project, info.workspace_num),
            {"workspace_dir": info.workspace_dir, "record_history": False},
        )
    ]


def test_rerun_bgcmd_failed_start_keeps_original() -> None:
    """If the launch is rejected, the original entry is not dismissed."""
    app = _FakeRerunApp()
    app._bgcmd_slots = [(1, _make_info(1, status="error", exit_code=2))]
    app._start_bgcmd = lambda *a, **k: False  # type: ignore[method-assign, assignment]

    AxeBgCmdMixin._rerun_bgcmd(app, 1)
    app.pushed_callbacks[0](True)

    assert app.dismiss_calls == []


def test_rerun_bgcmd_cancel_does_nothing() -> None:
    """Cancel-path (escape): no dismiss, no start, no notification."""
    app = _FakeRerunApp()
    app._bgcmd_slots = [(1, _make_info(1))]

    AxeBgCmdMixin._rerun_bgcmd(app, 1)
    callback = app.pushed_callbacks[0]
    callback(None)

    assert app.start_calls == []
    assert app.dismiss_calls == []
    assert app.notifications == []


# --- action_run_workflow dispatch on the AXE tab ---


def test_action_run_workflow_axe_done_bgcmd_dispatches_to_rerun() -> None:
    """Done BgCmdItem selection routes `r` to `_rerun_bgcmd`."""
    app = _FakeRerunApp()
    app._axe_items = [LumberjackItem(name="hooks"), BgCmdItem(slot=5)]
    app._bgcmd_slots = [(5, _make_info(5))]
    app.current_idx = 1

    BaseActionsMixin.action_run_workflow(app)

    assert app.rerun_calls == [5]


def test_action_run_workflow_axe_running_bgcmd_is_noop() -> None:
    """Running BgCmdItem does not dispatch to re-run."""
    app = _FakeRerunApp()
    app._axe_items = [LumberjackItem(name="hooks"), BgCmdItem(slot=5)]
    app._bgcmd_slots = [(5, _make_info(5, status="running", exit_code=None))]
    app.current_idx = 1

    BaseActionsMixin.action_run_workflow(app)

    assert app.rerun_calls == []


def test_action_run_workflow_axe_non_bgcmd_is_noop() -> None:
    """LumberjackItem rows do not dispatch to re-run."""
    app = _FakeRerunApp()
    app._axe_items = [LumberjackItem(name="hooks"), LumberjackItem(name="checks")]

    app.current_idx = 0
    BaseActionsMixin.action_run_workflow(app)
    assert app.rerun_calls == []

    app.current_idx = 1
    BaseActionsMixin.action_run_workflow(app)
    assert app.rerun_calls == []


# --- Footer bindings ---


def test_compute_axe_bindings_includes_rerun_when_done() -> None:
    """`re-run` appears only when the selected slot is done."""
    footer = KeybindingFooter()

    bindings_done = footer._compute_axe_bindings(1, selected_slot_done=True)
    assert ("r", "re-run") in bindings_done

    bindings_running = footer._compute_axe_bindings(1, selected_slot_done=False)
    assert ("r", "re-run") not in bindings_running

    bindings_axe = footer._compute_axe_bindings("axe", selected_slot_done=False)
    assert ("r", "re-run") not in bindings_axe
