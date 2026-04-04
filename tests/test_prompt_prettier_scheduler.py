"""Tests for async prettier scheduling in PromptTextArea formatting mixin."""

from __future__ import annotations

import asyncio

from sase.ace.tui.widgets._text_formatting import TextFormattingMixin


class _CoalescingFormatter(TextFormattingMixin):
    """Minimal test double that tracks scheduled formatting calls."""

    def __init__(self) -> None:
        self._formatting = False
        self._prettier_format_task: asyncio.Task[None] | None = None
        self._prettier_format_requested_generation = 0
        self._prettier_format_completed_generation = 0
        self.calls = 0
        self.first_started = asyncio.Event()
        self.unblock_first = asyncio.Event()

    async def _format_with_prettier(self) -> None:
        self.calls += 1
        if self.calls == 1:
            self.first_started.set()
            await self.unblock_first.wait()


class _CancellableFormatter(TextFormattingMixin):
    """Minimal test double that can be cancelled mid-format."""

    def __init__(self) -> None:
        self._formatting = False
        self._prettier_format_task: asyncio.Task[None] | None = None
        self._prettier_format_requested_generation = 0
        self._prettier_format_completed_generation = 0
        self.started = asyncio.Event()
        self.never = asyncio.Event()

    async def _format_with_prettier(self) -> None:
        self.started.set()
        await self.never.wait()


async def test_schedule_prettier_format_coalesces_requests() -> None:
    formatter = _CoalescingFormatter()

    formatter._schedule_prettier_format()
    formatter._schedule_prettier_format()
    formatter._schedule_prettier_format()

    await asyncio.wait_for(formatter.first_started.wait(), timeout=1.0)
    assert formatter.calls == 1

    # Multiple new requests while first run is still in progress should
    # coalesce into only one additional formatter pass.
    formatter._schedule_prettier_format()
    formatter._schedule_prettier_format()

    task = formatter._prettier_format_task
    assert task is not None
    formatter.unblock_first.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert formatter.calls == 2
    assert formatter._prettier_format_task is None


async def test_cancel_pending_prettier_format_clears_task() -> None:
    formatter = _CancellableFormatter()
    formatter._schedule_prettier_format()

    await asyncio.wait_for(formatter.started.wait(), timeout=1.0)

    task = formatter._prettier_format_task
    assert task is not None

    formatter._cancel_pending_prettier_format()
    assert formatter._prettier_format_task is None

    await asyncio.wait_for(task, timeout=1.0)
