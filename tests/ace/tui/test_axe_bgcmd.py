"""Tests for the non-blocking bgcmd launch path.

Covers:
- ``_bgcmd_launch_task`` standalone behavior: success, checkout failure,
  sase_hg_clean warning captured to stdout, subprocess-spawn failure, and
  pending-marker cleanup in every exit path.
- ``AxeBgCmdMixin._start_bgcmd`` dispatcher: submits a task and returns
  immediately without doing VCS work on the calling thread; fires the
  "Starting:" toast on submit; success callback writes history and switches
  view; dedup rejection clears the pending marker; synthetic dedup-key path
  for the no-CL case produces a slot-scoped warning.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.axe_bgcmd import AxeBgCmdMixin, _bgcmd_launch_task
from sase.ace.tui import bgcmd as bgcmd_module


# ---------------------------------------------------------------------------
# _bgcmd_launch_task
# ---------------------------------------------------------------------------


_PATCH_CLEAN = "sase.ace.tui.actions.axe_bgcmd.run_sase_hg_clean"
_PATCH_VCS = "sase.ace.tui.actions.axe_bgcmd.get_vcs_provider"
_PATCH_START = "sase.ace.tui.actions.axe_bgcmd.start_background_command"


class _TmpBgcmdDir:
    """Context manager patching BGCMD_STATE_DIR to a tmpdir."""

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name)
        self._patch = patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", path)
        self._patch.start()
        return path

    def __exit__(self, *args: Any) -> None:
        del args
        self._patch.stop()
        self._tmp.cleanup()


def test_launch_task_success_with_cl_returns_success_and_clears_pending() -> None:
    with _TmpBgcmdDir() as tmp:
        bgcmd_module.mark_slot_pending(3)
        assert bgcmd_module._is_slot_pending(3)

        provider = MagicMock()
        provider.resolve_revision.return_value = "rev1"
        provider.checkout.return_value = (True, None)
        with (
            patch(_PATCH_CLEAN, return_value=(True, None)),
            patch(_PATCH_VCS, return_value=provider),
            patch(_PATCH_START, return_value=4242),
        ):
            ok, msg = _bgcmd_launch_task(
                slot=3,
                command="make test",
                project="proj",
                workspace_num=1,
                workspace_dir="/ws/1",
                cl_name="CL-42",
            )

        assert ok is True
        assert "Started bgcmd in slot 3" in msg
        assert not bgcmd_module._is_slot_pending(3)
        assert not (tmp / "3" / "pending").exists()


def test_launch_task_success_without_cl_skips_checkout() -> None:
    with _TmpBgcmdDir():
        bgcmd_module.mark_slot_pending(2)

        with (
            patch(_PATCH_CLEAN) as clean,
            patch(_PATCH_VCS) as vcs,
            patch(_PATCH_START, return_value=99),
        ):
            ok, msg = _bgcmd_launch_task(
                slot=2,
                command="echo hi",
                project="proj",
                workspace_num=1,
                workspace_dir="/ws/1",
                cl_name=None,
            )

        assert ok is True
        assert "Started bgcmd in slot 2" in msg
        clean.assert_not_called()
        vcs.assert_not_called()
        assert not bgcmd_module._is_slot_pending(2)


def test_launch_task_checkout_failure_returns_failure_and_clears_pending() -> None:
    with _TmpBgcmdDir():
        bgcmd_module.mark_slot_pending(1)

        provider = MagicMock()
        provider.resolve_revision.return_value = "rev1"
        provider.checkout.return_value = (False, "dirty tree")
        with (
            patch(_PATCH_CLEAN, return_value=(True, None)),
            patch(_PATCH_VCS, return_value=provider),
            patch(_PATCH_START) as start,
        ):
            ok, msg = _bgcmd_launch_task(
                slot=1,
                command="make",
                project="proj",
                workspace_num=1,
                workspace_dir="/ws/1",
                cl_name="CL-1",
            )

        assert ok is False
        assert "checkout failed" in msg
        start.assert_not_called()
        assert not bgcmd_module._is_slot_pending(1)


def test_launch_task_spawn_failure_returns_failure_and_clears_pending() -> None:
    with _TmpBgcmdDir():
        bgcmd_module.mark_slot_pending(5)

        with (
            patch(_PATCH_CLEAN, return_value=(True, None)),
            patch(_PATCH_VCS),
            patch(_PATCH_START, return_value=None),
        ):
            ok, msg = _bgcmd_launch_task(
                slot=5,
                command="make",
                project="proj",
                workspace_num=1,
                workspace_dir="/ws/1",
                cl_name=None,
            )

        assert ok is False
        assert "Failed to start background command" in msg
        assert not bgcmd_module._is_slot_pending(5)


def test_launch_task_clean_warning_does_not_abort_and_is_printed(capsys) -> None:
    with _TmpBgcmdDir():
        bgcmd_module.mark_slot_pending(4)

        provider = MagicMock()
        provider.resolve_revision.return_value = "rev"
        provider.checkout.return_value = (True, None)
        with (
            patch(_PATCH_CLEAN, return_value=(False, "dirty")),
            patch(_PATCH_VCS, return_value=provider),
            patch(_PATCH_START, return_value=123),
        ):
            ok, _ = _bgcmd_launch_task(
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
        assert not bgcmd_module._is_slot_pending(4)


# ---------------------------------------------------------------------------
# find_first_available_slot honors pending marker
# ---------------------------------------------------------------------------


def test_find_first_available_slot_skips_pending() -> None:
    with _TmpBgcmdDir():
        bgcmd_module.mark_slot_pending(1)
        assert bgcmd_module.find_first_available_slot() == 2

        bgcmd_module.mark_slot_pending(2)
        assert bgcmd_module.find_first_available_slot() == 3


# ---------------------------------------------------------------------------
# _start_bgcmd dispatcher
# ---------------------------------------------------------------------------


class _FakeApp(AxeBgCmdMixin):
    """Minimal fake exposing just what the dispatcher needs."""

    def __init__(self) -> None:
        self.current_tab: Any = "changespecs"
        self.current_idx = 0
        self.axe_running = False
        self.changespecs = []  # type: ignore[assignment]
        self._bgcmd_slots = []
        self.notifications: list[tuple[str, str]] = []
        self.submit_calls: list[dict[str, Any]] = []
        self.submit_return: bool = True
        self.load_count: int = 0
        self.switched_view: Any = None

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _submit_background_task(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Any,
        on_success: Any = None,
    ) -> bool:
        self.submit_calls.append(
            {
                "task_type": task_type,
                "cl_name": cl_name,
                "project_file": project_file,
                "task_callable": task_callable,
                "on_success": on_success,
            }
        )
        return self.submit_return

    def _load_bgcmd_state(self) -> None:
        self.load_count += 1

    def _switch_to_axe_view(self, view: Any) -> None:
        self.switched_view = view


def test_start_bgcmd_submits_task_and_returns_without_running_vcs() -> None:
    app = _FakeApp()
    with (
        _TmpBgcmdDir(),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
            return_value="/ws/1",
        ),
        patch(_PATCH_CLEAN) as clean,
        patch(_PATCH_VCS) as vcs,
        patch(_PATCH_START) as start,
    ):
        AxeBgCmdMixin._start_bgcmd(app, 2, "make", "proj", 1, cl_name="CL-1")

        # Dispatcher must not do any VCS work on the calling thread.
        clean.assert_not_called()
        vcs.assert_not_called()
        start.assert_not_called()

        # Pending marker is in place while the task is in flight (must be
        # checked inside the tmpdir context).
        assert bgcmd_module._is_slot_pending(2)

    assert len(app.submit_calls) == 1
    call = app.submit_calls[0]
    assert call["task_type"] == "bgcmd-launch"
    assert call["cl_name"] == "CL-1"
    assert call["project_file"].endswith("/projects/proj/proj.gp")
    assert callable(call["task_callable"])
    assert callable(call["on_success"])

    # "Starting:" toast only — no success/failure toast yet.
    assert app.notifications == [("Starting: make", "information")]
    assert app.load_count == 0
    assert app.switched_view is None


def test_start_bgcmd_on_success_writes_history_and_switches_view() -> None:
    app = _FakeApp()
    with (
        _TmpBgcmdDir(),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
            return_value="/ws/1",
        ),
    ):
        AxeBgCmdMixin._start_bgcmd(app, 7, "make", "proj", 1, cl_name="CL-X")

    on_success = app.submit_calls[0]["on_success"]
    assert on_success is not None

    with patch("sase.history.command.add_or_update_command") as add:
        on_success()

    add.assert_called_once_with("make", "proj", "CL-X")
    assert app.load_count == 1
    assert app.switched_view == 7


def test_start_bgcmd_workspace_error_does_not_submit_or_reserve_slot() -> None:
    app = _FakeApp()
    with (
        _TmpBgcmdDir(),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
            side_effect=RuntimeError("no ws"),
        ),
    ):
        AxeBgCmdMixin._start_bgcmd(app, 2, "make", "proj", 1, cl_name="CL-1")
        assert not bgcmd_module._is_slot_pending(2)

    assert app.submit_calls == []
    assert app.notifications == [("Failed to get workspace: no ws", "error")]


def test_start_bgcmd_no_cl_uses_slot_scoped_dedup_key() -> None:
    app = _FakeApp()
    with (
        _TmpBgcmdDir(),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
            return_value="/ws/1",
        ),
    ):
        AxeBgCmdMixin._start_bgcmd(app, 4, "make", "proj", 1, cl_name=None)

    assert app.submit_calls[0]["cl_name"] == "bgcmd-slot-4"


def test_start_bgcmd_dedup_rejection_clears_pending_and_warns_synthetic() -> None:
    app = _FakeApp()
    app.submit_return = False
    with (
        _TmpBgcmdDir(),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
            return_value="/ws/1",
        ),
    ):
        AxeBgCmdMixin._start_bgcmd(app, 4, "make", "proj", 1, cl_name=None)
        # Marker cleared so the slot isn't leaked.
        assert not bgcmd_module._is_slot_pending(4)

    # Synthetic-key path gets the friendlier warning.
    assert any(
        "bgcmd launch is already in flight for slot 4" in msg
        for msg, _ in app.notifications
    )


def test_start_bgcmd_dedup_rejection_with_cl_key_skips_synthetic_warning() -> None:
    app = _FakeApp()
    app.submit_return = False
    with (
        _TmpBgcmdDir(),
        patch(
            "sase.ace.tui.actions.axe_bgcmd.get_workspace_directory",
            return_value="/ws/1",
        ),
    ):
        AxeBgCmdMixin._start_bgcmd(app, 4, "make", "proj", 1, cl_name="CL-42")
        assert not bgcmd_module._is_slot_pending(4)

    # No synthetic warning — the stock _submit_background_task warning (fired
    # inside the real impl) is the user-visible dedup message.
    assert not any(
        "bgcmd launch is already in flight" in msg for msg, _ in app.notifications
    )
    # And definitely no "Starting:" toast since submission failed.
    assert not any("Starting:" in msg for msg, _ in app.notifications)
