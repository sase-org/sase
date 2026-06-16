"""Prompt-stash capture handler + top-bar indicator refresh.

The prompt bar is presentation-only (boundary rule D6): it captures pane
text(s) and posts a ``PromptInputBar.Stashed`` message.  This mixin is the app
glue that persists the captured panes through ``prompt_stash_facade`` (which
fronts the Rust ``sase_core_rs`` store), shows a toast, and refreshes the
``StashedPromptsIndicator`` badge.  Reads/writes go through the per-user pile at
``prompt_stash_path()`` (``~/.sase/prompt_stash.jsonl``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.tui.widgets._prompt_input_bar_stack_actions import (
        StashedPromptPane,
    )


class PromptBarStashMixin:
    """Persist stashed prompt panes and keep the top-bar badge in sync."""

    _prompt_context: PromptContext | None

    def on_prompt_input_bar_stashed(self, event: object) -> None:
        """Persist stashed panes, toast, and refresh the indicator badge."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.Stashed):
            return

        panes = event.panes
        if not panes:
            # An empty pane stashes nothing; tell the user without touching the
            # store or the badge.
            self.notify("Nothing to stash", severity="warning")  # type: ignore[attr-defined]
            return

        try:
            self._persist_stashed_panes(panes, source=event.source)
        except Exception as exc:  # pragma: no cover - defensive (store/IO error)
            self.notify(  # type: ignore[attr-defined]
                f"Failed to stash prompt: {exc}", severity="error"
            )
            return

        count = len(panes)
        self.notify(  # type: ignore[attr-defined]
            "Stashed prompt" if count == 1 else f"Stashed {count} prompts"
        )
        self._refresh_prompt_stash_indicator()

        if event.dismiss_bar:
            # The bar emptied: drop it via the post-submit path so the stashed
            # text is not *also* re-recorded as cancelled prompt history.
            self._unmount_prompt_bar_after_submit()  # type: ignore[attr-defined]
            self._prompt_context = None

    def _persist_stashed_panes(
        self,
        panes: list[StashedPromptPane],
        *,
        source: str,
    ) -> None:
        """Append each captured pane to the per-user prompt-stash store.

        The originating project (D2 metadata) comes from the active prompt
        context so the Phase 3 restore picker can show a project chip; id and
        timestamp are minted here per entry.
        """
        from datetime import datetime
        from uuid import uuid4

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import (
            PromptStashEntryWire,
            append_prompt_stash,
        )
        from sase.core.time import get_timezone

        path = prompt_stash_path()
        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            else None
        )
        for pane in panes:
            entry = PromptStashEntryWire(
                id=str(uuid4()),
                created_at=datetime.now(get_timezone()).isoformat(),
                text=pane.text,
                frontmatter=pane.frontmatter,
                project=project,
                source=source,
                pane_index=pane.pane_index,
            )
            append_prompt_stash(path, entry)

    def _refresh_prompt_stash_indicator(self) -> None:
        """Reload the stash count from disk and update the top-bar badge."""
        self._apply_prompt_stash_count(self._read_prompt_stash_count())

    def _read_prompt_stash_count(self) -> int:
        """Return the number of stashed prompts on disk (thread-safe read).

        Pure disk read with no widget access, so it is safe to call from a
        worker thread (e.g. wrapped in ``asyncio.to_thread`` during startup).
        Any read/binding failure degrades to ``0`` rather than crashing.
        """
        try:
            from sase.core.paths import prompt_stash_path
            from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

            snapshot = read_prompt_stash_snapshot(prompt_stash_path())
        except Exception:
            return 0
        return len(snapshot.entries)

    def _apply_prompt_stash_count(self, count: int) -> None:
        """Push *count* into the ``StashedPromptsIndicator`` badge widget."""
        from ...widgets import StashedPromptsIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#stashed-prompts-indicator", StashedPromptsIndicator
            )
        except Exception:
            return
        indicator.set_count(count)
