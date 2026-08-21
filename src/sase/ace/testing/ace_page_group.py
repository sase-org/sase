"""Shared :class:`AcePage` lifetimes for related ACE TUI tests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, fields
from typing import Any, Literal

from sase.ace.query import parse_query
from sase.ace.patch import Patch
from sase.ace.tui.widgets.artifacts.patch_entry import patch_row_target

from .ace_page import AcePage, AceStartupPolicy, _drain_app_work

ACE_PAGE_GROUP_ISOLATION_ENV = "SASE_ACE_PAGE_GROUP_ISOLATION"

ResetHook = Callable[[AcePage], Awaitable[None] | None]


@dataclass(frozen=True)
class _IsolationSnapshot:
    tab: str
    artifacts_subtab: str
    files_subtab: str
    idx: int
    query: str
    canonical_query: str
    marked: tuple[int, ...]
    modal_depth: int
    prompt_bar: bool
    hint_bar: bool
    notifications: int | None
    focus: tuple[str, str | None] | None

    @classmethod
    def capture(
        cls,
        page: AcePage,
        *,
        track_notifications: bool = True,
    ) -> _IsolationSnapshot:
        app = page.app
        return cls(
            tab=app.current_tab,
            artifacts_subtab=app.current_artifacts_subtab,
            files_subtab=app.current_files_subtab,
            idx=app.current_idx,
            query=app.query_string,
            canonical_query=app.canonical_query_string,
            marked=tuple(sorted(app.marked_indices)),
            modal_depth=len(app.screen_stack),
            prompt_bar=_has_widget(app, "#prompt-input-bar"),
            hint_bar=_has_widget(app, "#hint-input-bar"),
            notifications=len(app._notifications) if track_notifications else None,
            focus=_focus_identity(app),
        )

    def diff(self, other: _IsolationSnapshot) -> dict[str, tuple[object, object]]:
        differences: dict[str, tuple[object, object]] = {}
        for field in fields(self):
            actual = getattr(self, field.name)
            expected = getattr(other, field.name)
            if field.name == "notifications" and (actual is None or expected is None):
                continue
            if actual != expected:
                differences[field.name] = (actual, expected)
        return differences


class AcePageGroup:
    """Own one running :class:`AcePage` and hand out isolated checkouts."""

    def __init__(
        self,
        *,
        query: str = '"feature"',
        size: tuple[int, int] = (120, 40),
        patches: list[Patch] | None = None,
        model_tier_override: Literal["large", "small"] | None = None,
        initial_tab: Literal[
            "artifacts",
            "patches",
            "agents",
            "axe",
        ] = "artifacts",
        notifications: bool = False,
        wait_for_startup_state: bool = True,
        startup_policy: AceStartupPolicy = "fast",
        reset_hook: ResetHook | None = None,
    ) -> None:
        self._query = query
        self._size = size
        self._patches = patches
        self._model_tier_override = model_tier_override
        self._initial_tab = initial_tab
        self._notifications = notifications
        self._wait_for_startup_state = wait_for_startup_state
        self._startup_policy = startup_policy
        self._reset_hook = reset_hook
        self._page: AcePage | None = None
        self._baseline: _IsolationSnapshot | None = None
        self._checkout_active = False
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._isolation_mode = _env_enabled(ACE_PAGE_GROUP_ISOLATION_ENV)

    async def __aenter__(self) -> AcePageGroup:
        self._owner_loop = asyncio.get_running_loop()
        if self._isolation_mode:
            return self
        page = self._new_page()
        await page.__aenter__()
        self._page = page
        self._baseline = _IsolationSnapshot.capture(
            page,
            track_notifications=self._notifications,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        page = self._page
        self._page = None
        self._baseline = None
        if page is not None:
            await page.__aexit__(exc_type, exc_val, exc_tb)

    @asynccontextmanager
    async def checkout(self) -> Any:
        """Yield an isolated page checkout from this group."""
        self._ensure_checkout_loop()
        if self._checkout_active:
            raise RuntimeError("AcePageGroup does not support overlapping checkouts")

        self._checkout_active = True
        try:
            if self._isolation_mode:
                async with self._new_page() as page:
                    yield page
                return

            shared_page = self._page
            if shared_page is None:
                raise RuntimeError("AcePageGroup must be entered before checkout")
            try:
                yield shared_page
            finally:
                await self._reset_shared_page(shared_page)
        finally:
            self._checkout_active = False

    def _ensure_checkout_loop(self) -> None:
        owner_loop = self._owner_loop
        current_loop = asyncio.get_running_loop()
        if owner_loop is None:
            raise RuntimeError("AcePageGroup must be entered before checkout")
        if current_loop is not owner_loop:
            raise RuntimeError(
                "AcePageGroup checkouts must use the module-scoped asyncio loop; "
                "mark the module with pytest.mark.asyncio(loop_scope='module')"
            )

    async def _reset_shared_page(self, page: AcePage) -> None:
        baseline = self._baseline
        if baseline is None:
            raise RuntimeError("AcePageGroup baseline is not available")

        app = page.app
        await _drain_app_work(app)
        await _close_extra_screens(page)
        _remove_prompt_surfaces(app)
        app._notifications.clear()
        _reset_navigation_modes(app)
        _restore_baseline_state(app, baseline)
        await app.recompose()
        _restore_focus(app, baseline)
        app._refresh_current_tab()
        await page.pause()

        if self._reset_hook is not None:
            result = self._reset_hook(page)
            if result is not None:
                await result
            await page.pause()

        after = _IsolationSnapshot.capture(
            page,
            track_notifications=self._notifications,
        )
        leaks = after.diff(baseline)
        if leaks:
            lines = [
                f"{name}: expected {expected!r}, got {actual!r}"
                for name, (actual, expected) in sorted(leaks.items())
            ]
            raise AssertionError(
                "AcePageGroup isolation leak(s):\n"
                + "\n".join(f"- {line}" for line in lines)
            )

    def _new_page(self) -> AcePage:
        return AcePage(
            query=self._query,
            size=self._size,
            patches=self._patches,
            model_tier_override=self._model_tier_override,
            initial_tab=self._initial_tab,
            notifications=self._notifications,
            wait_for_startup_state=self._wait_for_startup_state,
            startup_policy=self._startup_policy,
        )


async def _close_extra_screens(page: AcePage) -> None:
    app = page.app
    while len(app.screen_stack) > 1:
        await app.pop_screen()
        await page.pause()


def _remove_prompt_surfaces(app: Any) -> None:
    unmount_prompt = getattr(app, "_unmount_prompt_bar_without_cancel_save", None)
    if callable(unmount_prompt):
        unmount_prompt()
    remove_hint = getattr(app, "_remove_hint_input_bar", None)
    if callable(remove_hint):
        remove_hint(refresh=False)
    app._prompt_context = None


def _reset_navigation_modes(app: Any) -> None:
    for name in (
        "_leader_mode_active",
        "_bang_mode_active",
        "_saved_query_mode_active",
        "_entry_jump_mode_active",
        "_accept_mode_active",
        "_rewind_mode_active",
        "_hint_mode_active",
    ):
        if hasattr(app, name):
            setattr(app, name, False)
    if hasattr(app, "_custom_mode_active"):
        app._custom_mode_active = None
    if hasattr(app, "_entry_jump_pending_prefix"):
        app._entry_jump_pending_prefix = ""


def _restore_baseline_state(app: Any, baseline: _IsolationSnapshot) -> None:
    app.query_string = baseline.query
    app.parsed_query = parse_query(baseline.query)
    if hasattr(app, "_all_patches"):
        app.patches = app._filter_patches(app._all_patches)
    app.current_idx = min(baseline.idx, max(len(app.patches) - 1, 0))
    app._artifacts_marked_targets["patches"] = {
        patch_row_target(app.patches[index])
        for index in baseline.marked
        if 0 <= index < len(app.patches)
    }
    app.current_files_subtab = baseline.files_subtab
    app.current_artifacts_subtab = baseline.artifacts_subtab
    app.current_tab = baseline.tab


def _restore_focus(app: Any, baseline: _IsolationSnapshot) -> None:
    if baseline.focus is None:
        app.screen.set_focus(None)
        return

    class_name, widget_id = baseline.focus
    target = None
    if widget_id is not None:
        try:
            target = app.query_one(f"#{widget_id}")
        except Exception:
            target = None
    if target is None:
        for widget in app.query("*"):
            if type(widget).__name__ == class_name:
                target = widget
                break
    if target is None:
        app.screen.set_focus(None)
    else:
        target.focus()


def _has_widget(app: Any, selector: str) -> bool:
    try:
        app.query_one(selector)
    except Exception:
        return False
    return True


def _focus_identity(app: Any) -> tuple[str, str | None] | None:
    focused = getattr(app.screen, "focused", None)
    if focused is None:
        return None
    return (type(focused).__name__, getattr(focused, "id", None))


def _env_enabled(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}
