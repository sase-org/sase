"""Disk load, query-index, and apply helpers for the Patches pane."""

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
from ...util.trace import tui_trace
from sase.core.artifact_relations import RelationIndex

from ._relation_index import patches_pane_is_visible, resolve_patch_relation_index

_MISSING = object()


def is_mock(value: object) -> bool:
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


@dataclass(frozen=True)
class _PreparedPatchLoad:
    """Patch disk load plus worker-built query index."""

    all_patches: list[Patch]
    query_index: ArtifactQueryIndex | None
    pr_unmirrored_counts: dict[str, int]
    relation_index: RelationIndex | None = None
    relation_index_deferred: bool = False


class PatchLoadingApplyMixin:
    """Mixin providing patch disk load, query-index, and apply methods."""

    patches: list[Patch]
    current_idx: int
    parsed_query: QueryExpr
    query_string: str
    hide_reverted: bool
    hide_submitted: bool
    marked_indices: set[int]
    _all_patches: list[Patch]
    _hidden_reverted_count: int
    _hidden_submitted_count: int
    _patches_first_load_done: bool
    _patch_query_profile: CompiledQueryProfile | None
    _patch_query_index: ArtifactQueryIndex | None
    _patch_query_index_source_list_id: int | None
    _patch_query_index_generation: int
    _patch_query_result_cache: OrderedDict[ArtifactQueryCacheKey, ArtifactQueryResult]
    _pr_unmirrored_counts_by_display_name: dict[str, int]
    _patch_relation_index: RelationIndex | None
    _patch_relation_index_for_id: int | None
    _patch_relation_index_deferred: bool
    _patch_limit_truncated: bool

    def _compat_loader(
        self,
        legacy_loader: Callable[[], list[Patch]],
        canonical_loader: Callable[[], list[Patch]],
    ) -> Callable[[], list[Patch]]:
        if getattr(self, "current_tab", None) == "changespecs":  # legacy tab id
            return legacy_loader
        if is_mock(legacy_loader):
            return legacy_loader
        if is_mock(canonical_loader):
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
            if is_mock(legacy_uncached) or is_mock(canonical_uncached):
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

    def _prepare_patch_load_from_disk(
        self, *, build_relations: bool
    ) -> _PreparedPatchLoad:
        """Return Patches and their query index from one worker call."""
        all_patches = self._read_patches_from_disk()
        try:
            query_index = self._compile_patch_query_index(all_patches)
        except (TypeError, ValueError):
            query_index = None
        relation_index, deferred = resolve_patch_relation_index(
            all_patches, build_relations=build_relations
        )
        return _PreparedPatchLoad(
            all_patches=all_patches,
            query_index=query_index,
            pr_unmirrored_counts=_cached_pr_unmirrored_counts(),
            relation_index=relation_index,
            relation_index_deferred=deferred,
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

    def _apply_patches(
        self,
        all_patches: list[Patch],
        *,
        query_index: ArtifactQueryIndex | None | object = _MISSING,
        relation_index: RelationIndex | None | object = _MISSING,
        pr_unmirrored_counts: dict[str, int] | None = None,
        relation_index_deferred: bool | None = None,
    ) -> None:
        """Apply a pre-loaded patch list to app state.

        Must run on the main thread: touches widgets via ``_refresh_display``.
        """
        if pr_unmirrored_counts is not None:
            self._pr_unmirrored_counts_by_display_name = pr_unmirrored_counts
        if query_index is _MISSING:
            self._get_patch_query_index(all_patches)
        else:
            self._apply_prepared_patch_query_index(
                all_patches,
                query_index,  # type: ignore[arg-type]
            )
        self._all_patches = all_patches  # Cache for ancestry lookup
        if relation_index is _MISSING:
            stored, deferred = resolve_patch_relation_index(
                all_patches, build_relations=patches_pane_is_visible(self)
            )
        else:
            stored = relation_index  # type: ignore[assignment]
            deferred = (
                bool(relation_index_deferred)
                if relation_index_deferred is not None
                else False
            )
        self._store_patch_relation_index(all_patches, stored, deferred=deferred)
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

    def _store_patch_relation_index(
        self,
        patches: list[Patch],
        index: RelationIndex | None,
        *,
        deferred: bool = False,
    ) -> None:
        self._patch_relation_index = index
        self._patch_relation_index_for_id = id(patches)
        self._patch_relation_index_deferred = deferred

    def relation_index(self) -> RelationIndex | None:
        """Return the load-owned Patch relation index for ``_all_patches``."""
        patches = getattr(self, "_all_patches", None)
        if patches is None:
            return None
        if getattr(self, "_patch_relation_index_for_id", None) != id(patches):
            return None
        return getattr(self, "_patch_relation_index", None)
