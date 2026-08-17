"""Background common-placeholder cache for ACE placeholder completion."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sase.history.prompt_placeholders import (
        CommonPlaceholderIndex,
        CommonPlaceholderSourceToken,
    )

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _CommonPlaceholdersLoadResult:
    """Off-thread common-placeholder load result."""

    source_token: CommonPlaceholderSourceToken
    index: CommonPlaceholderIndex | None


class StartupCommonPlaceholdersMixin:
    """Mixin providing an app-global, memory-only common-placeholder cache."""

    _common_placeholder_index_cache: CommonPlaceholderIndex | None
    _common_placeholders_cache: list[str] | None
    _common_placeholders_source_token: CommonPlaceholderSourceToken | None
    _common_placeholders_generation: int
    _common_placeholders_rebuild_in_flight: bool
    _common_placeholders_rebuild_pending: bool

    def common_placeholder_index(self: Any) -> CommonPlaceholderIndex | None:
        """Return the warm common-placeholder index without touching disk."""
        return self._common_placeholder_index_cache

    def common_placeholders(self: Any) -> list[str] | None:
        """Return the warm common-placeholder texts without touching disk.

        Derived once from the warm index and cached alongside it so existing
        callers and lightweight test harnesses keep a ``list[str] | None``.
        """
        return self._common_placeholders_cache

    def common_placeholders_generation(self: Any) -> int:
        """Return a counter bumped on every successful cache publish.

        Placeholder menus fold this into their memo key so a menu opened
        against a cold cache recomputes once the saved group lands.
        """
        return self._common_placeholders_generation

    def warm_common_placeholders(self: Any) -> None:
        """Schedule an off-thread cache staleness check and reload."""
        limit = self.get_prompt_completion_settings().common_placeholder_count
        if limit <= 0:
            # Disabled: publish an empty index without ever touching disk. The
            # source token stays unset so that re-enabling the feature still
            # takes the first-warm path, seed included.
            was_cold = self._common_placeholder_index_cache is None
            self._set_empty_common_placeholder_cache()
            self._common_placeholders_source_token = None
            if was_cold:
                self._publish_common_placeholders()
            return

        if self._common_placeholders_rebuild_in_flight:
            self._common_placeholders_rebuild_pending = True
            return

        self._common_placeholders_rebuild_in_flight = True
        self._common_placeholders_rebuild_pending = False
        previous_token = (
            self._common_placeholders_source_token
            if self._common_placeholder_index_cache is not None
            else None
        )

        async def run_rebuild() -> None:
            await self._run_common_placeholders_rebuild(
                limit=limit,
                previous_token=previous_token,
            )

        try:
            self.run_worker(
                cast(Any, run_rebuild),
                name="prompt-common-placeholders",
                group="prompt-common-placeholders",
                exclusive=False,
            )
        except Exception:
            self._common_placeholders_rebuild_in_flight = False
            log.exception("Failed to schedule common-placeholder reload")
            if self._common_placeholder_index_cache is None:
                self._set_empty_common_placeholder_cache()
                self._publish_common_placeholders()

    def forget_common_placeholder(self: Any, text: str) -> None:
        """Optimistically remove *text* and force a store-backed next warm.

        Drops the entry from the warm index and leaves corpus statistics
        untouched, matching the durable store.  Clearing the source token
        takes the first-warm path, whose history seed is a no-op while the
        authoritative store file exists.
        """
        index = self._common_placeholder_index_cache
        if index is not None:
            self._set_common_placeholder_cache(_index_without_text(index, text))
        elif isinstance(self._common_placeholders_cache, list):
            self._common_placeholders_cache = [
                candidate
                for candidate in self._common_placeholders_cache
                if candidate != text
            ]
        self._common_placeholders_source_token = None
        self._publish_common_placeholders()

    def _set_common_placeholder_cache(self: Any, index: CommonPlaceholderIndex) -> None:
        from sase.history.prompt_placeholders import load_common_placeholders

        self._common_placeholder_index_cache = index
        self._common_placeholders_cache = load_common_placeholders(
            len(index.entries),
            index=index,
        )

    def _set_empty_common_placeholder_cache(self: Any) -> None:
        self._set_common_placeholder_cache(_empty_common_placeholder_index())

    async def _run_common_placeholders_rebuild(
        self: Any,
        *,
        limit: int,
        previous_token: CommonPlaceholderSourceToken | None,
    ) -> None:
        """Load the store off-thread and publish on the UI task."""
        import asyncio

        result: _CommonPlaceholdersLoadResult | None = None
        try:
            result = await asyncio.to_thread(
                _load_common_placeholders,
                limit=limit,
                previous_token=previous_token,
            )
        except Exception:
            log.exception("Common-placeholder reload failed")
            if self._common_placeholder_index_cache is None:
                self._set_empty_common_placeholder_cache()
                self._publish_common_placeholders()
        finally:
            self._common_placeholders_rebuild_in_flight = False

        if result is not None:
            self._common_placeholders_source_token = result.source_token
            if result.index is not None:
                self._set_common_placeholder_cache(result.index)
                self._publish_common_placeholders()

        if self._common_placeholders_rebuild_pending:
            self._common_placeholders_rebuild_pending = False
            self.warm_common_placeholders()

    def _publish_common_placeholders(self: Any) -> None:
        """Bump the generation counter and refresh any open placeholder menu."""
        self._common_placeholders_generation += 1
        self._refresh_visible_common_placeholder_surfaces()

    def _refresh_visible_common_placeholder_surfaces(self: Any) -> None:
        """Apply a newly warm cache to active placeholder menus."""
        try:
            from ..widgets.placeholder_completion import (
                PLACEHOLDER_COMPLETION_KIND,
            )
            from ..widgets.prompt_text_area import PromptTextArea

            text_areas = list(self.query(PromptTextArea))
        except Exception:
            return
        for text_area in text_areas:
            if (
                not getattr(text_area, "is_mounted", False)
                or not getattr(text_area, "_file_completion_active", False)
                or getattr(text_area, "_completion_kind", "")
                != PLACEHOLDER_COMPLETION_KIND
            ):
                continue
            try:
                text_area._refresh_file_completion_from_cursor()
            except Exception:
                log.debug(
                    "Failed to refresh common-placeholder completion surface",
                    exc_info=True,
                )


def _load_common_placeholders(
    *,
    limit: int,
    previous_token: CommonPlaceholderSourceToken | None,
) -> _CommonPlaceholdersLoadResult:
    """Seed on first use, then reload only when the store token is stale."""
    from sase.history.prompt_placeholders import (
        common_placeholder_source_token,
        load_common_placeholder_index,
        seed_common_placeholders_from_history,
    )

    if previous_token is None:
        # First warm of this app: a missing store means the feature has never
        # run here, so pay the one-time bounded history scan that makes the
        # menu useful on day one.  A no-op when the store already exists.
        seed_common_placeholders_from_history(limit)

    source_token = common_placeholder_source_token()
    if source_token == previous_token:
        return _CommonPlaceholdersLoadResult(
            source_token=source_token,
            index=None,
        )
    return _CommonPlaceholdersLoadResult(
        source_token=source_token,
        index=_limited_common_placeholder_index(
            load_common_placeholder_index(),
            limit,
        ),
    )


def _empty_common_placeholder_index() -> CommonPlaceholderIndex:
    from sase.history.prompt_placeholders import CommonPlaceholderIndex

    return CommonPlaceholderIndex(
        entries=(),
        prompt_count=0,
        context_frequency={},
        max_count=0,
    )


def _limited_common_placeholder_index(
    index: CommonPlaceholderIndex,
    limit: int,
) -> CommonPlaceholderIndex:
    from sase.history.prompt_placeholders import CommonPlaceholderIndex

    if limit <= 0:
        return CommonPlaceholderIndex(
            entries=(),
            prompt_count=index.prompt_count,
            context_frequency=index.context_frequency,
            max_count=0,
        )
    if len(index.entries) <= limit:
        return index
    entries = index.entries[:limit]
    return CommonPlaceholderIndex(
        entries=entries,
        prompt_count=index.prompt_count,
        context_frequency=index.context_frequency,
        max_count=max((entry.count for entry in entries), default=0),
    )


def _index_without_text(
    index: CommonPlaceholderIndex,
    text: str,
) -> CommonPlaceholderIndex:
    from sase.history.prompt_placeholders import CommonPlaceholderIndex

    remaining = tuple(entry for entry in index.entries if entry.text != text)
    if len(remaining) == len(index.entries):
        return index
    return CommonPlaceholderIndex(
        entries=remaining,
        prompt_count=index.prompt_count,
        context_frequency=index.context_frequency,
        max_count=max((entry.count for entry in remaining), default=0),
    )
