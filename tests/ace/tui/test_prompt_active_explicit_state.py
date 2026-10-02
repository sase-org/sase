"""Explicit prompt-active state parity with the DOM query.

Phase ``tick-compare-skip``: ``_prompt_input_active`` is backed by the
explicit ``app._active_prompt_bar`` reference instead of a per-second DOM
query. This test drives open, cancel, submit-path unmount, editor
suspend/resume, and remount across every prompt mode and asserts the
explicit state equals the DOM query at each step.
"""

from __future__ import annotations

import pytest
from textual.app import ScreenStackError

from sase.ace.testing import wait_for
from sase.ace.tui.actions._event_base import EventHandlersBase
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
