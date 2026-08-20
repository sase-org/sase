"""Patch loading, filtering, and reload logic for the ace TUI app."""

from __future__ import annotations

import sys
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from sase.ace.query_profile import CompiledQueryProfile
    from sase.core.query_profile_corpus_facade import (
        ArtifactQueryCacheKey,
        ArtifactQueryIndex,
        ArtifactQueryResult,
    )

from ....patch import Patch
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from sase.core.artifact_relations import RelationIndex

#: Module-level cache for the PR filter-outcome document, keyed on
#: ``(st_mtime_ns, st_size)`` so an unchanged document is never re-read.
_pr_unmirrored_cache_key: tuple[int, int] | None = None
_pr_unmirrored_cache_value: dict[str, int] = {}


def _cached_pr_unmirrored_counts() -> dict[str, int]:
    """Return PR filter-outcome counts keyed by project display name.

    Pure, synchronous file I/O (one stat plus, on a cache miss, one small
    JSON read) — safe to call from a worker thread or from a synchronous
    load path alike. See ``sase.external_mirror.state`` for the document
    this reads and why it takes no lock.
    """
    global _pr_unmirrored_cache_key, _pr_unmirrored_cache_value
    from sase.external_mirror.state import (
        pr_unmirrored_state_path,
        read_pr_unmirrored_counts,
    )
    from sase.project_display_names import project_display_name_for

    try:
        stat = pr_unmirrored_state_path().stat()
    except OSError:
        _pr_unmirrored_cache_key = None
        _pr_unmirrored_cache_value = {}
        return _pr_unmirrored_cache_value

    key = (stat.st_mtime_ns, stat.st_size)
    if key == _pr_unmirrored_cache_key:
        return _pr_unmirrored_cache_value

    _pr_unmirrored_cache_key = key
    _pr_unmirrored_cache_value = {
        project_display_name_for(project_key): count
        for project_key, count in read_pr_unmirrored_counts().items()
    }
    return _pr_unmirrored_cache_value


def _is_mock(value: object) -> bool:
    """Return whether *value* is a ``unittest.mock.Mock``, without importing it.

    ``unittest.mock`` is only ever imported by test code, so if it is absent
    from ``sys.modules`` nothing in the process can be a ``Mock`` instance —
    this fast path is correct, not merely a heuristic, and it keeps
    ``unittest.mock`` off the production Patch-load import path.
    """
    mock_module = sys.modules.get("unittest.mock")
    if mock_module is None:
        return False
    return isinstance(value, mock_module.Mock)


@dataclass(frozen=True)
class _PreparedPatchLoad:
    """Patch disk load plus worker-built query index."""

    all_patches: list[Patch]
    query_index: ArtifactQueryIndex | None
    pr_unmirrored_counts: dict[str, int]
    relation_index: RelationIndex | None = None


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
    _patch_query_profile: CompiledQueryProfile | None
    _patch_query_index: ArtifactQueryIndex | None
    _patch_query_index_source_list_id: int | None
    _patch_query_index_generation: int
    _patch_query_result_cache: OrderedDict[ArtifactQueryCacheKey, ArtifactQueryResult]
    _pr_unmirrored_counts_by_display_name: dict[str, int]
    _patch_relation_index: RelationIndex | None
    _patch_relation_index_for_id: int | None
    _patch_limit_truncated: bool

    def _compat_loader(
        self,
        legacy_loader: Callable[[], list[Patch]],
        canonical_loader: Callable[[], list[Patch]],
    ) -> Callable[[], list[Patch]]:
        if getattr(self, "current_tab", None) == "changespecs":  # legacy tab id
            return legacy_loader
        if _is_mock(legacy_loader):
            return legacy_loader
        if _is_mock(canonical_loader):
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
            if _is_mock(legacy_uncached) or _is_mock(canonical_uncached):
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
        """Return Patches and their query index from one worker call."""
        all_patches = self._read_patches_from_disk()
        try:
            query_index = self._compile_patch_query_index(all_patches)
        except (TypeError, ValueError):
            query_index = None
        return _PreparedPatchLoad(
            all_patches=all_patches,
            query_index=query_index,
            pr_unmirrored_counts=_cached_pr_unmirrored_counts(),
            relation_index=_build_patch_relation_index(all_patches),
        )

    def _patch_profile(self) -> CompiledQueryProfile:
        """Return the cached compiled Patch profile."""
        from sase.ace.query_profile import compiled_profile_for_builtin_pane

        cached = getattr(self, "_patch_query_profile", None)
        if cached is not None:
            return cached
        profile = compiled_profile_for_builtin_pane("patches")
        if profile is None:
            raise ValueError("Patch query profile is not registered")
        self._patch_query_profile = profile
        return profile

    def _next_patch_query_index_generation(self) -> int:
        generation = getattr(self, "_patch_query_index_generation", 0) + 1
        self._patch_query_index_generation = generation
        return generation

    def _compile_patch_query_index(self, patches: list[Patch]) -> ArtifactQueryIndex:
        """Compile and strictly validate an index for ``patches``."""
        from sase.core.query_profile_corpus_facade import compile_artifact_query_index

        index = compile_artifact_query_index(
            pane_id="patches",
            generation=self._next_patch_query_index_generation(),
            profile=self._patch_profile(),
            entries=patches,
        )
        self._validate_patch_query_index(index, patches)
        return index

    def _validate_patch_query_index(
        self, index: ArtifactQueryIndex, patches: list[Patch]
    ) -> None:
        """Raise unless ``index`` matches the current Patch list length."""
        index.validate()
        if len(index) != len(patches):
            raise ValueError(
                "compiled query index length does not match the current "
                "Patch list; rebuild the index before filtering"
            )

    def _apply_prepared_patch_query_index(
        self, patches: list[Patch], query_index: ArtifactQueryIndex | None
    ) -> None:
        """Install a pre-built index before filtering, or clear stale cache."""
        if query_index is None:
            self._patch_query_index = None
            self._patch_query_index_source_list_id = None
            self._clear_patch_query_result_cache()
            return

        self._validate_patch_query_index(query_index, patches)
        replaced = getattr(self, "_patch_query_index", None) is not query_index
        self._patch_query_index = query_index
        self._patch_query_index_source_list_id = id(patches)
        if replaced:
            self._clear_patch_query_result_cache()

    def _apply_patches(self, all_patches: list[Patch]) -> None:
        """Apply a pre-loaded patch list to app state.

        Must run on the main thread: touches widgets via ``_refresh_display``.
        """
        self._get_patch_query_index(all_patches)
        self._all_patches = all_patches  # Cache for ancestry lookup
        self._store_patch_relation_index(
            all_patches, _build_patch_relation_index(all_patches)
        )
        self.patches = self._filter_patches(all_patches)

        # Marks are stable-target based and survive reload; a mark whose
        # Patch dropped out of the filtered list simply stops resolving
        # until that Patch reappears.

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
        self._pr_unmirrored_counts_by_display_name = _cached_pr_unmirrored_counts()
        self._apply_patches(self._read_patches_from_disk())

    def _filter_patches(self, patches: list[Patch]) -> list[Patch]:
        """Filter patches using the parsed query and hide settings."""
        with tui_trace("patch.filter", count=len(patches)):
            return self._filter_patches_impl(patches)

    def _filter_patches_impl(self, patches: list[Patch]) -> list[Patch]:
        from ....patch import get_base_status
        from ....query import build_query_context
        from ....query.evaluator import (
            query_explicitly_targets_submitted,
            query_explicitly_targets_terminal,
        )

        from ....query.limit_token import LimitTokenError, apply_limit, extract_limit

        display_query_fn = getattr(self, "_display_patch_query", None)
        display_query = (
            display_query_fn() if callable(display_query_fn) else self.query_string
        )
        try:
            membership_query, cap = extract_limit(display_query)
        except LimitTokenError:
            membership_query, cap = display_query, None
        display_parsed_query_fn = getattr(self, "_display_patch_parsed_query", None)
        display_parsed_query = (
            display_parsed_query_fn()
            if callable(display_parsed_query_fn)
            else self.parsed_query
        )

        # Status map drives the hide-toggle logic below. Building the
        # context here is cheap (eager name/status maps only) and keeps
        # the lazy searchable_text/ancestor_memo path warm if anything
        # calls evaluate_query_with_context elsewhere on this list.
        ctx = build_query_context(patches)
        status_map = ctx.status_map

        index = self._get_patch_query_index(patches)
        if not membership_query.strip():
            result = list(patches)
        else:
            query_result = self._patch_query_result(membership_query, index)
            result = [
                cs
                for cs, keep in zip(patches, query_result.matched_mask, strict=True)
                if keep
            ]

        # Determine effective hide settings (disabled if query targets them)
        effective_hide_reverted = (
            self.hide_reverted
            and not query_explicitly_targets_terminal(
                display_parsed_query, patches, status_map=status_map
            )
        )
        effective_hide_submitted = (
            self.hide_submitted
            and not query_explicitly_targets_submitted(
                display_parsed_query, patches, status_map=status_map
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

        capped, truncated = apply_limit(result, cap)
        self._patch_limit_truncated = truncated
        return list(capped)

    def _patch_query_result(
        self,
        query: str,
        index: ArtifactQueryIndex,
    ) -> ArtifactQueryResult:
        """Return a cached profile-driven Rust query result."""
        from ....query.profile_reference import canonical_query_for_profile
        from sase.core.query_profile_corpus_facade import evaluate_artifact_query_many

        canonical_query = canonical_query_for_profile(query, index.profile)
        cache_key = index.cache_key(canonical_query)
        cache = getattr(self, "_patch_query_result_cache", None)
        if cache is None:
            cache = OrderedDict()
            self._patch_query_result_cache = cache
        cached = cache.get(cache_key)
        if cached is not None:
            cache.move_to_end(cache_key)
            return cached
        result = evaluate_artifact_query_many(
            query,
            index,
            canonical_query=canonical_query,
        )
        cache[cache_key] = result
        if len(cache) > 32:
            cache.popitem(last=False)
        return result

    def _clear_patch_query_result_cache(self) -> None:
        cache = getattr(self, "_patch_query_result_cache", None)
        if cache is not None:
            cache.clear()

    def _get_patch_query_index(self, patches: list[Patch]) -> ArtifactQueryIndex:
        """Return the cached Rust query index for this exact list object."""
        source_list_id = id(patches)
        cached = getattr(self, "_patch_query_index", None)
        cached_source_list_id = getattr(self, "_patch_query_index_source_list_id", None)
        if (
            cached is not None
            and cached_source_list_id == source_list_id
            and len(cached) == len(patches)
        ):
            cached.validate()
            return cached

        index = self._compile_patch_query_index(patches)
        self._patch_query_index = index
        self._patch_query_index_source_list_id = id(patches)
        self._clear_patch_query_result_cache()
        return index

    def _reload_and_reposition(self, current_name: str | None = None) -> None:
        """Reload patches and try to stay on the same one."""
        if current_name is None:
            current_name = self._snapshot_active_patch_name()

        prepared = self._prepare_patch_load_from_disk()
        self._apply_reloaded_patches(
            prepared.all_patches,
            current_name,
            query_index=prepared.query_index,
            pr_unmirrored_counts=prepared.pr_unmirrored_counts,
            relation_index=prepared.relation_index,
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
            query_index=prepared.query_index,
            pr_unmirrored_counts=prepared.pr_unmirrored_counts,
            relation_index=prepared.relation_index,
        )

    def _apply_reloaded_patches(
        self,
        all_patches: list[Patch],
        current_name: str | None,
        *,
        query_index: ArtifactQueryIndex | None = None,
        pr_unmirrored_counts: dict[str, int] | None = None,
        relation_index: RelationIndex | None = None,
    ) -> None:
        """Apply a freshly-loaded patch list and reposition the cursor."""
        from ...util.selection import restore_selection_by_identity

        if pr_unmirrored_counts is not None:
            self._pr_unmirrored_counts_by_display_name = pr_unmirrored_counts

        on_patches_tab = self._on_patch_list_tab()

        legacy_filter = getattr(self, "_filter_changespecs", None)
        canonical_filter = getattr(self, "_filter_patches", None)
        legacy_filter_fn = legacy_filter if callable(legacy_filter) else None
        canonical_filter_fn = canonical_filter if callable(canonical_filter) else None
        legacy_filter_patched = _is_mock(
            getattr(type(self), "_filter_changespecs", None)
        )
        canonical_filter_patched = _is_mock(
            getattr(type(self), "_filter_patches", None)
        )
        use_legacy_filter = legacy_filter_fn is not None and legacy_filter_patched
        use_canonical_filter = canonical_filter_fn is not None and (
            canonical_filter_patched
            or getattr(self, "current_tab", None) in {"patches"}
        )
        if query_index is None:
            if use_legacy_filter or use_canonical_filter:
                self._apply_prepared_patch_query_index(all_patches, None)
            else:
                self._get_patch_query_index(all_patches)
        else:
            self._apply_prepared_patch_query_index(all_patches, query_index)
        self._all_patches = all_patches  # Cache for ancestry lookup
        stored = (
            relation_index
            if relation_index is not None
            else _build_patch_relation_index(all_patches)
        )
        self._store_patch_relation_index(all_patches, stored)
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

    def _store_patch_relation_index(
        self,
        patches: list[Patch],
        index: RelationIndex | None,
    ) -> None:
        self._patch_relation_index = index
        self._patch_relation_index_for_id = id(patches)

    def relation_index(self) -> RelationIndex | None:
        """Return the load-owned Patch relation index for ``_all_patches``."""
        patches = getattr(self, "_all_patches", None)
        if patches is None:
            return None
        if getattr(self, "_patch_relation_index_for_id", None) != id(patches):
            return None
        return getattr(self, "_patch_relation_index", None)


def _build_patch_relation_index(
    patches: list[Patch],
    *,
    artifact_links: Any | None = None,
) -> RelationIndex | None:
    """Build the Patch relation index on a load path, never a keystroke path."""
    from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
    from sase.ace.tui.models.patch_graph_index import build_patch_graph_index
    from sase.ace.tui.relations import build_patches_relation_index
    from sase.ace.tui.relations import load_artifact_links_snapshot
    from sase.ace.tui.relations._support import relation_index_if_enabled

    contract = compile_builtin_contract("patches", label="Patch", icon="", accent="")
    return relation_index_if_enabled(
        contract,
        lambda compiled: build_patches_relation_index(
            patches,
            build_patch_graph_index(patches),
            contract=compiled,
            artifact_links=artifact_links or load_artifact_links_snapshot(None),
        ),
    )
