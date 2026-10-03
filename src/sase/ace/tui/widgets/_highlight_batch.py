"""Coalesced highlight-map rebuilds for ``PromptTextArea``.

A cycle edit (``ctrl+n`` / ``ctrl+p``) otherwise pays for one full
``_build_highlight_map`` chain per stage: once inside ``TextArea.edit()``,
again from the glossary and repo-mention context refreshes, and again from
the queued ``Changed`` / ``SelectionChanged`` echoes. This mixin batches the
synchronous builds (one build per :meth:`_highlight_batch` block) and makes
the queued echoes no-ops when their inputs have not changed since the last
run.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class HighlightBatchMixin(_MixinBase):
    """Defer highlight-map rebuilds inside :meth:`_highlight_batch`.

    Mixed first into
    :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea` so this
    ``_build_highlight_map`` is the most-derived override: every build
    request routes through it, including the call inside
    ``TextArea.edit()``. It also owns the idempotency guard for
    ``_on_prompt_completion_context_changed`` so the queued
    ``Changed`` / ``SelectionChanged`` echoes after a cycle edit skip the
    expensive glossary, repo-mention, and Jinja-delimiter refreshers when
    the document text, cursor, and catalog generations are unchanged.
    """

    if TYPE_CHECKING:
        _highlight_batch_depth: int
        _highlight_batch_pending: bool
        _prompt_context_refresh_key: tuple[Any, ...] | None

        text: str
        cursor_location: tuple[int, int]

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._highlight_batch_depth = 0
        self._highlight_batch_pending = False
        self._prompt_context_refresh_key = None
        super().__init__(*args, **kwargs)

    @contextmanager
    def _highlight_batch(self) -> Iterator[None]:
        """Coalesce every highlight-map build inside the block into one."""
        self._highlight_batch_depth += 1
        try:
            yield
        finally:
            self._highlight_batch_depth -= 1
            if self._highlight_batch_depth <= 0:
                self._highlight_batch_depth = 0
                if self._highlight_batch_pending:
                    self._highlight_batch_pending = False
                    super()._build_highlight_map()
                    self.refresh()

    def _build_highlight_map(self) -> None:
        if getattr(self, "_highlight_batch_depth", 0) > 0:
            self._highlight_batch_pending = True
            return
        super()._build_highlight_map()

    def _on_prompt_completion_context_changed(self) -> None:
        key = self._prompt_completion_context_key()
        if key is not None:
            if key == self._prompt_context_refresh_key:
                return
            self._prompt_context_refresh_key = key
        super_changed = getattr(super(), "_on_prompt_completion_context_changed", None)
        if callable(super_changed):
            super_changed()

    def _prompt_completion_context_key(self) -> tuple[Any, ...] | None:
        """Return the idempotency key for a context refresh, if readable.

        The key covers the document text, the cursor offset, and the
        app-owned catalog invalidation generations. Catalog warms that land
        between runs refresh panes through their own publish path, so a
        matching key means the refreshers would recompute identical state.
        ``None`` fails open: the chain runs as before.
        """
        try:
            cursor_offset = self._absolute_offset(self.cursor_location)
            text = self.text
        except Exception:
            return None
        generations: tuple[Any, ...] = ()
        try:
            app: Any = self.app
        except Exception:
            app = None
        if app is not None:
            generations = (
                getattr(app, "_prompt_glossary_generation", None),
                getattr(app, "_prompt_repo_mention_generation", None),
                getattr(app, "_prompt_catalog_generation", None),
            )
        return (text, cursor_offset, *generations)
