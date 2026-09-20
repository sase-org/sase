"""Tests for the oneshot-backed ``!`` background command path.

Covers:
- ``run_bgcmd_launch`` standalone behavior: success, checkout failure,
  sase_hg_clean warning captured to stdout, and oneshot-submit failure.
- ``AxeBgCmdMixin._start_bgcmd`` dispatcher: submits a launch operation and
  returns immediately without doing VCS work on the calling thread; fires the
  "Starting:" toast on submit; the success callback writes history and asks
  for a Services refresh; dedup rejection releases the in-memory slot
  reservation; the synthetic dedup-key path for the no-CL case produces a
  slot-scoped warning.
- Slot choice from cached state, and the kill / dismiss actions on durable
  oneshot rows and legacy slot directories.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

from tests.ace.tui._axe_collector_helpers import make_bgcmd_info

from sase.ace.tui.actions.axe_bgcmd import AxeBgCmdMixin
from sase.axe.bgcmd_operations import run_bgcmd_launch
from sase.ops.names import AXE_BGCMD, PROC_KILL
from sase.procs import ProcSubmitError

# ---------------------------------------------------------------------------
# run_bgcmd_launch
# ---------------------------------------------------------------------------


_PATCH_CLEAN = "sase.axe.bgcmd_operations.run_sase_hg_clean"
_PATCH_VCS = "sase.axe.bgcmd_operations.get_vcs_provider"
_PATCH_SUBMIT = "sase.axe.bgcmd_operations.submit_oneshot"


def _proc(proc_id: str = "proc-1", pid: int | None = 4242) -> Any:
    return MagicMock(proc_id=proc_id, pid=pid)


def test_launch_task_success_with_cl_submits_oneshot_after_checkout() -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "rev1"
    provider.checkout.return_value = (True, None)
    with (
        patch(_PATCH_CLEAN, return_value=(True, None)),
        patch(_PATCH_VCS, return_value=provider),
        patch(_PATCH_SUBMIT, return_value=_proc()) as submit,
    ):
        ok, msg, payload = run_bgcmd_launch(
            slot=3,
            command="make test",
            project="proj",
            workspace_num=1,
            workspace_dir="/ws/1",
            cl_name="CL-42",
        )

    assert ok is True
    assert "Started oneshot #3" in msg
    provider.checkout.assert_called_once_with("rev1", "/ws/1")
    submit.assert_called_once_with(
        ["sh", "-c", "make test"],
        label="make test",
        cwd="/ws/1",
        project="proj",
        workspace_num=1,
        cl_name="CL-42",
        slot=3,
    )
    assert payload["proc_id"] == "proc-1"
    assert payload["slot"] == 3


def test_launch_task_success_without_cl_skips_checkout() -> None:
    with (
        patch(_PATCH_CLEAN) as clean,
        patch(_PATCH_VCS) as vcs,
        patch(_PATCH_SUBMIT, return_value=_proc()),
    ):
        ok, msg, _payload = run_bgcmd_launch(
            slot=2,
            command="echo hi",
            project="proj",
            workspace_num=1,
            workspace_dir="/ws/1",
            cl_name=None,
        )

    assert ok is True
    assert "Started oneshot #2" in msg
    clean.assert_not_called()
    vcs.assert_not_called()


def test_launch_task_checkout_failure_returns_failure_without_submitting() -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "rev1"
    provider.checkout.return_value = (False, "dirty tree")
    with (
        patch(_PATCH_CLEAN, return_value=(True, None)),
        patch(_PATCH_VCS, return_value=provider),
        patch(_PATCH_SUBMIT) as submit,
    ):
        ok, msg, _payload = run_bgcmd_launch(
            slot=1,
            command="make",
            project="proj",
            workspace_num=1,
            workspace_dir="/ws/1",
            cl_name="CL-1",
        )

    assert ok is False
    assert "checkout failed" in msg
    submit.assert_not_called()


def test_launch_task_submit_failure_returns_failure() -> None:
    with (
        patch(_PATCH_CLEAN, return_value=(True, None)),
        patch(_PATCH_VCS),
        patch(
            _PATCH_SUBMIT,
            side_effect=ProcSubmitError('proc conflict on concurrency_key "x"'),
        ),
    ):
        ok, msg, payload = run_bgcmd_launch(
            slot=5,
            command="make",
            project="proj",
            workspace_num=1,
            workspace_dir="/ws/1",
            cl_name=None,
        )

    assert ok is False
    assert "Failed to start background command" in msg
    assert "concurrency_key" in msg
    assert payload["slot"] == 5


def test_launch_task_clean_warning_does_not_abort_and_is_printed(capsys) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "rev"
    provider.checkout.return_value = (True, None)
    with (
        patch(_PATCH_CLEAN, return_value=(False, "dirty")),
        patch(_PATCH_VCS, return_value=provider),
        patch(_PATCH_SUBMIT, return_value=_proc()),
    ):
        ok, _, _payload = run_bgcmd_launch(
            slot=4,
            command="make",
            project="proj",
            workspace_num=1,
            workspace_dir="/ws/1",
            cl_name="CL-9",
        )

    assert ok is True
    captured = capsys.readouterr()
    assert "sase_hg_clean failed" in captured.out


# ---------------------------------------------------------------------------
# Fake app shared by the dispatcher / kill / dismiss tests
# ---------------------------------------------------------------------------


class _FakeApp(AxeBgCmdMixin):
    """Minimal fake exposing just what the dispatcher needs."""

    def __init__(self) -> None:
        self.current_tab: Any = "patches"
        self.current_idx = 0
        self.axe_running = False
        self.patches = []  # type: ignore[assignment]
        self._bgcmd_slots = []
        self._bgcmd_pending_slots = {}
        self._bgcmd_dismissed = set()
        self._bgcmd_focus_slot = None
        self._axe_bgcmd_details: dict[int, Any] = {}
        self.notifications: list[tuple[str, str]] = []
        self.submit_calls: list[dict[str, Any]] = []
        self.submit_return: bool = True
        self.load_count: int = 0
        self.switched_view: Any = None
        self.workers: list[Any] = []
        self.pushed: list[tuple[Any, Any]] = []
        self.count_updates = 0
        self.item_builds = 0
        self.display_refreshes = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _submit_durable_proc(self, *args: object, **kwargs: Any) -> object:
        self.submit_calls.append({"args": args, "kwargs": kwargs})
        return object() if self.submit_return else False

    def _load_bgcmd_state(self) -> None:
        self.load_count += 1

    def _switch_to_axe_view(self, view: Any) -> None:
        self.switched_view = view

    def run_worker(self, fn: Any, **kwargs: Any) -> None:
        self.workers.append((fn, kwargs))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed.append((modal, callback))

    def _update_bgcmd_count(self) -> None:
        self.count_updates += 1

    def _build_axe_items(self) -> None:
        self.item_builds += 1

    def _refresh_axe_display(self) -> None:
        self.display_refreshes += 1


# ---------------------------------------------------------------------------
# _start_bgcmd dispatcher
# ---------------------------------------------------------------------------


def test_start_bgcmd_submits_task_and_returns_without_running_vcs() -> None:
    app = _FakeApp()
    with (
        patch(
            "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
            return_value="/ws/1",
        ),
        patch(_PATCH_CLEAN) as clean,
        patch(_PATCH_VCS) as vcs,
        patch(_PATCH_SUBMIT) as submit,
    ):
        assert AxeBgCmdMixin._start_bgcmd(app, 2, "make", "proj", 1, cl_name="CL-1")

        # Dispatcher must not do any VCS work or submit the oneshot itself on
        # the calling thread.
        clean.assert_not_called()
        vcs.assert_not_called()
        submit.assert_not_called()

    # The slot is reserved in memory while the launch operation is in flight.
    assert app._bgcmd_pending_slots[2] > time.monotonic()

    assert len(app.submit_calls) == 1
    call = app.submit_calls[0]
    assert call["args"] == (
        ["sase", "axe", "bgcmd-launch", "2", "proj", "1", "--json"],
    )
    kwargs = call["kwargs"]
    assert kwargs["operation"] == AXE_BGCMD
    assert kwargs["cl_name"] == "CL-1"
    assert kwargs["project_file"].endswith("/projects/proj/proj.sase")
    # The launch operation must not hold the oneshot's own ``bgcmd-slot:<n>``
    # key, or the oneshot it submits would collide with its own launcher.
    assert kwargs["concurrency_keys"] == ("bgcmd-launch:CL-1", "bgcmd-launch-slot:2")
    assert kwargs["request"] == {
        "cl_name": "CL-1",
        "command": "make",
        "workspace_dir": "/ws/1",
    }
    assert callable(kwargs["on_complete"])

    # "Starting:" toast only — no success/failure toast yet.
    assert app.notifications == [("Starting: make", "information")]
    assert app.load_count == 0
    assert app.switched_view is None


def test_start_bgcmd_on_success_writes_history_and_requests_refresh() -> None:
    app = _FakeApp()
    with patch(
        "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
        return_value="/ws/1",
    ):
        AxeBgCmdMixin._start_bgcmd(app, 7, "make", "proj", 1, cl_name="CL-X")

    on_complete = app.submit_calls[0]["kwargs"]["on_complete"]
    assert callable(on_complete)

    with patch("sase.history.command.add_or_update_command") as add:
        on_complete(MagicMock(success=True))

    add.assert_called_once_with("make", "proj", "CL-X")
    # The new row lands in the next Services refresh, which focuses it; the
    # slot stays reserved until that refresh has seen it.
    assert app.load_count == 1
    assert app._bgcmd_focus_slot == 7
    assert 7 in app._bgcmd_pending_slots


def test_start_bgcmd_on_failure_releases_slot_and_skips_history() -> None:
    app = _FakeApp()
    with patch(
        "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
        return_value="/ws/1",
    ):
        AxeBgCmdMixin._start_bgcmd(app, 7, "make", "proj", 1, cl_name=None)

    on_complete = app.submit_calls[0]["kwargs"]["on_complete"]
    with patch("sase.history.command.add_or_update_command") as add:
        on_complete(MagicMock(success=False))

    add.assert_not_called()
    assert 7 not in app._bgcmd_pending_slots
    assert app._bgcmd_focus_slot is None


def test_start_bgcmd_rerun_uses_recorded_workspace_and_skips_history() -> None:
    app = _FakeApp()
    with patch("sase.ace.tui.actions.axe_bgcmd.get_workspace_directory") as lookup:
        AxeBgCmdMixin._start_bgcmd(
            app,
            2,
            "make",
            "",
            0,
            workspace_dir="/somewhere/else",
            record_history=False,
        )
        lookup.assert_not_called()

    kwargs = app.submit_calls[0]["kwargs"]
    assert kwargs["cwd"] == "/somewhere/else"
    assert kwargs["project_file"] == ""
    assert kwargs["request"]["workspace_dir"] == "/somewhere/else"
    with patch("sase.history.command.add_or_update_command") as add:
        kwargs["on_complete"](MagicMock(success=True))
    add.assert_not_called()


def test_start_bgcmd_workspace_error_does_not_submit_or_reserve_slot() -> None:
    app = _FakeApp()
    with patch(
        "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
        side_effect=RuntimeError("no ws"),
    ):
        assert not AxeBgCmdMixin._start_bgcmd(app, 2, "make", "proj", 1, cl_name="CL-1")

    assert app._bgcmd_pending_slots == {}
    assert app.submit_calls == []
    assert app.notifications == [("Failed to get workspace: no ws", "error")]


def test_start_bgcmd_no_cl_uses_slot_scoped_dedup_key() -> None:
    app = _FakeApp()
    with patch(
        "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
        return_value="/ws/1",
    ):
        AxeBgCmdMixin._start_bgcmd(app, 4, "make", "proj", 1, cl_name=None)

    assert app.submit_calls[0]["kwargs"]["cl_name"] == "bgcmd-slot-4"


def test_start_bgcmd_dedup_rejection_releases_slot_and_warns_synthetic() -> None:
    app = _FakeApp()
    app.submit_return = False
    with patch(
        "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
        return_value="/ws/1",
    ):
        assert not AxeBgCmdMixin._start_bgcmd(app, 4, "make", "proj", 1, cl_name=None)

    # Reservation released so the slot isn't leaked.
    assert 4 not in app._bgcmd_pending_slots
    # Synthetic-key path gets the friendlier warning.
    assert any(
        "bgcmd launch is already in flight for slot 4" in msg
        for msg, _ in app.notifications
    )


def test_start_bgcmd_dedup_rejection_with_cl_key_skips_synthetic_warning() -> None:
    app = _FakeApp()
    app.submit_return = False
    with patch(
        "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
        return_value="/ws/1",
    ):
        AxeBgCmdMixin._start_bgcmd(app, 4, "make", "proj", 1, cl_name="CL-42")

    assert 4 not in app._bgcmd_pending_slots
    # No synthetic warning — the stock _submit_proc warning (fired
    # inside the real impl) is the user-visible dedup message.
    assert not any(
        "bgcmd launch is already in flight" in msg for msg, _ in app.notifications
    )
    # And definitely no "Starting:" toast since submission failed.
    assert not any("Starting:" in msg for msg, _ in app.notifications)


# ---------------------------------------------------------------------------
# Slot choice from cached state
# ---------------------------------------------------------------------------


def _running(slot: int) -> Any:
    return make_bgcmd_info(proc_id=f"proc-{slot}", status="running")


def _done(slot: int, *, finished: str = "2026-04-23T00:01:00") -> Any:
    return make_bgcmd_info(
        proc_id=f"proc-{slot}",
        status="success",
        exit_code=0,
        finished_at=finished,
    )


def test_next_bgcmd_slot_prefers_lowest_free_and_skips_pending() -> None:
    app = _FakeApp()
    assert app._next_bgcmd_slot() == 1

    app._bgcmd_slots = [(1, _running(1))]
    assert app._next_bgcmd_slot() == 2

    app._reserve_bgcmd_slot(2)
    assert app._next_bgcmd_slot() == 3


def test_next_bgcmd_slot_ignores_expired_reservation() -> None:
    app = _FakeApp()
    app._bgcmd_pending_slots = {1: time.monotonic() - 1.0}
    assert app._next_bgcmd_slot() == 1


def test_next_bgcmd_slot_reuses_oldest_finished_index_when_history_is_full() -> None:
    app = _FakeApp()
    app._bgcmd_slots = [
        (slot, _done(slot, finished=f"2026-04-23T00:0{slot}:00"))
        for slot in range(1, 10)
    ]
    # A new command never blocks on finished history: reuse the oldest index.
    assert app._next_bgcmd_slot() == 1


def test_next_bgcmd_slot_is_none_only_when_nine_are_running() -> None:
    app = _FakeApp()
    app._bgcmd_slots = [(slot, _running(slot)) for slot in range(1, 10)]
    assert app._next_bgcmd_slot() is None


def test_next_bgcmd_slot_never_reuses_a_legacy_slot_directory() -> None:
    app = _FakeApp()
    legacy = make_bgcmd_info(status="done")
    app._bgcmd_slots = [(1, legacy)]
    assert app._next_bgcmd_slot() == 2


def test_action_start_bgcmd_reports_when_nine_are_running() -> None:
    app = _FakeApp()
    app._bgcmd_slots = [(slot, _running(slot)) for slot in range(1, 10)]

    app.action_start_bgcmd()

    assert app.notifications == [
        ("Maximum background commands reached (9 running)", "error")
    ]


# ---------------------------------------------------------------------------
# Kill / dismiss
# ---------------------------------------------------------------------------


def test_confirm_kill_on_finished_row_dismisses_without_confirmation() -> None:
    app = _FakeApp()
    info = _done(3)
    survivor = _running(4)
    app._bgcmd_slots = [(3, info), (4, survivor)]
    app._axe_bgcmd_details = {3: MagicMock(), 4: MagicMock()}

    with patch("sase.ace.tui.actions.axe_bgcmd.dismiss_background_command") as dismiss:
        app._confirm_kill_bgcmd(3)
        # The persistence runs off-thread via the recorded worker.
        ((fn, kwargs),) = app.workers
        assert kwargs["thread"] is True
        fn()
        dismiss.assert_called_once_with(3, info)

    assert app.pushed == []
    assert app._bgcmd_slots == [(4, survivor)]
    assert 3 not in app._axe_bgcmd_details
    assert "proc-3" in app._bgcmd_dismissed
    assert app.notifications == [("Cleared: sleep 1", "information")]
    assert app.item_builds == 1
    assert app.display_refreshes == 1


def test_dismissing_last_row_switches_back_to_the_axe_view() -> None:
    app = _FakeApp()
    app._bgcmd_slots = [(3, _done(3))]

    app._confirm_kill_bgcmd(3)

    assert app.switched_view == "axe"


def test_confirm_kill_on_running_row_asks_first_then_submits_durable_kill() -> None:
    app = _FakeApp()
    info = _running(2)
    app._bgcmd_slots = [(2, info)]

    app._confirm_kill_bgcmd(2)

    ((modal, callback),) = app.pushed
    assert type(modal).__name__ == "ConfirmKillModal"
    # Nothing is killed until the user confirms.
    assert app.submit_calls == []
    callback(False)
    assert app.submit_calls == []

    callback(True)
    (call,) = app.submit_calls
    assert call["args"] == (["sase", "proc", "kill", "proc-2", "--json"],)
    kwargs = call["kwargs"]
    assert kwargs["operation"] == PROC_KILL
    assert kwargs["request"] == {"proc_id": "proc-2", "proc_label": "sleep 1"}
    # The row stays until the durable kill lands.
    assert app._bgcmd_slots == [(2, info)]

    kwargs["on_complete"](MagicMock(success=False))
    assert app._bgcmd_slots == [(2, info)]

    kwargs["on_complete"](MagicMock(success=True))
    assert app._bgcmd_slots == []
    assert any(msg.startswith("Stopped: ") for msg, _ in app.notifications)


def test_stopping_a_legacy_slot_signals_the_process_group_directly() -> None:
    app = _FakeApp()
    legacy = make_bgcmd_info(status="running")
    app._bgcmd_slots = [(6, legacy)]

    with patch("sase.ace.tui.actions.axe_bgcmd.stop_legacy_background_command") as stop:
        app._stop_bgcmd(6, legacy)

    stop.assert_called_once_with(6)
    assert app.submit_calls == []
    assert app._bgcmd_slots == []
    assert "legacy:6" in app._bgcmd_dismissed
