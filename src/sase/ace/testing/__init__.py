"""Playwright-inspired testing DSL for the ace TUI."""

import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any, Literal
from unittest.mock import patch

from textual.app import App, ComposeResult

import sase.notifications as _notifications
from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    DeltaEntry,
    HookEntry,
)
from sase.ace.tui import AceApp
from sase.ace.tui.actions.agents import _loading as _agent_loading
from sase.ace.tui.modals import plugins_browser_pane as _plugins_browser_pane
from sase.ace.tui.modals import project_inventory_panes as _project_inventory_panes
from sase.ace.tui.util import stall_watchdog as _stall_watchdog
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.repo_inventory import RepoInventory
from sase.workspace_provider.inventory import WorkspaceInventory


AceStartupPolicy = Literal["fast", "real"]

_ORIGINAL_RUN_MOUNT_STATE_LOADS = AceApp._run_mount_state_loads
_ORIGINAL_RUN_AGENT_STARTUP = AceApp._run_agent_index_startup_prepare_and_refresh
_ORIGINAL_RUN_AXE_STARTUP = AceApp._run_axe_startup_init
_ORIGINAL_LOAD_AXE_STATUS_ASYNC = AceApp._load_axe_status_async
_ORIGINAL_SCHEDULE_FOLD_STATE_LOAD = AceApp._schedule_agents_fold_state_load
_ORIGINAL_SCHEDULE_DISMISSED_INDEX_SYNC = AceApp._schedule_dismissed_index_startup_sync
_ORIGINAL_START_ARTIFACT_WATCHER = AceApp._start_artifact_watcher
_ORIGINAL_START_PROMPT_SOURCE_WATCHER = AceApp._start_prompt_source_watcher
_ORIGINAL_SCHEDULE_PROMPT_CATALOG_REBUILD = AceApp._schedule_prompt_catalog_rebuild
_ORIGINAL_SCHEDULE_UPDATE_CHECK = AceApp._schedule_startup_update_toast_check

_ORIGINAL_LOAD_AGENTS_FROM_DISK = _agent_loading.load_agents_from_disk_with_state
_ORIGINAL_READ_NOTIFICATION_SNAPSHOT = _notifications.read_notification_snapshot
_ORIGINAL_START_STALL_WATCHDOG = _stall_watchdog.start_event_loop_stall_watchdog
_ORIGINAL_LOAD_PLUGINS_CATALOG = _plugins_browser_pane._load_plugins_catalog
_ORIGINAL_COLLECT_REPO_INVENTORY = _project_inventory_panes.collect_repo_inventory
_ORIGINAL_COLLECT_WORKSPACE_INVENTORY = (
    _project_inventory_panes.collect_workspace_inventory
)


def _noop_startup_service(*_args: Any, **_kwargs: Any) -> None:
    """Stand in for a background service suppressed by fast pilot startup."""


async def _run_fast_mount_state_loads(app: AceApp) -> None:
    """Install deterministic mount state without reading the host filesystem."""
    try:
        notification_state: tuple[set[str], int, int, int] = (set(), 0, 0, 0)
        if (
            _notifications.read_notification_snapshot
            is not _ORIGINAL_READ_NOTIFICATION_SNAPSHOT
        ):
            # Caller-supplied fixtures (notably the visual harness) remain the
            # source of truth. They are still called off the event loop so a
            # deliberately blocked fixture retains production scheduling.
            notification_state = await asyncio.to_thread(
                app._read_notifications_for_startup
            )
        app._initialize_agent_tracking(notification_state)
        app._apply_prompt_stash_counts(0, 0)
        # AcePage owns both ChangeSpec loader patches, so this retains the real
        # filtering, selection, and widget-application path without a disk scan.
        app._apply_changespecs(app._read_changespecs_from_disk())
    finally:
        app._mount_state_loads_done = True


def _finish_fast_agent_startup(app: AceApp) -> None:
    """Complete the empty Agents startup surface without scheduling I/O."""
    from sase.ace.tui.widgets import AgentInfoPanel, AgentList

    # The real loader establishes both projections before flipping its first-
    # load flag. Keep the same invariant so later tab switches can run the
    # production in-memory refilter path against an intentionally empty list.
    app._agents_with_children = []
    app._agents_refresh_pending_callbacks.clear()
    app._agents_refresh_scheduled = False
    app._agents_first_load_done = True
    try:
        app.query_one("#agent-list-panel", AgentList).loading = False
    except Exception:
        pass
    try:
        app.query_one("#agent-info-panel", AgentInfoPanel).set_loading(False)
    except Exception:
        pass
    app._maybe_end_startup_stopwatch()


async def _run_fast_agent_startup(app: AceApp) -> None:
    _finish_fast_agent_startup(app)


async def _run_fast_axe_startup(app: AceApp) -> None:
    """Complete the empty AXE startup surface without reading daemon state."""
    from sase.ace.tui.widgets import AxeDashboard, AxeInfoPanel

    app._axe_first_load_done = True
    try:
        app.query_one("#axe-dashboard", AxeDashboard).loading = False
    except Exception:
        pass
    try:
        app.query_one("#axe-info-panel", AxeInfoPanel).set_loading(False)
    except Exception:
        pass
    app._maybe_end_startup_stopwatch()


def _schedule_prompt_catalog_without_startup_warm(
    app: AceApp,
    *,
    reason: str,
    force: bool = False,
    config_dirty: bool = False,
) -> None:
    """Skip automatic warming while retaining page-requested catalog loads."""
    if reason == "startup_warm":
        return
    _ORIGINAL_SCHEDULE_PROMPT_CATALOG_REBUILD(
        app,
        reason=reason,
        force=force,
        config_dirty=config_dirty,
    )


def _empty_plugins_catalog(**_kwargs: Any) -> Any:
    """Return an inert Updates-pane snapshot for unrelated mounted tabs."""
    return _plugins_browser_pane._PluginsLoadResult(
        catalog=None,
        error=None,
        now=0.0,
    )


def _empty_repo_inventory(*_args: Any, **_kwargs: Any) -> RepoInventory:
    return RepoInventory((), ())


def _empty_workspace_inventory(
    *_args: Any,
    **_kwargs: Any,
) -> WorkspaceInventory:
    return WorkspaceInventory((), ())


def _patch_method_if_unchanged(
    stack: AsyncExitStack,
    name: str,
    original: Any,
    replacement: Any,
) -> None:
    """Patch an AceApp method unless a caller already supplied a fixture."""
    if getattr(AceApp, name) is original:
        stack.enter_context(patch.object(AceApp, name, replacement))


def _install_fast_startup_overrides(stack: AsyncExitStack) -> None:
    """Install the scoped nonessential-service overrides used by AcePage."""
    _patch_method_if_unchanged(
        stack,
        "_run_mount_state_loads",
        _ORIGINAL_RUN_MOUNT_STATE_LOADS,
        _run_fast_mount_state_loads,
    )

    if (
        AceApp._run_agent_index_startup_prepare_and_refresh
        is _ORIGINAL_RUN_AGENT_STARTUP
        and _agent_loading.load_agents_from_disk_with_state
        is _ORIGINAL_LOAD_AGENTS_FROM_DISK
    ):
        stack.enter_context(
            patch.object(
                AceApp,
                "_run_agent_index_startup_prepare_and_refresh",
                _run_fast_agent_startup,
            )
        )

    if (
        AceApp._run_axe_startup_init is _ORIGINAL_RUN_AXE_STARTUP
        and AceApp._load_axe_status_async is _ORIGINAL_LOAD_AXE_STATUS_ASYNC
    ):
        stack.enter_context(
            patch.object(AceApp, "_run_axe_startup_init", _run_fast_axe_startup)
        )

    for name, original in (
        ("_schedule_agents_fold_state_load", _ORIGINAL_SCHEDULE_FOLD_STATE_LOAD),
        (
            "_schedule_dismissed_index_startup_sync",
            _ORIGINAL_SCHEDULE_DISMISSED_INDEX_SYNC,
        ),
        ("_start_artifact_watcher", _ORIGINAL_START_ARTIFACT_WATCHER),
        (
            "_start_prompt_source_watcher",
            _ORIGINAL_START_PROMPT_SOURCE_WATCHER,
        ),
        ("_schedule_startup_update_toast_check", _ORIGINAL_SCHEDULE_UPDATE_CHECK),
    ):
        _patch_method_if_unchanged(stack, name, original, _noop_startup_service)

    _patch_method_if_unchanged(
        stack,
        "_schedule_prompt_catalog_rebuild",
        _ORIGINAL_SCHEDULE_PROMPT_CATALOG_REBUILD,
        _schedule_prompt_catalog_without_startup_warm,
    )
    if (
        _stall_watchdog.start_event_loop_stall_watchdog
        is _ORIGINAL_START_STALL_WATCHDOG
    ):
        stack.enter_context(
            patch.object(
                _stall_watchdog,
                "start_event_loop_stall_watchdog",
                _noop_startup_service,
            )
        )
    if _plugins_browser_pane._load_plugins_catalog is _ORIGINAL_LOAD_PLUGINS_CATALOG:
        stack.enter_context(
            patch.object(
                _plugins_browser_pane,
                "_load_plugins_catalog",
                _empty_plugins_catalog,
            )
        )
    if (
        _project_inventory_panes.collect_repo_inventory
        is _ORIGINAL_COLLECT_REPO_INVENTORY
    ):
        stack.enter_context(
            patch.object(
                _project_inventory_panes,
                "collect_repo_inventory",
                _empty_repo_inventory,
            )
        )
    if (
        _project_inventory_panes.collect_workspace_inventory
        is _ORIGINAL_COLLECT_WORKSPACE_INVENTORY
    ):
        stack.enter_context(
            patch.object(
                _project_inventory_panes,
                "collect_workspace_inventory",
                _empty_workspace_inventory,
            )
        )


def make_changespec(
    name: str = "test_feature",
    description: str = "Test description",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    file_path: str = "/tmp/test.sase",
    commits: list[CommitEntry] | None = None,
    hooks: list[HookEntry] | None = None,
    comments: list[CommentEntry] | None = None,
    deltas: list[DeltaEntry] | None = None,
) -> ChangeSpec:
    """Create a ChangeSpec for testing."""
    return ChangeSpec(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
        file_path=file_path,
        line_number=1,
        commits=commits,
        hooks=hooks,
        comments=comments,
        deltas=deltas,
    )


DEFAULT_CHANGESPECS = [
    make_changespec(name="feature_a"),
    make_changespec(name="feature_b"),
    make_changespec(name="feature_c"),
]


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
        "idx": app.current_idx,
        "total": len(app.changespecs),
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

    # Selected changespec info
    if app.changespecs and 0 <= app.current_idx < len(app.changespecs):
        cs = app.changespecs[app.current_idx]
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


class AcePage:
    """Async context manager wrapping AceApp + Pilot for fluent TUI testing."""

    def __init__(
        self,
        query: str = '"feature"',
        size: tuple[int, int] = (120, 40),
        changespecs: list[ChangeSpec] | None = None,
        model_tier_override: Literal["large", "small"] | None = None,
        initial_tab: Literal["changespecs", "agents", "axe"] = "changespecs",
        notifications: bool = False,
        wait_for_startup_state: bool = True,
        startup_policy: AceStartupPolicy = "fast",
    ) -> None:
        if startup_policy not in {"fast", "real"}:
            raise ValueError(f"unsupported AcePage startup policy: {startup_policy!r}")
        self._query = query
        self._size = size
        self._changespecs = (
            changespecs if changespecs is not None else DEFAULT_CHANGESPECS
        )
        self._model_tier_override: Literal["large", "small"] | None = (
            model_tier_override
        )
        self._initial_tab: Literal["changespecs", "agents", "axe"] = initial_tab
        self._notifications = notifications
        self._wait_for_startup_state = wait_for_startup_state
        self._startup_policy = startup_policy
        self._app: AceApp | None = None
        self._pilot: Any = None
        self._stack: AsyncExitStack | None = None

    async def __aenter__(self) -> "AcePage":
        stack = AsyncExitStack()
        await stack.__aenter__()
        self._stack = stack
        try:
            stack.enter_context(
                patch(
                    "sase.ace.changespec.find_all_changespecs",
                    return_value=self._changespecs,
                )
            )
            stack.enter_context(
                patch(
                    "sase.ace.changespec.find_all_changespecs_cached",
                    return_value=self._changespecs,
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
                    await self._pilot.pause()
                    paused = True
                # Fast fixtures can complete before Textual's run-test enter
                # returns. Give their queued display/focus continuations one
                # turn, matching the settling turn the real loader wait gets.
                if not paused:
                    await self._pilot.pause()
            return self
        except BaseException:
            await stack.aclose()
            self._stack = None
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        stack = self._stack
        self._stack = None
        if stack is not None:
            await stack.__aexit__(exc_type, exc_val, exc_tb)

    async def press(self, *keys: str) -> None:
        """Press one or more keys via the pilot."""
        await self._pilot.press(*keys)

    async def pause(self, delay: float | None = None) -> None:
        """Let the Textual message queue settle.

        Pass ``0`` when the caller has its own semantic or frame-convergence
        barrier and only needs queued messages to drain. The default retains
        Textual's CPU-idle heuristic for general-purpose tests.
        """
        await self._pilot.pause(delay)

    async def click(self, selector: str) -> None:
        """Click a widget by CSS selector."""
        await self._pilot.click(selector)

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
        return self._app.query(selector)

    def query_one_widget(self, selector: str, widget_type: type | None = None) -> Any:
        """Query a single widget by CSS selector."""
        assert self._app is not None
        if widget_type is not None:
            return self._app.query_one(selector, widget_type)
        return self._app.query_one(selector)

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
        deadline = asyncio.get_event_loop().time() + timeout
        last_actual: Any = _SENTINEL
        while True:
            state = self.state
            actual = _resolve_key(state, key)
            last_actual = actual
            if actual == value:
                return
            if asyncio.get_event_loop().time() >= deadline:
                msg = (
                    f"expect_state({key!r}, {value!r}) timed out after"
                    f" {timeout}s — last value was {last_actual!r}"
                )
                raise AssertionError(msg)
            await self._pilot.pause()

    async def expect_modal(self, name: str, *, timeout: float = 5.0) -> None:
        """Assert that the named modal is currently shown."""
        await self.expect_state("modal", name, timeout=timeout)

    async def expect_no_modal(self, *, timeout: float = 5.0) -> None:
        """Assert that no modal is currently shown."""
        await self.expect_state("modal", None, timeout=timeout)

    async def expect_screen_contains(self, text: str, *, timeout: float = 5.0) -> None:
        """Poll screen until text is found, or raise AssertionError."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            screen = self.screen
            if text in screen:
                return
            if asyncio.get_event_loop().time() >= deadline:
                msg = (
                    f"expect_screen_contains({text!r}) timed out after"
                    f" {timeout}s — text not found in screen"
                )
                raise AssertionError(msg)
            await self._pilot.pause()

    async def expect_screen_not_contains(
        self, text: str, *, timeout: float = 5.0
    ) -> None:
        """Poll screen until text is absent, or raise AssertionError."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            screen = self.screen
            if text not in screen:
                return
            if asyncio.get_event_loop().time() >= deadline:
                msg = (
                    f"expect_screen_not_contains({text!r}) timed out after"
                    f" {timeout}s — text still present in screen"
                )
                raise AssertionError(msg)
            await self._pilot.pause()

    async def wait_for(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float = 5.0,
    ) -> None:
        """Poll state until predicate(state) returns True, or raise."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            state = self.state
            if predicate(state):
                return
            if asyncio.get_event_loop().time() >= deadline:
                msg = (
                    f"wait_for() timed out after {timeout}s —"
                    f" predicate never returned True"
                )
                raise AssertionError(msg)
            await self._pilot.pause()


class _PromptTestApp(App[None]):
    """Minimal app hosting a single PromptTextArea for isolation testing."""

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")


class PromptPage:
    """Async context manager wrapping PromptTextArea + Pilot for fluent testing.

    Absorbs the ``_TestApp`` + ``PromptTextArea`` boilerplate that every
    normal-mode test file duplicates::

        async with PromptPage("hello world", cursor=(0, 5)) as page:
            await page.press("d", "w")
            assert page.text == "hello"
    """

    def __init__(
        self,
        text: str = "",
        cursor: tuple[int, int] = (0, 0),
        mode: str = "normal",
        size: tuple[int, int] | None = None,
    ) -> None:
        self._init_text = text
        self._init_cursor = cursor
        self._init_mode = mode
        self._size = size
        self._app: _PromptTestApp | None = None
        self._ta: PromptTextArea | None = None
        self._pilot: Any = None
        self._pilot_cm: Any = None

    async def __aenter__(self) -> "PromptPage":
        self._app = _PromptTestApp()
        if self._size is not None:
            self._pilot_cm = self._app.run_test(size=self._size)
        else:
            self._pilot_cm = self._app.run_test()
        self._pilot = await self._pilot_cm.__aenter__()
        self._ta = self._app.query_one("#ta", PromptTextArea)
        self._ta.text = self._init_text
        self._ta.cursor_location = self._init_cursor
        if self._init_mode == "normal":
            self._ta._enter_normal_mode()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._pilot_cm is not None:
            await self._pilot_cm.__aexit__(exc_type, exc_val, exc_tb)

    async def press(self, *keys: str) -> None:
        """Press one or more keys via the pilot."""
        await self._pilot.press(*keys)

    async def pause(self) -> None:
        """Pause the pilot to let the app process events."""
        await self._pilot.pause()

    @property
    def text(self) -> str:
        """Get the current text content."""
        assert self._ta is not None
        return self._ta.text

    @text.setter
    def text(self, value: str) -> None:
        """Set the text content."""
        assert self._ta is not None
        self._ta.text = value

    @property
    def cursor(self) -> tuple[int, int]:
        """Get the current cursor position."""
        assert self._ta is not None
        return self._ta.cursor_location

    @cursor.setter
    def cursor(self, value: tuple[int, int]) -> None:
        """Set the cursor position."""
        assert self._ta is not None
        self._ta.cursor_location = value

    @property
    def mode(self) -> str:
        """Get the current vim mode."""
        assert self._ta is not None
        return self._ta._vim_mode

    @property
    def ta(self) -> PromptTextArea:
        """Direct access to the underlying PromptTextArea widget."""
        assert self._ta is not None
        return self._ta


class _VimEditorTestApp(App[None]):
    """Minimal app hosting a single VimTextArea-family widget for testing."""

    def __init__(
        self,
        widget_cls: type[VimTextArea],
        text: str,
    ) -> None:
        super().__init__()
        self._widget_cls = widget_cls
        self._text = text
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        yield self._widget_cls(self._text, id="ed")

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        self.submitted.append(event.value)


class VimEditorPage:
    """Async context manager wrapping a bare VimTextArea (or subclass) + Pilot.

    The direct counterpart to :class:`PromptPage` for the shared base widgets::

        async with VimEditorPage("hello world", cursor=(0, 5)) as page:
            await page.press("d", "w")
            assert page.text == "hello"

    Pass ``widget_cls=SingleLineVimTextArea`` to exercise the single-line
    variant. Unlike ``PromptPage`` there is no parent prompt bar, so the host
    hooks fall back to their inert defaults (mode is shown on the widget border).
    """

    def __init__(
        self,
        text: str = "",
        cursor: tuple[int, int] = (0, 0),
        mode: str = "normal",
        size: tuple[int, int] | None = None,
        widget_cls: type[VimTextArea] = VimTextArea,
    ) -> None:
        self._init_text = text
        self._init_cursor = cursor
        self._init_mode = mode
        self._size = size
        self._widget_cls = widget_cls
        self._app: _VimEditorTestApp | None = None
        self._ta: VimTextArea | None = None
        self._pilot: Any = None
        self._pilot_cm: Any = None

    async def __aenter__(self) -> "VimEditorPage":
        self._app = _VimEditorTestApp(self._widget_cls, self._init_text)
        if self._size is not None:
            self._pilot_cm = self._app.run_test(size=self._size)
        else:
            self._pilot_cm = self._app.run_test()
        self._pilot = await self._pilot_cm.__aenter__()
        self._ta = self._app.query_one("#ed", self._widget_cls)
        self._ta.text = self._init_text
        self._ta.cursor_location = self._init_cursor
        if self._init_mode == "normal":
            self._ta._enter_normal_mode()
        self._ta.focus()
        return self

    @property
    def submitted(self) -> list[str]:
        """Values captured from ``SingleLineVimTextArea.Submitted`` messages."""
        assert self._app is not None
        return self._app.submitted

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._pilot_cm is not None:
            await self._pilot_cm.__aexit__(exc_type, exc_val, exc_tb)

    async def press(self, *keys: str) -> None:
        """Press one or more keys via the pilot."""
        await self._pilot.press(*keys)

    async def pause(self) -> None:
        """Pause the pilot to let the app process events."""
        await self._pilot.pause()

    @property
    def text(self) -> str:
        """Get the current text content."""
        assert self._ta is not None
        return self._ta.text

    @text.setter
    def text(self, value: str) -> None:
        assert self._ta is not None
        self._ta.text = value

    @property
    def cursor(self) -> tuple[int, int]:
        """Get the current cursor position."""
        assert self._ta is not None
        return self._ta.cursor_location

    @cursor.setter
    def cursor(self, value: tuple[int, int]) -> None:
        assert self._ta is not None
        self._ta.cursor_location = value

    @property
    def mode(self) -> str:
        """Get the current vim mode."""
        assert self._ta is not None
        return self._ta._vim_mode

    @property
    def ta(self) -> VimTextArea:
        """Direct access to the underlying widget."""
        assert self._ta is not None
        return self._ta


_SENTINEL = object()


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
