"""Tests for the re-run affordance on the AXE tab.

Covers:
- `_rerun_bgcmd` behavior: running/none/no-slot/happy-path.
- `action_run_workflow` dispatch on the AXE tab.
- `_compute_axe_bindings` includes the re-run binding when a done bgcmd is selected.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.axe_bgcmd import AxeBgCmdMixin
from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.widgets.bgcmd_list import (
    AxeParentItem,
    BgCmdItem,
    LumberjackItem,
)


def _make_info(slot: int = 1) -> BackgroundCommandInfo:
    return BackgroundCommandInfo(
        command=f"echo slot {slot}",
        project="myproj",
        workspace_num=2,
        workspace_dir="/tmp/work/myproj_2",
        started_at="2026-04-23T12:00:00",
        pid=None,
        finished_at="2026-04-23T12:00:01",
    )


class _FakeRerunApp(AxeBgCmdMixin, BaseActionsMixin):
    """Minimal fake with exactly what the re-run path and dispatcher use."""

    def __init__(self) -> None:
        self.current_tab: Any = "axe"
        self.current_idx = 0
        self.axe_running = False
        self.changespecs = []  # type: ignore[assignment]
        self._bgcmd_slots = []
        self._axe_items = [AxeParentItem()]
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.load_count: int = 0
        self.switched_view: Any = None
        self.rerun_calls: list[int] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _load_bgcmd_state(self) -> None:
        self.load_count += 1

    def _switch_to_axe_view(self, view: Any) -> None:
        self.switched_view = view

    # Used by the dispatch test to assert the correct slot is re-run.
    def _rerun_bgcmd(self, slot: int) -> None:  # type: ignore[override]
        self.rerun_calls.append(slot)


def test_rerun_bgcmd_running_slot_is_noop() -> None:
    """If the slot is still running, `_rerun_bgcmd` is a no-op."""
    app = _FakeRerunApp()
    with (
        patch(
            "sase.ace.tui.actions.axe_bgcmd.get_slot_info", return_value=_make_info(1)
        ),
        patch("sase.ace.tui.actions.axe_bgcmd.is_slot_running", return_value=True),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.find_first_available_slot",
            return_value=2,
        ),
        patch("sase.ace.tui.actions.axe_bgcmd.start_background_command") as start,
        patch("sase.ace.tui.actions.axe_bgcmd.clear_slot") as clear,
    ):
        # Undo the test-override to exercise the real mixin method.
        real_method = AxeBgCmdMixin._rerun_bgcmd
        real_method(app, 1)
        assert app.pushed_modals == []
        assert app.notifications == []
        start.assert_not_called()
        clear.assert_not_called()


def test_rerun_bgcmd_missing_info_is_noop() -> None:
    """If slot info has vanished, `_rerun_bgcmd` is a no-op."""
    app = _FakeRerunApp()
    with (
        patch("sase.ace.tui.actions.axe_bgcmd.get_slot_info", return_value=None),
        patch("sase.ace.tui.actions.axe_bgcmd.is_slot_running", return_value=False),
        patch("sase.ace.tui.actions.axe_bgcmd.start_background_command") as start,
        patch("sase.ace.tui.actions.axe_bgcmd.clear_slot") as clear,
    ):
        AxeBgCmdMixin._rerun_bgcmd(app, 1)
        assert app.pushed_modals == []
        assert app.notifications == []
        start.assert_not_called()
        clear.assert_not_called()


def test_rerun_bgcmd_no_available_slot_notifies_without_prompt() -> None:
    """If all slots are full, notify and skip the prompt; don't clear anything."""
    app = _FakeRerunApp()
    with (
        patch(
            "sase.ace.tui.actions.axe_bgcmd.get_slot_info", return_value=_make_info(1)
        ),
        patch("sase.ace.tui.actions.axe_bgcmd.is_slot_running", return_value=False),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.find_first_available_slot",
            return_value=None,
        ),
        patch("sase.ace.tui.actions.axe_bgcmd.start_background_command") as start,
        patch("sase.ace.tui.actions.axe_bgcmd.clear_slot") as clear,
    ):
        AxeBgCmdMixin._rerun_bgcmd(app, 1)

    assert app.pushed_modals == []
    assert app.notifications == [
        ("Maximum background commands reached", "error"),
    ]
    start.assert_not_called()
    clear.assert_not_called()


def test_rerun_bgcmd_yes_clears_original_and_starts_new_slot() -> None:
    """Yes-path: clear original slot, start the same command in a fresh slot."""
    app = _FakeRerunApp()
    info = _make_info(1)

    with (
        patch("sase.ace.tui.actions.axe_bgcmd.get_slot_info", return_value=info),
        patch("sase.ace.tui.actions.axe_bgcmd.is_slot_running", return_value=False),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.find_first_available_slot",
            return_value=2,
        ),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.start_background_command",
            return_value=12345,
        ) as start,
        patch("sase.ace.tui.actions.axe_bgcmd.clear_slot") as clear,
    ):
        AxeBgCmdMixin._rerun_bgcmd(app, 1)

        # One modal pushed — the confirm modal — awaiting the y/n callback.
        assert len(app.pushed_modals) == 1
        callback = app.pushed_callbacks[0]
        assert callback is not None

        # Simulate user pressing `y`.
        callback(True)

    clear.assert_called_once_with(1)
    start.assert_called_once_with(
        slot=2,
        command=info.command,
        project=info.project,
        workspace_num=info.workspace_num,
        workspace_dir=info.workspace_dir,
    )
    assert app.load_count == 1
    assert app.switched_view == 2
    assert any("Re-running" in msg for msg, _ in app.notifications)


def test_rerun_bgcmd_no_keeps_original_and_starts_new_slot() -> None:
    """No-path: keep the original entry; still start in a fresh slot."""
    app = _FakeRerunApp()
    info = _make_info(1)

    with (
        patch("sase.ace.tui.actions.axe_bgcmd.get_slot_info", return_value=info),
        patch("sase.ace.tui.actions.axe_bgcmd.is_slot_running", return_value=False),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.find_first_available_slot",
            return_value=3,
        ),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.start_background_command",
            return_value=12345,
        ) as start,
        patch("sase.ace.tui.actions.axe_bgcmd.clear_slot") as clear,
    ):
        AxeBgCmdMixin._rerun_bgcmd(app, 1)
        callback = app.pushed_callbacks[0]
        # Simulate user pressing `n`.
        callback(False)

    clear.assert_not_called()
    start.assert_called_once_with(
        slot=3,
        command=info.command,
        project=info.project,
        workspace_num=info.workspace_num,
        workspace_dir=info.workspace_dir,
    )
    assert app.switched_view == 3


def test_rerun_bgcmd_cancel_does_nothing() -> None:
    """Cancel-path (escape): no clear, no start, no notification."""
    app = _FakeRerunApp()
    info = _make_info(1)

    with (
        patch("sase.ace.tui.actions.axe_bgcmd.get_slot_info", return_value=info),
        patch("sase.ace.tui.actions.axe_bgcmd.is_slot_running", return_value=False),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.find_first_available_slot",
            return_value=2,
        ),
        patch("sase.ace.tui.actions.axe_bgcmd.start_background_command") as start,
        patch("sase.ace.tui.actions.axe_bgcmd.clear_slot") as clear,
    ):
        AxeBgCmdMixin._rerun_bgcmd(app, 1)
        callback = app.pushed_callbacks[0]
        callback(None)

    clear.assert_not_called()
    start.assert_not_called()
    assert app.switched_view is None
    assert app.notifications == []


# --- action_run_workflow dispatch on the AXE tab ---


def test_action_run_workflow_axe_done_bgcmd_dispatches_to_rerun() -> None:
    """Done BgCmdItem selection routes `r` to `_rerun_bgcmd`."""
    app = _FakeRerunApp()
    app._axe_items = [AxeParentItem(), BgCmdItem(slot=5)]
    app.current_idx = 1

    with patch("sase.ace.tui.bgcmd.is_slot_running", return_value=False):
        BaseActionsMixin.action_run_workflow(app)

    assert app.rerun_calls == [5]


def test_action_run_workflow_axe_running_bgcmd_is_noop() -> None:
    """Running BgCmdItem does not dispatch to re-run."""
    app = _FakeRerunApp()
    app._axe_items = [AxeParentItem(), BgCmdItem(slot=5)]
    app.current_idx = 1

    with patch("sase.ace.tui.bgcmd.is_slot_running", return_value=True):
        BaseActionsMixin.action_run_workflow(app)

    assert app.rerun_calls == []


def test_action_run_workflow_axe_non_bgcmd_is_noop() -> None:
    """AxeParentItem / LumberjackItem do not dispatch to re-run."""
    app = _FakeRerunApp()
    app._axe_items = [AxeParentItem(), LumberjackItem(name="hooks")]

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
