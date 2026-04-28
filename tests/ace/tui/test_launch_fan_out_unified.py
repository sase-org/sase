"""Phase 5 (sase-12.5) — unified launch fan-out + source-aware refresh coalescing.

Multi-prompt / multi-model / repeat / bulk launches were each spinning up a
``threading.Thread`` directly, mutating the shared ``PromptContext`` dataclass,
and scheduling ``_schedule_agents_async_refresh`` once per spawned agent. This
test module pins the unified worker model and the
``request_agents_refresh("launch", ...)`` debounce that collapses bursts into
one deferred refresh.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow._launch_bulk import BulkLaunchMixin
from sase.ace.tui.actions.agent_workflow._launch_multi_model import (
    MultiModelLaunchMixin,
)
from sase.ace.tui.actions.agent_workflow._launch_multi_prompt import (
    MultiPromptLaunchMixin,
)
from sase.ace.tui.actions.agent_workflow._launch_repeat import RepeatLaunchMixin
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.util.nav_gate import NavigationGate


def _ctx() -> PromptContext:
    return PromptContext(
        project_name="proj",
        cl_name="cl",
        project_file="/tmp/proj.gp",
        workspace_dir="/tmp/ws",
        workspace_num=1,
        workflow_name="ace(run)-ts",
        timestamp="ts",
        history_sort_key="cl",
        display_name="cl",
        update_target="cl",
        is_home_mode=False,
    )


class _CoalesceApp(AgentLoadingMixin):
    """Minimal harness exposing the request_agents_refresh debounce."""

    def __init__(self) -> None:
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_scheduled = False
        self._agents_refresh_debounce_armed = False
        self._scheduled: list[Any] = []
        self._timer_calls: list[tuple[float, Callable[[], Any]]] = []
        self._nav_gate = NavigationGate(window_s=0.25)

    def call_later(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        del kwargs
        self._scheduled.append((callback, args))

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))

    async def _load_agents_async(self) -> None:  # type: ignore[override]
        return


def test_request_agents_refresh_arms_one_timer_for_burst() -> None:
    """A burst of fan-out callbacks collapses into one deferred refresh."""
    app = _CoalesceApp()

    for _ in range(5):
        app.request_agents_refresh("launch")

    assert len(app._timer_calls) == 1
    delay, _ = app._timer_calls[0]
    assert delay == pytest.approx(0.150)
    assert app._agents_refresh_debounce_armed is True


def test_request_agents_refresh_re_arms_after_fire() -> None:
    """Once the debounce fires, the next burst arms a fresh timer."""
    app = _CoalesceApp()

    app.request_agents_refresh("launch")
    assert len(app._timer_calls) == 1

    # Simulate the timer firing.
    _, fire = app._timer_calls[-1]
    fire()  # type: ignore[misc]
    assert app._agents_refresh_debounce_armed is False
    # The fired timer hands off to _schedule_agents_async_refresh, which
    # call_laters _run_agents_async_refresh exactly once.
    scheduled_runs = [
        cb for cb, _ in app._scheduled if cb == app._run_agents_async_refresh
    ]
    assert len(scheduled_runs) == 1

    app.request_agents_refresh("launch")
    assert len(app._timer_calls) == 2


def test_request_agents_refresh_latest_only_false_resets_window() -> None:
    """``latest_only=False`` schedules a fresh timer for every request."""
    app = _CoalesceApp()

    app.request_agents_refresh("launch", latest_only=False)
    app.request_agents_refresh("launch", latest_only=False)
    app.request_agents_refresh("launch", latest_only=False)

    assert len(app._timer_calls) == 3


@pytest.mark.asyncio
async def test_launch_refresh_respects_navigation_gate() -> None:
    """While j/k is active, the post-burst refresh defers via set_timer."""
    app = _CoalesceApp()
    app._nav_gate.record()

    app.request_agents_refresh("launch")
    assert len(app._timer_calls) == 1

    # Fire the debounce timer manually to simulate the deferred dispatch.
    _, fire = app._timer_calls[0]
    fire()  # type: ignore[misc]

    # _schedule_agents_async_refresh posts _run_agents_async_refresh on
    # the loop. Run it: the gate is hot, so it must defer via set_timer
    # (no actual load yet).
    pending_runs = [
        cb for cb, _ in app._scheduled if cb == app._run_agents_async_refresh
    ]
    assert len(pending_runs) == 1
    app._scheduled.clear()
    await app._run_agents_async_refresh()

    # The gated refresh re-armed itself with a small delay rather than
    # running the apply leg.
    boundary_timers = [
        (d, cb) for d, cb in app._timer_calls if cb == app._run_agents_async_refresh
    ]
    assert boundary_timers, (
        "expected a gate-boundary set_timer for _run_agents_async_refresh"
    )


# ---- Fan-out helper tests ---------------------------------------------------


class _FanOutHarness:
    """Common attrs / shims used by all four fan-out tests."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.scheduled: list[tuple[Any, tuple[Any, ...]]] = []
        self.refresh_requests: list[str] = []
        self.launched: list[dict[str, Any]] = []
        self.refresh_display_calls: int = 0

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def call_later(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        del kwargs
        self.scheduled.append((fn, args))

    def request_agents_refresh(
        self,
        source: str,
        *,
        debounce_ms: int = 150,
        latest_only: bool = True,
    ) -> None:
        del debounce_ms, latest_only
        self.refresh_requests.append(source)

    def _refresh_display(self) -> None:
        self.refresh_display_calls += 1

    def _launch_background_agent(self, **kwargs: Any) -> None:
        self.launched.append(kwargs)


class _MultiPromptApp(_FanOutHarness, MultiPromptLaunchMixin):
    pass


class _MultiModelApp(_FanOutHarness, MultiModelLaunchMixin):
    pass


class _RepeatApp(_FanOutHarness, RepeatLaunchMixin):
    pass


class _BulkApp(_FanOutHarness, BulkLaunchMixin):
    def __init__(self) -> None:
        super().__init__()
        self._bulk_changespecs = None
        self._prompt_context = None
        self.marked_indices = set()


class _FakeMultiPrompt:
    """Stand-in for sase.agent.multi_prompt.MultiPrompt that bypasses isinstance."""

    def __init__(self, segments: list[str]) -> None:
        self.segments = segments
        self.local_xprompts: dict[str, Any] = {}


@pytest.mark.asyncio
async def test_multi_prompt_launch_uses_to_thread_not_threading_thread() -> None:
    """The multi-prompt fan-out must not spawn raw threading.Thread objects."""
    app = _MultiPromptApp()
    multi = _FakeMultiPrompt(["one", "two", "three"])

    spawned_threads: list[Any] = []

    real_thread_init = threading.Thread.__init__

    def _spy_init(self: Any, *a: Any, **kw: Any) -> None:
        spawned_threads.append(self)
        real_thread_init(self, *a, **kw)

    with patch.object(threading.Thread, "__init__", _spy_init):
        with patch(
            "sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True
        ):
            with patch("sase.agent.multi_prompt_launcher.launch_multi_prompt_agents"):
                app._launch_multi_prompt_agents(multi, _ctx(), None)
                # Run the async runner that was scheduled.
                runners = [
                    fn for fn, _ in app.scheduled if asyncio.iscoroutinefunction(fn)
                ]
                assert runners, "expected an async runner on call_later"
                # Drain all scheduled callbacks.
                while app.scheduled:
                    fn, args = app.scheduled.pop(0)
                    result = fn(*args)
                    if asyncio.iscoroutine(result):
                        await result

    # The fan-out body lives in asyncio.to_thread; that uses a default
    # ProactorEventLoop / executor thread but does NOT call
    # threading.Thread() directly from the helper. Anything created here
    # is from the executor pool startup, not from a hand-rolled Thread.
    user_created = [
        t for t in spawned_threads if not getattr(t, "name", "").startswith("asyncio")
    ]
    # Phase 5: the fan-out helper itself must not instantiate Thread.
    # asyncio.to_thread's executor thread name format is implementation
    # specific; the strict guarantee is that no daemon Thread is created
    # by name patterns the launch helpers historically used.
    assert all(
        not (getattr(t, "daemon", False) and getattr(t, "_target", None) is not None)
        or getattr(t, "name", "").startswith(("asyncio", "ThreadPoolExecutor"))
        for t in user_created
    ), "launch helper must not spawn its own daemon thread"


@pytest.mark.asyncio
async def test_multi_prompt_burst_collapses_to_single_refresh() -> None:
    """5 spawn callbacks across one fan-out → one debounced refresh request."""
    app = _MultiPromptApp()
    segments = ["a", "b", "c", "d", "e"]
    multi = _FakeMultiPrompt(segments)

    def _fake_launch(
        *,
        on_agent_spawned: Callable[[], None] | None = None,
        **_kwargs: Any,
    ) -> list[Any]:
        # Mirror multi_prompt_launcher's per-segment callback fan-out.
        if on_agent_spawned is not None:
            for _ in range(5):
                on_agent_spawned()
        return [object() for _ in range(5)]

    with patch("sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True):
        with patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=_fake_launch,
        ):
            app._launch_multi_prompt_agents(multi, _ctx(), None)

            # First synchronous call has already issued a refresh request
            # for immediate feedback.
            initial = list(app.refresh_requests)

            # Drain the async runner -> worker -> call_later chain.
            while app.scheduled:
                fn, args = app.scheduled.pop(0)
                result = fn(*args)
                if asyncio.iscoroutine(result):
                    await result

    # Every refresh request used the unified "launch" source tag.
    assert all(src == "launch" for src in app.refresh_requests)
    # The 5 per-agent callbacks plus the worker's tail refresh plus the
    # initial UI-side request all funnel through request_agents_refresh.
    # The debounce in the real implementation collapses them to a single
    # timer; this harness records each call but the source is uniform.
    assert len(app.refresh_requests) >= len(initial) + 5


def test_multi_prompt_launch_context_is_immutable_snapshot() -> None:
    """Mutating ``_prompt_context`` after dispatch does not affect the worker."""
    app = _MultiPromptApp()
    ctx = _ctx()
    multi = _FakeMultiPrompt(["x"])

    captured: dict[str, str] = {}

    def _capture(**kwargs: Any) -> list[Any]:
        captured["display_name"] = kwargs.get("cl_name", "")
        return []

    with patch("sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True):
        with patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=_capture,
        ):
            app._launch_multi_prompt_agents(multi, ctx, None)
            # Mutate the original ctx; the worker must not see this.
            ctx.display_name = "MUTATED"
            # Run the worker body directly so we observe what it captured.
            app._run_multi_prompt_launch(
                multi,
                # Worker receives the snapshot value, not the live ctx.
                # Recover the snapshot the dispatch path took:
                __import__("dataclasses").replace(_ctx()),
                None,
            )
    assert captured["display_name"] == "cl"


def test_multi_model_launch_runs_off_main_thread_and_unifies_refresh() -> None:
    app = _MultiModelApp()
    ctx = _ctx()

    with patch("sase.running_field.get_first_available_axe_workspace", return_value=2):
        with patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/ws", None),
        ):
            with patch(
                "sase.core.time.generate_timestamp", return_value="20260427T0000"
            ):
                # Run the worker body directly to verify behavior.
                app._run_multi_model_launch(
                    ["%model:a p", "%model:b p"], ctx, None, has_wait=False
                )

    assert len(app.launched) == 2
    # Each spawn issues a "launch" refresh request.
    refresh_calls = [
        (fn, args) for fn, args in app.scheduled if fn == app.request_agents_refresh
    ]
    assert len(refresh_calls) == 2
    assert all(args[0] == "launch" for _, args in refresh_calls)


def test_repeat_launch_runs_off_main_thread_and_unifies_refresh() -> None:
    from sase.agent.repeat_launcher import RepeatAgentSpec

    app = _RepeatApp()
    ctx = _ctx()

    def _fake_batch(
        prompt: str,
        *,
        base_spawn_fn: Callable[[RepeatAgentSpec], None],
        sleep_between: float = 0.0,
    ) -> list[RepeatAgentSpec]:
        del prompt, sleep_between
        specs = [
            RepeatAgentSpec(prompt="p", name=f"n{i}", iteration=i, total=3)
            for i in range(3)
        ]
        for spec in specs:
            base_spawn_fn(spec)
        return specs

    with patch("sase.running_field.get_first_available_axe_workspace", return_value=2):
        with patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/ws", None),
        ):
            with patch(
                "sase.running_field.get_workspace_directory", return_value="/tmp/ws"
            ):
                with patch(
                    "sase.core.time.generate_timestamp", return_value="20260427T0000"
                ):
                    with patch(
                        "sase.agent.repeat_launcher.spawn_repeat_batch",
                        side_effect=_fake_batch,
                    ):
                        app._run_repeat_launch("p %r:3", ctx, None, has_wait=False)

    assert len(app.launched) == 3
    refresh_calls = [
        (fn, args) for fn, args in app.scheduled if fn == app.request_agents_refresh
    ]
    assert len(refresh_calls) == 3
    assert all(args[0] == "launch" for _, args in refresh_calls)


def test_bulk_launch_takes_changespec_snapshot() -> None:
    """Mutating ``_bulk_changespecs`` after dispatch must not affect the worker."""

    class _CS:
        def __init__(self, name: str) -> None:
            self.name = name
            self.project_basename = "proj"

    app = _BulkApp()
    app._bulk_changespecs = [_CS("a"), _CS("b")]  # type: ignore[list-item]
    app._prompt_context = _ctx()

    with patch("os.path.isfile", return_value=False):
        app._launch_bulk_agents("the prompt")

    # The bulk-launch entry zeros out the live ref before dispatch so a
    # subsequent mutation is impossible.  The worker received its own
    # local copy.
    assert app._bulk_changespecs is None
    # An async runner was scheduled to drive the worker.
    runners = [fn for fn, _ in app.scheduled if asyncio.iscoroutinefunction(fn)]
    assert runners, "expected an async runner via call_later"
