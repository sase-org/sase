"""Post-launch j/k lag regression tests.

Phase 3 of plans/202604/post_launch_jk_lag.md. Without these guards, any
new code path that re-introduces a UI-thread refresh during a j/k burst
will silently regress the "navigation feels instant after launch"
property that the plan exists to defend.

The tests cover three properties:

1. ``_run_agents_async_refresh`` defers via ``set_timer`` when the
   navigation gate reports an active j/k burst, instead of running the
   apply/render pipeline on the UI thread mid-burst.
2. The gate-deferred refresh re-arms itself via ``set_timer`` rather
   than scheduling duplicate ``call_later`` invocations, so additional
   refresh triggers during the burst collapse into the existing
   ``_agents_refresh_pending`` flag.
3. ``_apply_loaded_agents`` batches the auto-dismiss disk writes into a
   single ``save_dismissed_agents`` flush — the post-launch refresh's
   biggest source of UI-thread disk I/O — so a many-agent reload no
   longer fans out into N synchronous writes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.nav_gate import NavigationGate


class _FakeRefreshApp(AgentLoadingMixin):
    """Minimal harness for the gate / scheduler tests."""

    def __init__(self) -> None:
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_scheduled = False
        self._scheduled: list[Any] = []
        self._timer_calls: list[tuple[float, Callable[[], Any]]] = []
        self._nav_gate = NavigationGate(window_s=0.25)
        self.load_calls: int = 0

    def call_later(self, callback: Any) -> None:
        self._scheduled.append(callback)

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))

    async def _load_agents_async(self) -> None:  # type: ignore[override]
        self.load_calls += 1


@pytest.mark.asyncio
async def test_run_refresh_defers_when_user_is_navigating() -> None:
    """While a j/k burst is active, the apply leg must not run inline.

    Pressing j/k right after a launch arms the gate; this test pins the
    behavior that the launch-driven refresh sees the gate, schedules a
    deferred re-arm, and exits without touching the UI-thread apply
    pipeline.
    """
    app = _FakeRefreshApp()
    app._nav_gate.record()

    await app._run_agents_async_refresh()

    # No apply ran — the disk/apply pipeline was deferred.
    assert app.load_calls == 0
    # A re-arm timer was scheduled at the gate boundary plus 50 ms.
    assert len(app._timer_calls) == 1
    delay, callback = app._timer_calls[0]
    assert 0.05 < delay <= 0.30
    assert callback == app._run_agents_async_refresh


@pytest.mark.asyncio
async def test_deferred_refresh_does_not_clear_scheduled_flag() -> None:
    """A gate-deferred run must keep ``_agents_refresh_scheduled`` set.

    Otherwise concurrent triggers (each launch refresh, each inotify
    fire, each kill / dismiss) would each post their own
    ``call_later(_run_agents_async_refresh)`` and the user's first j/k
    pause would fire several apply passes back-to-back instead of one.
    """
    app = _FakeRefreshApp()
    # Simulate the scheduling path having posted the run on the loop.
    app._agents_refresh_scheduled = True
    app._nav_gate.record()

    await app._run_agents_async_refresh()

    # The scheduled flag survives the deferral so subsequent
    # _schedule_agents_async_refresh calls collapse into the pending flag.
    assert app._agents_refresh_scheduled is True
    # And further launch/kill/etc. triggers fold into _refresh_pending,
    # not into a second call_later.
    app._schedule_agents_async_refresh()
    app._schedule_agents_async_refresh()
    assert app._scheduled == []
    assert app._agents_refresh_pending is True


@pytest.mark.asyncio
async def test_run_refresh_runs_inline_when_user_is_idle() -> None:
    """With no active burst, the refresh runs the apply leg directly."""
    app = _FakeRefreshApp()

    await app._run_agents_async_refresh()

    assert app.load_calls == 1
    assert app._timer_calls == []
    assert app._agents_loading is False
    assert app._agents_refresh_scheduled is False


class _FakeApplyApp(AgentLoadingMixin):
    """Minimal harness exposing just the attrs ``_apply_loaded_agents`` reads.

    ``_finalize_agent_list`` is stubbed because the real implementation
    needs widgets that aren't mounted in this fake; the test only needs
    to observe the dismissed-set / save-call surface that the apply step
    drives before delegating to finalize.
    """

    def __init__(self) -> None:
        self.current_tab = "changespecs"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_last_idx = 0
        self._has_always_visible = False
        self._hidden_count = 0
        self._hideable_agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._agents_loading = False
        self._agents_first_load_done = True
        self.finalize_calls: int = 0

    def _finalize_agent_list(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.finalize_calls += 1


def _make_hidden_done(suffix: str, cl: str = "x") -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=cl,
        project_file="",
        status="DONE",
        start_time=datetime(2026, 4, 27, 12, 0, 0),
        raw_suffix=suffix,
        hidden=True,
    )


def test_apply_batches_auto_dismiss_into_one_disk_write() -> None:
    """N hidden+DONE agents → exactly 1 save_dismissed_agents call.

    Pre-Phase-2 each auto-dismissed agent triggered one synchronous
    ``save_dismissed_agents`` disk write on the UI thread, so a refresh
    that auto-dismissed K agents performed K JSON writes during the
    user's first post-launch j/k burst.  After Phase 2 the prep step
    accumulates the identities into a single delta and the apply step
    flushes the merged set once.
    """
    app = _FakeApplyApp()
    agents = [
        _make_hidden_done(f"2026-04-27T1{i}0000.000", cl=f"a{i}") for i in range(5)
    ]

    with patch(
        "sase.ace.dismissed_agents.save_dismissed_agents", return_value=True
    ) as mock_save:
        app._apply_loaded_agents(
            list(agents),
            dismissed_from_loader=[],
            on_agents_tab=False,
            selected_identity=None,
        )

    # Exactly one flush — not five — for the batched auto-dismiss delta.
    assert mock_save.call_count == 1
    # All five identities ended up in the dismissed set.
    assert len(app._dismissed_agents) == 5
    # The finalize step ran (apply step delegated to it as expected).
    assert app.finalize_calls == 1


def test_apply_skips_save_when_no_dismissed_changes() -> None:
    """If nothing changed in the dismissed set, no disk write happens.

    Most refreshes don't auto-dismiss anything (no newly-hidden+DONE
    agents) and don't recover bundles — they shouldn't touch disk.
    """
    app = _FakeApplyApp()
    a_running = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha",
        project_file="",
        status="RUNNING",
        start_time=datetime(2026, 4, 27, 12, 0, 0),
        raw_suffix="2026-04-27T120000.000",
    )

    with patch(
        "sase.ace.dismissed_agents.save_dismissed_agents", return_value=True
    ) as mock_save:
        app._apply_loaded_agents(
            [a_running],
            dismissed_from_loader=[],
            on_agents_tab=False,
            selected_identity=None,
        )

    assert mock_save.call_count == 0
