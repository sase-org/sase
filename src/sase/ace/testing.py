"""Playwright-inspired testing DSL for the ace TUI."""

import asyncio
from collections.abc import Callable
from typing import Any, Literal
from unittest.mock import patch

from sase.ace.agent_runner import capture_screen, extract_state
from sase.ace.changespec import ChangeSpec, CommentEntry, CommitEntry, HookEntry
from sase.ace.tui import AceApp


# pyvision: tests/test_ace_testing.py
def make_changespec(
    name: str = "test_feature",
    description: str = "Test description",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    file_path: str = "/tmp/test.gp",
    commits: list[CommitEntry] | None = None,
    hooks: list[HookEntry] | None = None,
    comments: list[CommentEntry] | None = None,
) -> ChangeSpec:
    """Create a ChangeSpec for testing."""
    return ChangeSpec(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path=file_path,
        line_number=1,
        commits=commits,
        hooks=hooks,
        comments=comments,
    )


DEFAULT_CHANGESPECS = [
    make_changespec(name="feature_a"),
    make_changespec(name="feature_b"),
    make_changespec(name="feature_c"),
]


# pyvision: tests/test_ace_testing.py
class AcePage:
    """Async context manager wrapping AceApp + Pilot for fluent TUI testing."""

    def __init__(
        self,
        query: str = '"feature"',
        size: tuple[int, int] = (120, 40),
        changespecs: list[ChangeSpec] | None = None,
        model_tier_override: Literal["large", "small"] | None = None,
    ) -> None:
        self._query = query
        self._size = size
        self._changespecs = (
            changespecs if changespecs is not None else DEFAULT_CHANGESPECS
        )
        self._model_tier_override: Literal["large", "small"] | None = (
            model_tier_override
        )
        self._app: AceApp | None = None
        self._pilot: Any = None
        self._patch: Any = None
        self._pilot_cm: Any = None

    async def __aenter__(self) -> "AcePage":
        self._patch = patch(
            "sase.ace.changespec.find_all_changespecs",
            return_value=self._changespecs,
        )
        self._patch.start()
        self._app = AceApp(
            query=self._query,
            model_tier_override=self._model_tier_override,
            refresh_interval=0,
        )
        self._pilot_cm = self._app.run_test(size=self._size)
        self._pilot = await self._pilot_cm.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        try:
            if self._pilot_cm is not None:
                await self._pilot_cm.__aexit__(exc_type, exc_val, exc_tb)
        finally:
            if self._patch is not None:
                self._patch.stop()

    async def press(self, *keys: str) -> None:
        """Press one or more keys via the pilot."""
        await self._pilot.press(*keys)

    async def click(self, selector: str) -> None:
        """Click a widget by CSS selector."""
        await self._pilot.click(selector)

    @property
    def state(self) -> dict[str, Any]:
        """Extract structured state from the app."""
        assert self._app is not None
        return extract_state(self._app)

    @property
    def screen(self) -> str:
        """Capture the current screen as plain text."""
        assert self._app is not None
        return capture_screen(self._app, self._size[1])

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
        timeout: float = 2.0,
        interval: float = 0.05,
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
            await asyncio.sleep(interval)

    async def expect_modal(self, name: str, *, timeout: float = 2.0) -> None:
        """Assert that the named modal is currently shown."""
        await self.expect_state("modal", name, timeout=timeout)

    async def expect_no_modal(self, *, timeout: float = 2.0) -> None:
        """Assert that no modal is currently shown."""
        await self.expect_state("modal", None, timeout=timeout)

    async def expect_screen_contains(
        self, text: str, *, timeout: float = 2.0, interval: float = 0.05
    ) -> None:
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
            await asyncio.sleep(interval)

    async def expect_screen_not_contains(
        self, text: str, *, timeout: float = 2.0, interval: float = 0.05
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
            await asyncio.sleep(interval)

    async def wait_for(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float = 2.0,
        interval: float = 0.05,
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
            await asyncio.sleep(interval)


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
