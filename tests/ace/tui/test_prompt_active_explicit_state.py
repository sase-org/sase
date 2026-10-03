"""Explicit prompt-active state parity with the DOM query.

Phase ``tick-compare-skip``: ``_prompt_input_active`` is backed by the
explicit ``app._active_prompt_bar`` reference instead of a per-second DOM
query. This test drives open, cancel, submit-path unmount, editor
suspend/resume, and remount across every prompt mode and asserts the
explicit state equals the DOM query at each step.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import ScreenStackError

from sase.ace.testing import wait_for
from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.actions._event_base import EventHandlersBase
from sase.ace.tui.actions.agent_workflow._prompt_bar_stash_store import (
    mounted_prompt_bar,
)
from sase.ace.tui.widgets import PromptInputBar
from tests.ace.tui._kill_and_edit_launch_barrier_helpers import (
    PromptLifecycleApp,
    prompt_bar_ready,
)


def _explicit_active(app: PromptLifecycleApp) -> bool:
    """Read prompt-active state through the production mixin method."""
    return EventHandlersBase._prompt_input_active(app)


def _dom_active(app: PromptLifecycleApp) -> bool:
    """Read prompt-active state through the legacy DOM query."""
    try:
        return bool(app.query(PromptInputBar))
    except ScreenStackError:
        return False


def _assert_parity(app: PromptLifecycleApp, expected: bool) -> None:
    """Assert explicit state and DOM query agree on *expected*."""
    assert _explicit_active(app) is expected
    assert _dom_active(app) is expected


def _fresh_app() -> PromptLifecycleApp:
    """Return a lifecycle harness with explicit prompt state initialized."""
    app = PromptLifecycleApp()
    app._active_prompt_bar = None  # type: ignore[attr-defined]
    app._prompt_editor_suspended = False  # type: ignore[attr-defined]
    return app


@pytest.mark.asyncio
async def test_prompt_active_parity_home_bar_open_cancel_remount() -> None:
    """Open, cancel, and remount keep explicit state equal to the DOM."""
    app = _fresh_app()
    async with app.run_test(size=(100, 35)) as pilot:
        _assert_parity(app, False)

        # Open a home prompt bar.
        app._show_prompt_input_bar_for_home(initial_text="hello")
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        _assert_parity(app, True)
        assert app._active_prompt_bar is app.query_one(PromptInputBar)  # type: ignore[attr-defined]

        # Editor suspend/resume with the bar mounted: parity holds, and the
        # short-circuit keeps the state active throughout.
        app._prompt_editor_suspended = True  # type: ignore[attr-defined]
        await pilot.pause()
        _assert_parity(app, True)
        app._prompt_editor_suspended = False  # type: ignore[attr-defined]
        await pilot.pause()
        _assert_parity(app, True)

        # Cancel withdraws the explicit reference synchronously, before the
        # async DOM removal lands.
        app._unmount_prompt_bar()
        assert app._active_prompt_bar is None  # type: ignore[attr-defined]
        await wait_for(pilot, lambda: not _dom_active(app))
        _assert_parity(app, False)

        # Remount publishes the new bar.
        app._show_prompt_input_bar_for_home(initial_text="again")
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        _assert_parity(app, True)


@pytest.mark.asyncio
async def test_prompt_active_parity_submit_path_unmount() -> None:
    """The successful-submit unmount also withdraws the explicit state."""
    app = _fresh_app()
    async with app.run_test(size=(100, 35)) as pilot:
        app._show_prompt_input_bar_for_home(initial_text="ship it")
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        _assert_parity(app, True)

        app._unmount_prompt_bar_after_submit()
        assert app._active_prompt_bar is None  # type: ignore[attr-defined]
        await wait_for(pilot, lambda: not _dom_active(app))
        _assert_parity(app, False)


@pytest.mark.asyncio
async def test_prompt_active_parity_feedback_and_approve_modes() -> None:
    """Feedback and approve bars publish through the same widget hook."""
    app = _fresh_app()
    async with app.run_test(size=(100, 35)) as pilot:
        await app.mount(PromptInputBar(mode="feedback", id="prompt-input-bar"))
        await wait_for(pilot, lambda: _dom_active(app))
        await pilot.pause()
        _assert_parity(app, True)

        app._unmount_prompt_bar()
        await wait_for(pilot, lambda: not _dom_active(app))
        _assert_parity(app, False)

        await app.mount(
            PromptInputBar(
                initial_value="edited prompt",
                mode="approve_prompt",
                id="prompt-input-bar",
            )
        )
        await wait_for(pilot, lambda: _dom_active(app))
        await pilot.pause()
        _assert_parity(app, True)

        app._unmount_prompt_bar()
        await wait_for(pilot, lambda: not _dom_active(app))
        _assert_parity(app, False)


@pytest.mark.asyncio
async def test_prompt_active_suspend_without_bar_stays_active() -> None:
    """Editor suspend reports active even with no bar mounted by design."""
    app = _fresh_app()
    async with app.run_test(size=(100, 35)) as pilot:
        _assert_parity(app, False)
        app._prompt_editor_suspended = True  # type: ignore[attr-defined]
        await pilot.pause()
        assert _explicit_active(app) is True
        assert _dom_active(app) is False
        app._prompt_editor_suspended = False  # type: ignore[attr-defined]
        await pilot.pause()
        _assert_parity(app, False)


def _raise_on_dom(*_args: Any, **_kwargs: Any) -> Any:
    """Fail a test that reaches the widget DOM."""
    raise AssertionError("must not query the DOM")


def test_mounted_prompt_bar_prefers_explicit_state_without_dom() -> None:
    """The accessor returns the explicit bar even when the DOM is unreadable."""
    bar = SimpleNamespace(is_mounted=True)
    host = SimpleNamespace(_active_prompt_bar=bar, query_one=_raise_on_dom)
    assert mounted_prompt_bar(host) is bar


def test_mounted_prompt_bar_stale_reference_falls_back_to_dom() -> None:
    """A stale explicit reference (failed mount) reads as no bar.

    A bar removed without the detach hook — or a mount that never landed —
    leaves ``_active_prompt_bar`` pointing at an unmounted widget. The
    accessor must ignore it (falling back to the DOM) and the explicit
    active check must stay False, so ticks are never suppressed forever.
    """
    stale = SimpleNamespace(is_mounted=False)
    host: Any = SimpleNamespace(
        _prompt_editor_suspended=False,
        _active_prompt_bar=stale,
        query_one=_raise_on_dom,
    )
    assert mounted_prompt_bar(host) is None
    assert EventHandlersBase._prompt_input_active(host) is False


def test_mounted_prompt_bar_dom_fallback_without_explicit_state() -> None:
    """Hosts without explicit state keep the legacy DOM lookup."""
    bar = SimpleNamespace(is_mounted=True)
    host = SimpleNamespace(query_one=lambda _s, _c: bar)
    assert mounted_prompt_bar(host) is bar
    assert mounted_prompt_bar(SimpleNamespace()) is None


def _allow_all(_action: str, _parameters: tuple[object, ...]) -> bool:
    return True


def _dom_free_app(prompt_active: bool) -> SimpleNamespace:
    """Return an availability host whose DOM queries fail the test."""
    return SimpleNamespace(
        current_tab="agents",
        screen=object(),
        query=_raise_on_dom,
        query_one=_raise_on_dom,
        _get_selected_agent=lambda: None,
        _prompt_input_active=lambda: prompt_active,
    )


def test_prompt_gated_check_action_needs_no_dom_walk() -> None:
    """Prompt-gated availability resolves without any DOM query."""
    assert (
        check_app_action(_dom_free_app(True), "restore_prompt_stash", (), _allow_all)
        is False
    )
    assert (
        check_app_action(_dom_free_app(False), "restore_prompt_stash", (), _allow_all)
        is True
    )
