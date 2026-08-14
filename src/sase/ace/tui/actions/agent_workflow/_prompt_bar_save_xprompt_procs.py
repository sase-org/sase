"""Async task helpers for prompt-bar xprompt saves."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Coroutine


class PromptBarSaveXpromptTaskMixin:
    """Run save-flow coroutines while keeping them alive until completion."""

    def _spawn_xprompt_save_task(self, coro: Coroutine[object, object, None]) -> None:
        """Run *coro* on the running loop, holding a reference until complete."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        task = loop.create_task(coro)
        tasks = getattr(self, "_xprompt_save_async_tasks", None)
        if tasks is None:
            tasks = set()
            self._xprompt_save_async_tasks = tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)


__all__ = ["PromptBarSaveXpromptTaskMixin"]
