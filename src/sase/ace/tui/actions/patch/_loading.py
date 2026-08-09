"""Patch loading, filtering, and reload logic for the ace TUI app."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import Mock

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from sase.core.query_corpus_facade import QueryCorpus

from ....patch import Patch
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace


@dataclass(frozen=True)
class _PreparedPatchLoad:
    """Patch disk load plus worker-built query corpus."""

    all_patches: list[Patch]
    query_corpus: QueryCorpus | None


class PatchLoadingMixin:
    """Mixin providing patch loading, filtering, and reload methods."""

    patches: list[Patch]
    current_idx: int
    parsed_query: QueryExpr
    query_string: str
    hide_reverted: bool
    hide_submitted: bool
    marked_indices: set[int]
    _patches_last_idx: int
    _patches_last_name: str | None
    _all_patches: list[Patch]
    _hidden_reverted_count: int
    _hidden_submitted_count: int
    _patches_loading: bool
    _patches_refresh_scheduled: bool
    _patches_refresh_pending: bool
    _patches_first_load_done: bool
    _current_patch_group_key: tuple[str, ...] | None
    _query_corpus: QueryCorpus | None
    _query_corpus_source_list_id: int | None

    def _compat_loader(
        self,
        legacy_loader: Callable[[], list[Patch]],
        canonical_loader: Callable[[], list[Patch]],
    ) -> Callable[[], list[Patch]]:
        if getattr(self, "current_tab", None) == "changespecs":  # legacy tab id
            return legacy_loader
        if isinstance(legacy_loader, Mock):
            return legacy_loader
        if isinstance(canonical_loader, Mock):
            return canonical_loader
        return canonical_loader

    def _on_patch_list_tab(self) -> bool:
        current_tab = getattr(self, "current_tab", None)
        if current_tab in {
            "artifacts",
            "patches",
            "changespecs",  # legacy compatibility tab id
        }:
            return True
        return current_tab is None and hasattr(self, "patches")

    def _read_patches_from_disk(self) -> list[Patch]:
        """Return the full patch list freshly read from disk.

        Pure disk I/O with no widget access — safe to call from a worker
        thread via ``asyncio.to_thread`` so the Textual event loop stays
        free (e.g. for the startup stopwatch to tick).
        """
        from .... import changespec as changespec_module  # legacy compat module
        from .... import patch as patch_module

        if self._on_patch_list_tab():
            legacy_uncached = (  # legacy compatibility alias
                changespec_module.find_all_changespecs
            )
            canonical_uncached = patch_module.find_all_patches
            if isinstance(legacy_uncached, Mock) or isinstance(
                canonical_uncached, Mock
            ):
                uncached_loader = self._compat_loader(
                    legacy_uncached,
                    canonical_uncached,
                )
                if uncached_loader is not patch_module.find_all_patches:
                    return uncached_loader()
            cached_loader = self._compat_loader(
                changespec_module.find_all_changespecs_cached,  # legacy alias
                patch_module.find_all_patches_cached,
            )
            return cached_loader()
        return patch_module.find_all_patches_cached()

    def _prepare_patch_load_from_disk(self) -> _PreparedPatchLoad:
        """Return Patches and their query corpus from one worker call."""
        all_patches = self._read_patches_from_disk()
        try:
            query_corpus = self._compile_query_corpus_for_patches(all_patches)
        except (TypeError, ValueError):
            query_corpus = None
        return _PreparedPatchLoad(
            all_patches=all_patches,
            query_corpus=query_corpus,
        )

    def _compile_query_corpus_for_patches(self, patches: list[Patch]) -> QueryCorpus:
        """Compile and strictly validate a corpus for ``patches``."""
        from sase.core.query_corpus_facade import compile_query_corpus

        corpus = compile_query_corpus(patches)
        self._validate_query_corpus_for_patches(corpus, patches)
        return corpus

    def _validate_query_corpus_for_patches(
        self, corpus: QueryCorpus, patches: list[Patch]
    ) -> None:
        """Raise unless ``corpus`` was built for this exact list object."""
        source_list_id = id(patches)
        if corpus.source_list_id != source_list_id:
            raise ValueError(
                "compiled query corpus source list id does not match the "
                "current Patch list; rebuild the corpus before filtering"
            )
        if corpus.expected_length != len(patches):
            raise ValueError(
                "compiled query corpus length does not match the current "
                "Patch list; rebuild the corpus before filtering"
            )

    def _apply_prepared_query_corpus(
        self, patches: list[Patch], query_corpus: QueryCorpus | None
    ) -> None:
        """Install a pre-built corpus before filtering, or clear stale cache."""
        if query_corpus is None:
            self._query_corpus = None
            self._query_corpus_source_list_id = None
            return

        self._validate_query_corpus_for_patches(query_corpus, patches)
        self._query_corpus = query_corpus
        self._query_corpus_source_list_id = id(patches)

    def _apply_patches(self, all_patches: list[Patch]) -> None:
        """Apply a pre-loaded patch list to app state.

        Must run on the main thread: touches widgets via ``_refresh_display``.
        """
        self._get_query_corpus_for_patches(all_patches)
        self._all_patches = all_patches  # Cache for ancestry lookup
        self.patches = self._filter_patches(all_patches)

        # Clear marks on reload (indices may shift)
        self.marked_indices = set()  # type: ignore[assignment]

        # Ensure current_idx is within bounds
        if self.patches:
            if self.current_idx >= len(self.patches):
                self.current_idx = len(self.patches) - 1
        else:
            self.current_idx = 0

        self._patches_first_load_done = True
        self._refresh_display()  # type: ignore[attr-defined]

    def _load_patches(self) -> None:
        """Load and filter patches from disk."""
        self._apply_patches(self._read_patches_from_disk())

    def _filter_patches(self, patches: list[Patch]) -> list[Patch]:
        """Filter patches using the parsed query and hide settings."""
        with tui_trace("patch.filter", count=len(patches)):
            return self._filter_patches_impl(patches)

    def _filter_patches_impl(self, patches: list[Patch]) -> list[Patch]:
        from sase.core.query_corpus_facade import evaluate_query_many_with_corpus

        from ....patch import get_base_status
        from ....query import build_query_context
        from ....query.evaluator import (
            query_explicitly_targets_submitted,
            query_explicitly_targets_terminal,
        )

        # Status map drives the hide-toggle logic below. Building the
        # context here is cheap (eager name/status maps only) and keeps
        # the lazy searchable_text/ancestor_memo path warm if anything
        # calls evaluate_query_with_context elsewhere on this list.
        ctx = build_query_context(patches)
        status_map = ctx.status_map

        corpus = self._get_query_corpus_for_patches(patches)
        if not self.query_string.strip():
            result = list(patches)
        else:
            mask = evaluate_query_many_with_corpus(self.query_string, corpus)
            result = [cs for cs, keep in zip(patches, mask, strict=True) if keep]

        # Determine effective hide settings (disabled if query targets them)
        effective_hide_reverted = (
            self.hide_reverted
            and not query_explicitly_targets_terminal(
                self.parsed_query, patches, status_map=status_map
            )
        )
        effective_hide_submitted = (
            self.hide_submitted
            and not query_explicitly_targets_submitted(
                self.parsed_query, patches, status_map=status_map
            )
        )

        # Filter out hidden statuses
        self._hidden_reverted_count = 0
        self._hidden_submitted_count = 0
        if effective_hide_reverted or effective_hide_submitted:
            filtered: list[Patch] = []
            for cs in result:
                base_status = get_base_status(cs.status)
                if effective_hide_reverted and base_status in ("Reverted", "Archived"):
                    self._hidden_reverted_count += 1
                elif effective_hide_submitted and base_status == "Submitted":
                    self._hidden_submitted_count += 1
                else:
                    filtered.append(cs)
            result = filtered

        return result

    def _get_query_corpus_for_patches(self, patches: list[Patch]) -> QueryCorpus:
        """Return the cached Rust query corpus for this exact list object."""
        source_list_id = id(patches)
        cached = getattr(self, "_query_corpus", None)
        cached_source_list_id = getattr(self, "_query_corpus_source_list_id", None)
        if (
            cached is not None
            and cached_source_list_id == source_list_id
            and cached.source_list_id == source_list_id
            and cached.expected_length == len(patches)
        ):
            return cached

        corpus = self._compile_query_corpus_for_patches(patches)
        self._query_corpus = corpus
        self._query_corpus_source_list_id = id(patches)
        return corpus

    def _reload_and_reposition(self, current_name: str | None = None) -> None:
        """Reload patches and try to stay on the same one."""
        if current_name is None:
            current_name = self._snapshot_active_patch_name()

        prepared = self._prepare_patch_load_from_disk()
        self._apply_reloaded_patches(
            prepared.all_patches,
            current_name,
            query_corpus=prepared.query_corpus,
        )

    def _snapshot_active_patch_name(self) -> str | None:
        """Return the identity of the currently selected Patch.

        Falls back to ``_patches_last_name`` when the Patches pane
        isn't active so off-tab refreshes (file-watcher / async reload
        while on Agents or AXE) restore by identity rather than by the
        cross-tab-shared ``current_idx``.
        """
        on_patches_tab = self._on_patch_list_tab()
        if on_patches_tab and self.patches:
            idx = min(self.current_idx, len(self.patches) - 1)
            return self.patches[idx].name
        return getattr(self, "_patches_last_name", None)

    async def _reload_and_reposition_async(
        self, current_name: str | None = None
    ) -> None:
        """Async variant of _reload_and_reposition.

        Off-loads the disk scan to a background thread and re-captures UI
        state after the await so the load survives user navigation while
        the I/O is in flight.
        """
        import asyncio

        caller_supplied_name = current_name is not None

        prepared = await asyncio.to_thread(self._prepare_patch_load_from_disk)

        # Re-capture current selection AFTER the await — user may have
        # moved with j/k or switched tabs while disk I/O was in flight.
        # Skip if the caller explicitly pinned us to a specific name.
        if not caller_supplied_name:
            current_name = self._snapshot_active_patch_name()

        self._apply_reloaded_patches(
            prepared.all_patches,
            current_name,
            query_corpus=prepared.query_corpus,
        )

    def _apply_reloaded_patches(
        self,
        all_patches: list[Patch],
        current_name: str | None,
        *,
        query_corpus: QueryCorpus | None = None,
    ) -> None:
        """Apply a freshly-loaded patch list and reposition the cursor."""
        from ...util.selection import restore_selection_by_identity

        on_patches_tab = self._on_patch_list_tab()

        legacy_filter = getattr(self, "_filter_changespecs", None)
        canonical_filter = getattr(self, "_filter_patches", None)
        legacy_filter_fn = legacy_filter if callable(legacy_filter) else None
        canonical_filter_fn = canonical_filter if callable(canonical_filter) else None
        legacy_filter_patched = isinstance(
            getattr(type(self), "_filter_changespecs", None), Mock
        )
        canonical_filter_patched = isinstance(
            getattr(type(self), "_filter_patches", None), Mock
        )
        use_legacy_filter = legacy_filter_fn is not None and legacy_filter_patched
        use_canonical_filter = canonical_filter_fn is not None and (
            canonical_filter_patched
            or getattr(self, "current_tab", None) in {"patches"}
        )
        if query_corpus is None:
            if use_legacy_filter or use_canonical_filter:
                self._apply_prepared_query_corpus(all_patches, None)
            else:
                self._get_query_corpus_for_patches(all_patches)
        else:
            self._apply_prepared_query_corpus(all_patches, query_corpus)
        self._all_patches = all_patches  # Cache for ancestry lookup
        if use_legacy_filter and legacy_filter_fn is not None:
            new_patches = legacy_filter_fn(all_patches)
        elif use_canonical_filter and canonical_filter_fn is not None:
            new_patches = canonical_filter_fn(all_patches)
        else:
            new_patches = self._filter_patches(all_patches)

        # Capture the prior visual row before mutating state so we can
        # land on the nearest neighbor when the previously selected
        # Patch has been filtered out (Submitted + hide_submitted).
        if on_patches_tab:
            prior_visual_row = self.current_idx if self.patches else None
        else:
            prior_visual_row = getattr(self, "_patches_last_idx", None)

        # Try to find the same patch by name. When the name was mutated
        # by a suffix strip/append (e.g. revert flow), fall back to the base
        # name before deferring to the neighbor-based helper.
        identity_to_match: str | None = current_name
        if current_name:
            found = any(cs.name == current_name for cs in new_patches)
            if not found:
                from sase.core.patch import strip_reverted_suffix

                base = strip_reverted_suffix(current_name)
                if any(cs.name == base for cs in new_patches):
                    identity_to_match = base
                else:
                    for cs in new_patches:
                        if strip_reverted_suffix(cs.name) == base:
                            identity_to_match = cs.name
                            break

        new_idx = restore_selection_by_identity(
            new_patches,
            prior_identity=identity_to_match,
            prior_visual_row=prior_visual_row,
            identity_fn=lambda cs: cs.name,
        )

        self.patches = new_patches  # type: ignore[assignment]
        if on_patches_tab:
            self.current_idx = new_idx
        else:
            # Off-tab refresh: don't mutate ``current_idx`` (it belongs to
            # whichever tab is active). Update the saved row + identity
            # so a tab switch back lands on the right entry.
            self._patches_last_idx = new_idx
            if new_patches and 0 <= new_idx < len(new_patches):
                self._patches_last_name = new_patches[new_idx].name
            else:
                self._patches_last_name = None
        # Drop stale Patch banner focus when its group's last member dropped
        # out of the filtered set — ``_refresh_display`` will also call
        # ``clear_unknown`` on the fold registry, but the focused banner
        # key has to be cleared here so the renderer doesn't try to
        # highlight a banner that no longer exists.
        if not self._patch_banner_focus_still_valid():  # type: ignore[attr-defined]
            self._current_patch_group_key = None  # type: ignore[attr-defined]
        self._patches_first_load_done = True
        # Skip the (hidden) widget repaint entirely when off-tab. The
        # freshly applied data sits ready and ``watch_current_tab`` will
        # re-run ``_refresh_display`` on switch-back. Avoids the wasted
        # hidden-widget churn that was the source of the footer flicker.
        if on_patches_tab:
            self._refresh_display()  # type: ignore[attr-defined]

    def _schedule_patches_async_refresh(self) -> None:
        """Schedule an async patch reload without blocking.

        Mirrors the agents-tab pattern: if a refresh is already in flight,
        mark a pending follow-up so the in-flight run re-schedules itself
        once it finishes (last-request-wins, collapses stampedes).
        """
        if self._patches_loading:
            self._patches_refresh_pending = True
            return
        if getattr(self, "_patches_refresh_scheduled", False):
            return
        self._patches_refresh_scheduled = True
        self._spawn_patches_refresh_task()

    def _spawn_patches_refresh_task(self) -> None:
        """Run a Patch reload outside Textual's serial message pump."""
        task = spawn_pump_free_task(
            self,
            self._run_patches_async_refresh(),
            name="sase-patches-refresh",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._patches_refresh_scheduled = False

    async def _run_patches_async_refresh(self) -> None:
        """Run the async patch refresh with loading guard."""
        self._patches_refresh_scheduled = False
        if self._patches_loading:
            self._patches_refresh_pending = True
            return
        self._patches_loading = True
        try:
            await self._reload_and_reposition_async()
        finally:
            self._patches_loading = False
            if self._patches_refresh_pending:
                self._patches_refresh_pending = False
                self._schedule_patches_async_refresh()
