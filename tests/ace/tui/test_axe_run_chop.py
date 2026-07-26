"""Phase 3: manual chop run dispatch from the AXE tab."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.axe_bgcmd import AxeBgCmdMixin
from sase.ace.tui.actions.axe_chop_run import AxeChopRunMixin
from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.widgets.bgcmd_list import (
    BgCmdItem,
    ChopItem,
    LumberjackItem,
)
from sase.axe.chop_runner import (
    AmbiguousChopError,
    ChopNotFoundError,
    ChopRunOutcome,
)
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig


class _FakeChopApp(AxeChopRunMixin, AxeBgCmdMixin, BaseActionsMixin):
    """Minimal fake exercising the manual chop-run dispatch and async path."""

    def __init__(self) -> None:
        self.current_tab: Any = "axe"
        self.current_idx = 0
        self.axe_running = False
        self.changespecs = []  # type: ignore[assignment]
        self._bgcmd_slots = []
        self._axe_items: list[Any] = []
        self.notifications: list[tuple[str, str]] = []
        self.launched_chops: list[tuple[str, str]] = []
        self.refresh_count = 0
        self.call_later_calls: list[tuple[Any, tuple[Any, ...]]] = []

    def notify(  # type: ignore[override]
        self, message: str, *, severity: str = "information", **_: Any
    ) -> None:
        self.notifications.append((message, severity))

    def call_later(self, fn: Any, *args: Any) -> None:  # type: ignore[override]
        self.call_later_calls.append((fn, args))

    def _schedule_axe_async_refresh(self) -> None:  # type: ignore[override]
        self.refresh_count += 1

    # Stub launch so the dispatch tests don't need the async loop.
    def _launch_chop_run(  # type: ignore[override]
        self, lumberjack_name: str, chop_name: str
    ) -> None:
        self.launched_chops.append((lumberjack_name, chop_name))


def _config_with_chop(
    lumberjack: str = "hooks",
    chop: str = "fast",
    *,
    timeout: int | None = None,
) -> AxeConfig:
    return AxeConfig(
        lumberjacks={
            lumberjack: LumberjackConfig(
                name=lumberjack,
                description=f"Run {lumberjack} TUI test chops",
                interval=60,
                chops=[ChopConfig(name=chop, description="")],
                chop_timeout=timeout,
            )
        }
    )


# --- Dispatch: action_run_workflow on AXE tab ---


def test_action_run_workflow_axe_chop_dispatches_to_run_selected_chop() -> None:
    """ChopItem selection routes `r` to `_run_selected_chop`."""
    app = _FakeChopApp()
    app._axe_items = [
        LumberjackItem(name="hooks"),
        ChopItem(lumberjack_name="hooks", chop_name="fast"),
    ]
    app.current_idx = 1

    BaseActionsMixin.action_run_workflow(app)
    assert app.launched_chops == [("hooks", "fast")]


def test_action_run_workflow_axe_lumberjack_is_noop() -> None:
    """Lumberjack rows do not trigger a chop run."""
    app = _FakeChopApp()
    app._axe_items = [LumberjackItem(name="hooks")]
    app.current_idx = 0

    BaseActionsMixin.action_run_workflow(app)
    assert app.launched_chops == []


def test_action_run_workflow_axe_done_bgcmd_does_not_launch_chop() -> None:
    """Done BgCmdItem still flows through the bgcmd re-run path, not the chop path."""
    app = _FakeChopApp()
    app._axe_items = [BgCmdItem(slot=4)]
    app.current_idx = 0

    rerun_calls: list[int] = []

    def _rerun(slot: int) -> None:
        rerun_calls.append(slot)

    app._rerun_bgcmd = _rerun  # type: ignore[assignment, method-assign]

    with patch("sase.ace.tui.bgcmd.is_slot_running", return_value=False):
        BaseActionsMixin.action_run_workflow(app)

    assert rerun_calls == [4]
    assert app.launched_chops == []


def test_run_selected_chop_outside_axe_tab_is_noop() -> None:
    """Calling the helper on a non-axe tab is a defensive no-op."""
    app = _FakeChopApp()
    app.current_tab = "changespecs"
    app._axe_items = [ChopItem(lumberjack_name="hooks", chop_name="fast")]
    app.current_idx = 0

    AxeChopRunMixin._run_selected_chop(app)
    assert app.launched_chops == []


def test_run_selected_chop_with_lumberjack_row_is_noop() -> None:
    """Selecting a lumberjack row leaves the launch path untouched."""
    app = _FakeChopApp()
    app._axe_items = [LumberjackItem(name="hooks")]
    app.current_idx = 0

    AxeChopRunMixin._run_selected_chop(app)
    assert app.launched_chops == []


# --- _launch_chop_run schedules pump-free ---


@pytest.mark.asyncio
async def test_launch_chop_run_schedules_pump_free_task() -> None:
    """The real launcher creates a retained task outside Textual's pump."""
    app = _FakeChopApp()

    # Call the real mixin method directly, bypassing the fake's override.
    AxeChopRunMixin._launch_chop_run(app, "hooks", "fast")

    tasks = list(app._pump_free_async_tasks)
    assert len(tasks) == 1
    assert tasks[0].get_name() == "sase-axe-chop-run"
    tasks[0].cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


# --- async path: outcomes -> notifications + refresh ---


def _run_async(coro: Any) -> None:
    """Helper: run a coroutine to completion on a fresh loop."""
    asyncio.new_event_loop().run_until_complete(coro)


def test_launch_chop_run_async_success_notifies_and_refreshes() -> None:
    """Success outcome surfaces a positive notification and refreshes AXE."""
    app = _FakeChopApp()
    config = _config_with_chop()
    outcome = ChopRunOutcome(
        lumberjack_name="hooks",
        chop_name="fast",
        status="success",
        run_id="r1",
        exit_code=0,
    )

    with (
        patch("sase.ace.tui.actions.axe_chop_run.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_chop_run.run_configured_chop_once",
            return_value=outcome,
        ) as run_mock,
    ):
        _run_async(app._launch_chop_run_async("hooks", "fast"))

    run_mock.assert_called_once()
    call_kwargs = run_mock.call_args.kwargs
    assert call_kwargs["lumberjack_name"] == "hooks"
    assert call_kwargs["chop"].name == "fast"
    assert call_kwargs["source"] == "manual"
    assert call_kwargs["started_by"] == "ace"

    assert app.refresh_count == 1
    msgs = [m for m, _ in app.notifications]
    assert any("Running chop 'fast'" in m for m in msgs)
    assert any("finished successfully" in m for m in msgs)


def test_launch_chop_run_async_already_running_notifies_warning() -> None:
    """``already_running`` outcome shows a warning notification."""
    app = _FakeChopApp()
    config = _config_with_chop()
    outcome = ChopRunOutcome(
        lumberjack_name="hooks",
        chop_name="fast",
        status="already_running",
        run_id="r1",
    )

    with (
        patch("sase.ace.tui.actions.axe_chop_run.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_chop_run.run_configured_chop_once",
            return_value=outcome,
        ),
    ):
        _run_async(app._launch_chop_run_async("hooks", "fast"))

    severities = {sev for _, sev in app.notifications}
    assert "warning" in severities
    assert any("already running" in m for m, _ in app.notifications)


def test_launch_chop_run_async_runner_exception_notifies_error_and_refreshes() -> None:
    """If the backend raises, the user sees an error and the cache still refreshes."""
    app = _FakeChopApp()
    config = _config_with_chop()

    with (
        patch("sase.ace.tui.actions.axe_chop_run.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_chop_run.run_configured_chop_once",
            side_effect=RuntimeError("kaboom"),
        ),
    ):
        _run_async(app._launch_chop_run_async("hooks", "fast"))

    assert app.refresh_count == 1
    assert any(sev == "error" and "kaboom" in msg for msg, sev in app.notifications)


def test_launch_chop_run_async_not_found_notifies_error() -> None:
    """Chop missing from config surfaces an error and does not call the runner."""
    app = _FakeChopApp()
    config = AxeConfig(lumberjacks={})

    with (
        patch("sase.ace.tui.actions.axe_chop_run.load_axe_config", return_value=config),
        patch("sase.ace.tui.actions.axe_chop_run.run_configured_chop_once") as run_mock,
    ):
        _run_async(app._launch_chop_run_async("hooks", "ghost"))

    run_mock.assert_not_called()
    assert any(sev == "error" for _, sev in app.notifications)


def test_launch_chop_run_async_ambiguous_error_notifies() -> None:
    """``find_configured_chop`` raising AmbiguousChopError is surfaced cleanly."""
    app = _FakeChopApp()

    with (
        patch(
            "sase.ace.tui.actions.axe_chop_run.load_axe_config",
            return_value=_config_with_chop(),
        ),
        patch(
            "sase.ace.tui.actions.axe_chop_run.find_configured_chop",
            side_effect=AmbiguousChopError("fast", ["hooks", "checks"]),
        ),
        patch("sase.ace.tui.actions.axe_chop_run.run_configured_chop_once") as run_mock,
    ):
        _run_async(app._launch_chop_run_async("hooks", "fast"))

    run_mock.assert_not_called()
    assert any(sev == "error" for _, sev in app.notifications)


def test_launch_chop_run_async_not_found_via_find_notifies() -> None:
    """``find_configured_chop`` raising ChopNotFoundError surfaces an error."""
    app = _FakeChopApp()
    with (
        patch(
            "sase.ace.tui.actions.axe_chop_run.load_axe_config",
            return_value=_config_with_chop(),
        ),
        patch(
            "sase.ace.tui.actions.axe_chop_run.find_configured_chop",
            side_effect=ChopNotFoundError("ghost"),
        ),
        patch("sase.ace.tui.actions.axe_chop_run.run_configured_chop_once") as run_mock,
    ):
        _run_async(app._launch_chop_run_async("hooks", "ghost"))
    run_mock.assert_not_called()
    assert any(sev == "error" for _, sev in app.notifications)


def test_launch_chop_run_async_passes_chop_timeout_default() -> None:
    """The lumberjack's ``chop_timeout`` is forwarded to the backend."""
    app = _FakeChopApp()
    config = _config_with_chop(timeout=42)
    outcome = ChopRunOutcome(
        lumberjack_name="hooks",
        chop_name="fast",
        status="success",
        run_id="r1",
        exit_code=0,
    )

    with (
        patch("sase.ace.tui.actions.axe_chop_run.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_chop_run.run_configured_chop_once",
            return_value=outcome,
        ) as run_mock,
    ):
        _run_async(app._launch_chop_run_async("hooks", "fast"))

    assert run_mock.call_args.kwargs["chop_timeout_default"] == 42


# --- Footer bindings ---


def test_compute_axe_bindings_chop_selected_idle_shows_run_chop() -> None:
    """An idle chop selection adds ``r run chop`` to the footer."""
    footer = KeybindingFooter()
    bindings = footer._compute_axe_bindings(
        "axe", chop_selected=True, chop_selected_running=False
    )
    assert ("r", "run chop") in bindings


def test_compute_axe_bindings_chop_selected_running_shows_running() -> None:
    """A chop with a running newest run shows ``r running`` instead."""
    footer = KeybindingFooter()
    bindings = footer._compute_axe_bindings(
        "axe", chop_selected=True, chop_selected_running=True
    )
    assert ("r", "running") in bindings
    assert ("r", "run chop") not in bindings


def test_compute_axe_bindings_no_chop_no_r_binding() -> None:
    """Without a chop or done bgcmd selection, ``r`` is absent from the footer."""
    footer = KeybindingFooter()
    bindings = footer._compute_axe_bindings("axe")
    assert not any(k == "r" for k, _ in bindings)


def test_compute_axe_bindings_tracks_description_state() -> None:
    footer = KeybindingFooter()

    expanded = footer._compute_axe_bindings(
        "axe",
        config_row_selected=True,
        description_expanded=True,
    )
    collapsed = footer._compute_axe_bindings(
        "axe",
        config_row_selected=True,
        description_expanded=False,
    )

    assert ("d", "collapse desc") in expanded
    assert ("d", "expand desc") in collapsed


def test_compute_axe_bindings_done_bgcmd_wins_over_chop_label() -> None:
    """A done bgcmd selection keeps the ``re-run`` label even with chop flag set."""
    footer = KeybindingFooter()
    bindings = footer._compute_axe_bindings(
        1, selected_slot_done=True, chop_selected=True
    )
    assert ("r", "re-run") in bindings
    # Only one r-binding is surfaced; chop flags don't double up.
    r_count = sum(1 for k, _ in bindings if k == "r")
    assert r_count == 1
