"""Regression tests for prompt-stash app handlers leaving the pump quickly."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable

import pytest

from sase.ace.tui.widgets._prompt_input_bar_stack_actions import StashedPromptPane
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._prompt_stash_restore_helpers import _RestoreHarness


async def _assert_handler_returns_while_read_is_stuck(
    harness: _RestoreHarness,
    invoke: Callable[[], Awaitable[None]],
    *,
    counts_read: bool = False,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def _slow_read() -> object:
        entered.set()
        release.wait(timeout=1.0)
        return (0, 0) if counts_read else []

    attr = "_read_prompt_stash_counts" if counts_read else "_read_prompt_stash_entries"
    setattr(harness, attr, _slow_read)
    try:
        await asyncio.wait_for(invoke(), timeout=0.05)
        assert getattr(harness, "_prompt_stash_async_tasks", set())
        await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=0.5)

        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=0.05)
    finally:
        release.set()
        while tasks := list(getattr(harness, "_prompt_stash_async_tasks", set())):
            await asyncio.gather(*tasks)
            await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ["restore_event", "restore_action", "open_action", "update_pinned"],
)
async def test_store_read_handlers_return_while_store_is_stuck(
    operation: str,
) -> None:
    harness = _RestoreHarness()
    panes = [StashedPromptPane(text="draft")]
    invocations: dict[str, Callable[[], Awaitable[None]]] = {
        "restore_event": lambda: harness.on_prompt_input_bar_restore_requested(
            PromptInputBar.RestoreRequested("prompt")
        ),
        "restore_action": harness.action_restore_prompt_stash,
        "open_action": harness.action_open_prompt_stash,
        "update_pinned": lambda: harness.on_prompt_input_bar_update_pinned_requested(
            PromptInputBar.UpdatePinnedRequested(panes)
        ),
    }

    await _assert_handler_returns_while_read_is_stuck(
        harness,
        invocations[operation],
    )


@pytest.mark.asyncio
async def test_focus_handler_returns_while_badge_read_is_stuck() -> None:
    harness = _RestoreHarness()

    await _assert_handler_returns_while_read_is_stuck(
        harness,
        lambda: harness.on_app_focus(None),
        counts_read=True,
    )
