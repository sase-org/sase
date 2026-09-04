"""Full-application test harness for the ace TUI."""

import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any, Literal
from unittest.mock import patch

from sase.ace.patch import Patch
from sase.ace.tui import AceApp
from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks
from textual.worker import WorkerCancelled

from ._startup import _install_fast_startup_overrides
from ._stylesheet_cache import (
    FastStylesheetSeed,
    finish_fast_stylesheet_boot,
    seed_fast_stylesheet,
)
from . import settle as settle_helpers
from .fixtures import DEFAULT_PATCHES
from .wait import _poll_until

AceStartupPolicy = Literal["fast", "real"]

_SENTINEL = object()

_LEGACY_SELECTOR_ALIASES = {
    "#changespecs-view": "#artifacts-view",
    "#changespec-quickstart-panel": "#patch-quickstart-panel",  # legacy compat alias
    "#patch-quickstart-panel": "#patch-quickstart-panel",
}

_LEGACY_STATE_VALUE_ALIASES = {
    ("tab", "changespecs"): "artifacts",
    ("tab", "patches"): "artifacts",
}


def _capture_screen(app: AceApp, height: int) -> str:
    """Capture the current screen content as plain text."""
    lines = [app.screen.render_line(y).text for y in range(height)]
    return "\n".join(lines)


def _get_modal_name(app: AceApp) -> str | None:
    """Return the class name of the top modal, or None if no modal is open."""
    if len(app.screen_stack) > 1:
        return type(app.screen_stack[-1]).__name__
    return None


def _extract_state(app: AceApp) -> dict[str, Any]:
    """Extract structured state from the app's reactive properties."""
    state: dict[str, Any] = {
        "tab": app.current_tab,
        "artifacts_subtab": app.current_artifacts_subtab,
        "files_subtab": app.current_files_subtab,
        "idx": app.current_idx,
        "total": len(app.patches),
        "query": app.query_string,
        "canonical_query": app.canonical_query_string,
        "marked": sorted(app.marked_indices),
        "modal": _get_modal_name(app),
        "hide_reverted": app.hide_reverted,
        "hooks_collapsed": app.hooks_collapsed.value,
        "commits_collapsed": app.commits_collapsed.value,
        "mentors_collapsed": app.mentors_collapsed.value,
        "deltas_collapsed": app.deltas_collapsed.value,
    }

    # Selected patch info
    if app.patches and 0 <= app.current_idx < len(app.patches):
        cs = app.patches[app.current_idx]
        state["selected"] = {
            "name": cs.name,
            "status": cs.status,
            "cl": cs.pr_url,
            "parent": cs.parent,
            "project": cs.project_basename,
            "description": cs.description[:200] if cs.description else None,
            "commit_count": len(cs.commits) if cs.commits else 0,
            "hook_count": len(cs.hooks) if cs.hooks else 0,
            "has_comments": bool(cs.comments),
            "has_mentors": bool(cs.mentors),
        }
    else:
        state["selected"] = None

    # Tab-specific state
    if app.current_tab == "agents":
        state["agent_count"] = len(app._agents)
        if app._agents and 0 <= app._agents_last_idx < len(app._agents):
            agent = app._agents[app._agents_last_idx]
            state["selected_agent"] = {
                "type": agent.display_type,
                "cl_name": agent.cl_name,
                "status": agent.status,
            }
        else:
            state["selected_agent"] = None
    elif app.current_tab == "axe":
        state["axe_running"] = app.axe_running

    return state


def _stop_ace_app_proc_observer(app: AceApp | None) -> None:
    """Retire a constructed app's proc observer even when unmount never ran."""
    if app is None:
        return
    stop = getattr(app, "_stop_proc_observer", None)
    if not callable(stop):
        return
    try:
        stop()
    except Exception:
        pass


async def _drain_pump_free_tasks(app: AceApp) -> None:
    """Cancel leftover pump-free work and wait until it leaves the registry.

    ``on_unmount`` only requests cancellation. A task blocked in
    ``asyncio.to_thread`` stays in ``_pump_free_async_tasks`` until the
    thread returns and the done callback discards it; AcePage must await
    that before the test loop is torn down.
    """
    cancel_pump_free_tasks(app)
    tasks: set[asyncio.Task[Any]] = set()
    for registry_name in tuple(getattr(app, "_pump_free_task_registry_attrs", ())):
        tasks.update(getattr(app, registry_name, ()))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _drain_textual_workers(app: AceApp) -> None:
    """Cancel live Textual workers and surface real worker failures."""
    workers = tuple(app.workers)
    if not workers:
        return
    app.workers.cancel_all()
    worker_results = await asyncio.gather(
        *(worker.wait() for worker in workers),
        return_exceptions=True,
    )
    for result in worker_results:
        if isinstance(result, WorkerCancelled):
            continue
        if isinstance(result, Exception):
            raise result


async def _drain_app_work(app: AceApp) -> None:
    """Drain every ACE-owned asynchronous work queue before app teardown returns."""
    worker_error: Exception | None = None
    try:
        await _drain_textual_workers(app)
    except Exception as error:
        worker_error = error
    await _drain_pump_free_tasks(app)
    if worker_error is not None:
        raise worker_error


def _resolve_key(data: dict[str, Any], key: str) -> Any:
    """Resolve a dot-notation key like 'selected.name' into nested dicts."""
    parts = key.split(".")
    current: Any = data
    for part in parts:
        if not isinstance(current, dict):
            return _SENTINEL
        current = current.get(part, _SENTINEL)
        if current is _SENTINEL:
            return _SENTINEL
    return current


class AcePage:
    """Async context manager wrapping AceApp + Pilot for fluent TUI testing."""

    def __init__(
        self,
        query: str = '"feature"',
        size: tuple[int, int] = (120, 40),
        patches: list[Patch] | None = None,
        changespecs: list[Patch] | None = None,  # legacy compatibility alias
        model_tier_override: Literal["large", "small"] | None = None,
        initial_tab: Literal[
            "artifacts",
            "patches",
            "changespecs",  # legacy compatibility tab id
            "agents",
            "axe",
        ] = "artifacts",
        notifications: bool = False,
        wait_for_startup_state: bool = True,
        startup_policy: AceStartupPolicy = "fast",
    ) -> None:
        if startup_policy not in {"fast", "real"}:
            raise ValueError(f"unsupported AcePage startup policy: {startup_policy!r}")
        self._query = query
        self._size = size
        if patches is not None:
            self._patches = patches
        elif changespecs is not None:
            self._patches = changespecs  # legacy compatibility alias
        else:
            self._patches = DEFAULT_PATCHES
        self._model_tier_override: Literal["large", "small"] | None = (
            model_tier_override
        )
        self._initial_tab = initial_tab
        self._notifications = notifications
        self._wait_for_startup_state = wait_for_startup_state
        self._startup_policy = startup_policy
        self._app: AceApp | None = None
        self._pilot: Any = None
        self._stack: AsyncExitStack | None = None
        self._stylesheet_seed: FastStylesheetSeed | None = None

    async def __aenter__(self) -> "AcePage":
        stack = AsyncExitStack()
        await stack.__aenter__()
        self._stack = stack
        try:
            stack.enter_context(
                patch(
                    "sase.ace.patch.find_all_patches",
                    return_value=self._patches,
                )
            )
            stack.enter_context(
                patch(
                    "sase.ace.patch.find_all_patches_cached",
                    return_value=self._patches,
                )
            )
            stack.enter_context(
                patch(
                    "sase.ace.patch.find_all_patches_cached",
                    return_value=self._patches,
                )
            )
            if self._startup_policy == "fast":
                _install_fast_startup_overrides(stack)

            self._app = AceApp(
                query=self._query,
                model_tier_override=self._model_tier_override,
                refresh_interval=0,
                initial_tab=self._initial_tab,
            )
            if self._startup_policy == "fast":
                self._app.animation_level = "none"
                self._stylesheet_seed = seed_fast_stylesheet(self._app)
            self._pilot = await stack.enter_async_context(
                self._app.run_test(
                    size=self._size,
                    notifications=self._notifications,
                )
            )
            if self._wait_for_startup_state:
                deadline = asyncio.get_running_loop().time() + 15.0
                paused = False
                while not self._app._mount_state_loads_done:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError(
                            "AcePage startup state did not load within 15 seconds"
                        )
                    await settle_helpers.settle_pilot(self._pilot)
                    paused = True
                # Fast fixtures can complete before Textual's run-test enter
                # returns. Give their queued display/focus continuations one
                # turn, matching the settling turn the real loader wait gets.
                if not paused:
                    await settle_helpers.settle_pilot(self._pilot)
            if self._startup_policy == "fast":
                finish_fast_stylesheet_boot(self._app, self._stylesheet_seed)
            return self
        except BaseException:
            app = self._app
            if app is not None:
                await _drain_app_work(app)
            await stack.aclose()
            if app is not None:
                await _drain_app_work(app)
            self._stack = None
            _stop_ace_app_proc_observer(app)
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        stack = self._stack
        self._stack = None
        app = self._app
        try:
            if app is not None:
                await _drain_app_work(app)
            if stack is not None:
                await stack.__aexit__(exc_type, exc_val, exc_tb)
            if app is not None:
                await _drain_app_work(app)
        finally:
            _stop_ace_app_proc_observer(app)

    async def press(self, *keys: str) -> None:
        """Press one or more keys via the pilot."""
        await self._pilot.press(*keys)

    async def pause(self, delay: float | None = None) -> None:
        """Let Textual settle, or sleep for an explicitly requested delay.

        Bare pauses use ACE's event-driven settle barrier. Numeric pauses are
        retained as real delays for tests that intentionally exercise time.
        """
        if delay is None:
            await settle_helpers.settle_pilot(self._pilot)
        else:
            await self._pilot.pause(delay)

    async def pause_until_cpu_idle(self) -> None:
        """Use Textual's original CPU-idle pause heuristic explicitly."""

        await settle_helpers.pause_until_cpu_idle(self._pilot)

    async def click(
        self,
        selector: str,
        *,
        offset: tuple[int, int] | None = None,
    ) -> None:
        """Click a widget by CSS selector."""
        if offset is None:
            await self._pilot.click(selector)
        else:
            await self._pilot.click(selector, offset=offset)

    @property
    def state(self) -> dict[str, Any]:
        """Extract structured state from the app."""
        assert self._app is not None
        return _extract_state(self._app)

    @property
    def screen(self) -> str:
        """Capture the current screen as plain text."""
        assert self._app is not None
        return _capture_screen(self._app, self._size[1])

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        """Export the current Textual screen as an SVG screenshot."""
        assert self._app is not None
        return self._app.export_screenshot(title=title, simplify=simplify)

    @property
    def app(self) -> AceApp:
        """Access the underlying AceApp directly."""
        assert self._app is not None
        return self._app

    def query_widget(self, selector: str) -> Any:
        """Query widgets matching a CSS selector."""
        assert self._app is not None
        selector = _LEGACY_SELECTOR_ALIASES.get(selector, selector)
        return self._app.query(selector)

    def query_one_widget(self, selector: str, widget_type: type | None = None) -> Any:
        """Query a single widget by CSS selector."""
        assert self._app is not None
        selector = _LEGACY_SELECTOR_ALIASES.get(selector, selector)
        if widget_type is not None:
            from sase.ace.tui.widgets.patch_detail import PatchDetail

            if widget_type is PatchDetail:
                widget_type = PatchDetail
            return self._app.query_one(selector, widget_type)
        return self._app.query_one(selector)

    def artifacts_digit(self, subtab: str) -> str:
        """Return the live digit shortcut for an Artifacts sub-tab id.

        Artifacts digits follow visual position (see
        ``_artifact_tab_descriptors.assign_artifacts_digit_shortcuts``), so tests must
        not hard-code them. The import is function-local because AcePage's
        fast startup overrides patch ``resolve_artifacts_subtabs`` on the
        ``artifact_tabs`` module; a module-level import would bind the
        unpatched function instead.
        """
        from sase.ace.tui.artifact_tabs import resolve_artifacts_subtabs

        descriptor = next(d for d in resolve_artifacts_subtabs() if d.id == subtab)
        assert descriptor.digit_shortcut is not None
        return descriptor.digit_shortcut

    async def expect_state(
        self,
        key: str,
        value: Any,
        *,
        timeout: float = 5.0,
    ) -> None:
        """Poll state until state[key] == value, or raise AssertionError.

        Supports dot-notation for nested keys (e.g., "selected.name").
        """
        value = _LEGACY_STATE_VALUE_ALIASES.get((key, value), value)
        last_actual: Any = _SENTINEL
        app = self.app

        def predicate() -> bool:
            nonlocal last_actual
            state = self.state
            actual = _resolve_key(state, key)
            last_actual = actual
            return actual == value

        def timeout_message() -> str:
            return (
                f"expect_state({key!r}, {value!r}) timed out after"
                f" {timeout}s — last value was {last_actual!r}"
            )

        await _poll_until(
            predicate,
            is_success=bool,
            settle=lambda: settle_helpers.settle_pilot(self._pilot),
            timeout=timeout,
            timeout_message=timeout_message,
            clock=app._loop.time if app._loop is not None else None,
        )

    async def expect_modal(self, name: str, *, timeout: float = 5.0) -> None:
        """Assert that the named modal is currently shown."""
        await self.expect_state("modal", name, timeout=timeout)

    async def expect_no_modal(self, *, timeout: float = 5.0) -> None:
        """Assert that no modal is currently shown."""
        await self.expect_state("modal", None, timeout=timeout)

    async def expect_screen_contains(self, text: str, *, timeout: float = 5.0) -> None:
        """Poll screen until text is found, or raise AssertionError."""
        app = self.app

        await _poll_until(
            lambda: text in self.screen,
            is_success=bool,
            settle=lambda: settle_helpers.settle_pilot(self._pilot),
            timeout=timeout,
            timeout_message=lambda: (
                f"expect_screen_contains({text!r}) timed out after"
                f" {timeout}s — text not found in screen"
            ),
            clock=app._loop.time if app._loop is not None else None,
        )

    async def expect_screen_not_contains(
        self, text: str, *, timeout: float = 5.0
    ) -> None:
        """Poll screen until text is absent, or raise AssertionError."""
        app = self.app

        await _poll_until(
            lambda: text not in self.screen,
            is_success=bool,
            settle=lambda: settle_helpers.settle_pilot(self._pilot),
            timeout=timeout,
            timeout_message=lambda: (
                f"expect_screen_not_contains({text!r}) timed out after"
                f" {timeout}s — text still present in screen"
            ),
            clock=app._loop.time if app._loop is not None else None,
        )

    async def wait_for(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float = 5.0,
    ) -> None:
        """Poll state until predicate(state) returns True, or raise."""
        app = self.app

        await _poll_until(
            lambda: predicate(self.state),
            is_success=bool,
            settle=lambda: settle_helpers.settle_pilot(self._pilot),
            timeout=timeout,
            timeout_message=lambda: (
                f"wait_for() timed out after {timeout}s — predicate never returned True"
            ),
            clock=app._loop.time if app._loop is not None else None,
        )
