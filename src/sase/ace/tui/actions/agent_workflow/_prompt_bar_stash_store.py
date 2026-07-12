"""Shared prompt-stash store, badge, and asynchronous task helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.ace.tui.widgets import PromptInputBar
    from sase.core.prompt_stash_wire import (
        PromptStashEntryWire,
        PromptStashSnapshotWire,
    )


class PromptBarStashStoreMixin:
    """Provide prompt-stash persistence reads and indicator synchronization."""

    def _mounted_prompt_bar(self) -> PromptInputBar | None:
        """Return the mounted ``#prompt-input-bar`` widget, or ``None``."""
        from ...widgets import PromptInputBar

        try:
            return self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined,no-any-return]
        except Exception:
            return None

    def _read_prompt_stash_entries(self) -> list[PromptStashEntryWire]:
        """Return the stashed entries on disk (empty on any read failure)."""
        try:
            from sase.core.paths import prompt_stash_path
            from sase.core.prompt_stash_facade import (
                PromptStashLockTimeoutError,
                read_prompt_stash_snapshot,
            )

            snapshot = read_prompt_stash_snapshot(prompt_stash_path())
        except PromptStashLockTimeoutError:
            raise
        except Exception:
            return []
        return list(snapshot.entries)

    def _has_stashed_prompts(self) -> bool:
        """Whether any restorable stash exists (drives the footer keymap).

        Reads the in-memory badge count rather than disk so it stays cheap on
        every leader-mode entry; the badge is refreshed on startup and after
        each capture / restore.
        """
        from ...widgets import StashedPromptsIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#stashed-prompts-indicator", StashedPromptsIndicator
            )
        except Exception:
            return False
        return indicator.count > 0

    def _has_pinned_stashed_prompts(self) -> bool:
        """Whether any pinned stash exists (drives the ``gS`` hint gate)."""
        from ...widgets import StashedPromptsIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#stashed-prompts-indicator", StashedPromptsIndicator
            )
        except Exception:
            return False
        return indicator.pinned_count > 0

    async def on_app_focus(self, _event: object) -> None:
        """Reconcile the shared stash badge after terminal focus returns."""
        self._spawn_prompt_stash_task(self._refresh_prompt_stash_badge_async())

    def _refresh_prompt_stash_indicator(self) -> None:
        """Reload the stash count from disk and update the top-bar badge."""
        self._apply_prompt_stash_counts(*self._read_prompt_stash_counts())

    # -- failed-launch recovery (off the event loop) -------------------------

    def _schedule_prompt_stash_badge_refresh(self) -> None:
        """Refresh the stash badge from disk without blocking the event loop.

        Launch-completion handlers run on the Textual event loop; a synchronous
        stash read there would block the paint path. This schedules the disk
        read on a worker thread and applies the result back on the UI thread.
        """
        self._spawn_prompt_stash_task(self._refresh_prompt_stash_badge_async())

    async def _refresh_prompt_stash_badge_async(self) -> None:
        """Read the on-disk stash count off-thread and apply it to the badge."""
        import asyncio

        try:
            counts = await asyncio.to_thread(self._read_prompt_stash_counts)
        except Exception:  # pragma: no cover - defensive (thread/IO error)
            return
        self._apply_prompt_stash_counts(*counts)

    def _schedule_failed_launch_prompt_recovery(self, submitted_prompt: str) -> None:
        """Stash a payloadless failed-launch prompt, then refresh the badge.

        Used when a launch worker died before returning an outcome, so nothing
        recorded the submitted prompt yet. The record/stash and the follow-up
        badge read both run off the event loop.
        """
        self._spawn_prompt_stash_task(
            self._recover_failed_launch_prompt_async(submitted_prompt)
        )

    async def _recover_failed_launch_prompt_async(self, submitted_prompt: str) -> None:
        """Record + stash *submitted_prompt* off-thread, then refresh the badge."""
        import asyncio

        from sase.history.prompt import record_failed_launch_prompt

        try:
            await asyncio.to_thread(record_failed_launch_prompt, submitted_prompt)
        except Exception:  # pragma: no cover - defensive (thread/IO error)
            return
        await self._refresh_prompt_stash_badge_async()

    def _spawn_prompt_stash_task(self, coro: object) -> None:
        """Run *coro* on the running loop, holding a reference until it finishes."""
        import asyncio
        from collections.abc import Coroutine
        from typing import cast

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            cast(Coroutine[object, object, None], coro).close()
            return
        task = loop.create_task(cast("Coroutine[object, object, None]", coro))
        tasks = getattr(self, "_prompt_stash_async_tasks", None)
        if tasks is None:
            tasks = set()
            self._prompt_stash_async_tasks = tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def _read_prompt_stash_count(self) -> int:
        """Return the number of stashed prompts on disk (thread-safe read).

        Pure disk read with no widget access, so it is safe to call from a
        worker thread (e.g. wrapped in ``asyncio.to_thread`` during startup).
        Any read/binding failure degrades to ``0`` rather than crashing.
        """
        return self._read_prompt_stash_counts()[0]

    def _read_prompt_stash_counts(self) -> tuple[int, int]:
        """Return total and pinned stashed-prompt counts from disk."""
        try:
            from sase.core.paths import prompt_stash_path
            from sase.core.prompt_stash_facade import (
                PromptStashLockTimeoutError,
                read_prompt_stash_snapshot,
            )

            snapshot = read_prompt_stash_snapshot(prompt_stash_path())
        except PromptStashLockTimeoutError:
            return self._cached_prompt_stash_counts()
        except Exception:
            return 0, 0
        return self._prompt_stash_snapshot_counts(snapshot)

    def _cached_prompt_stash_counts(self) -> tuple[int, int]:
        """Return the last badge counts without touching the shared store."""
        return getattr(self, "_prompt_stash_cached_counts", (0, 0))

    @staticmethod
    def _prompt_stash_error_message(prefix: str, exc: Exception) -> str:
        from sase.core.prompt_stash_facade import PromptStashLockTimeoutError

        if (
            isinstance(exc, PromptStashLockTimeoutError)
            or (
                exc.__cause__ is not None
                and isinstance(exc.__cause__, PromptStashLockTimeoutError)
            )
            or "prompt stash lock timed out" in str(exc).lower()
        ):
            return "Prompt stash is busy — retry"
        return f"{prefix}: {exc}"

    @staticmethod
    def _prompt_stash_snapshot_counts(
        snapshot: PromptStashSnapshotWire,
    ) -> tuple[int, int]:
        """Return ``(total, pinned)`` counts for a prompt-stash snapshot."""
        entries = list(snapshot.entries)
        return len(entries), sum(1 for entry in entries if entry.pinned)

    def _apply_prompt_stash_snapshot_counts(
        self, snapshot: PromptStashSnapshotWire
    ) -> None:
        """Apply badge counts from an already-available store snapshot."""
        self._apply_prompt_stash_counts(*self._prompt_stash_snapshot_counts(snapshot))

    def _reconcile_prompt_stash_snapshot_counts(
        self, snapshot: PromptStashSnapshotWire
    ) -> None:
        """Apply a worker result only when it differs from optimistic state."""
        counts = self._prompt_stash_snapshot_counts(snapshot)
        if counts != self._cached_prompt_stash_counts():
            self._apply_prompt_stash_counts(*counts)

    def _apply_prompt_stash_counts(self, count: int, pinned_count: int) -> None:
        """Push total and pinned counts into the stash indicator widget."""
        self._prompt_stash_cached_counts = (count, pinned_count)
        from ...widgets import StashedPromptsIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#stashed-prompts-indicator", StashedPromptsIndicator
            )
        except Exception:
            return
        indicator.set_count(count, pinned_count=pinned_count)
