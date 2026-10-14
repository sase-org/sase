"""Reload, reposition, and async refresh helpers for the Patches pane."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.core.query_profile_corpus_facade import ArtifactQueryIndex

from ....patch import Patch
from ...util.pump_tasks import spawn_pump_free_task
from sase.core.artifact_relations import RelationIndex

from ._loading_apply import PatchLoadingApplyMixin, is_mock
from ._relation_index import patches_pane_is_visible, resolve_patch_relation_index

_PATCH_REFRESH_FOLLOW_UP_CAP_SECONDS = 5.0


class PatchLoadingRefreshMixin(PatchLoadingApplyMixin):
    """Mixin providing patch reload, reposition, and async refresh methods."""

    patches: list[Patch]
    current_idx: int
    _patches_last_idx: int
    _patches_last_name: str | None
    _all_patches: list[Patch]
    _patches_loading: bool
    _patches_refresh_scheduled: bool
    _patches_refresh_pending: bool
    _patches_refresh_follow_up_timer: Any
    _last_patches_reload_duration: float
    _patches_first_load_done: bool
    _current_patch_group_key: tuple[str, ...] | None
    _pr_unmirrored_counts_by_display_name: dict[str, int]

    def _reload_and_reposition(self, current_name: str | None = None) -> None:
        """Reload patches and try to stay on the same one."""
        if current_name is None:
            current_name = self._snapshot_active_patch_name()

        prepared = self._prepare_patch_load_from_disk(
            build_relations=patches_pane_is_visible(self)
        )
        self._apply_reloaded_patches(
            prepared.all_patches,
            current_name,
            query_index=prepared.query_index,
            pr_unmirrored_counts=prepared.pr_unmirrored_counts,
            relation_index=prepared.relation_index,
            relation_index_deferred=prepared.relation_index_deferred,
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

        build_relations = patches_pane_is_visible(self)
        prepared = await asyncio.to_thread(
            self._prepare_patch_load_from_disk,
            build_relations=build_relations,
        )

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
            relation_index_deferred=prepared.relation_index_deferred,
        )
        if not build_relations and patches_pane_is_visible(self):
            self._schedule_patches_async_refresh()

    def _apply_reloaded_patches(
        self,
        all_patches: list[Patch],
        current_name: str | None,
        *,
        query_index: ArtifactQueryIndex | None = None,
        pr_unmirrored_counts: dict[str, int] | None = None,
        relation_index: RelationIndex | None = None,
        relation_index_deferred: bool | None = None,
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
        legacy_filter_patched = is_mock(
            getattr(type(self), "_filter_changespecs", None)
        )
        canonical_filter_patched = is_mock(getattr(type(self), "_filter_patches", None))
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
        stored, deferred = self._resolve_applied_patch_relation_index(
            all_patches,
            relation_index=relation_index,
            relation_index_deferred=relation_index_deferred,
        )
        self._store_patch_relation_index(all_patches, stored, deferred=deferred)
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

    def _maybe_schedule_visible_patch_relation_rebuild(self) -> None:
        """Rebuild Patch relation edges when the Patches pane becomes visible."""
        if not patches_pane_is_visible(self):
            return
        if getattr(self, "_patch_relation_index_deferred", False) or getattr(
            self, "_dirty_patches", False
        ):
            self._schedule_patches_async_refresh()

    def _cancel_patches_refresh_follow_up_timer(self) -> None:
        timer = getattr(self, "_patches_refresh_follow_up_timer", None)
        self._patches_refresh_follow_up_timer = None
        if timer is None:
            return
        stop = getattr(timer, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass

    def _arm_patches_refresh_follow_up(self, delay: float) -> None:
        """Debounce the pending follow-up; keep scheduled so requests coalesce."""
        self._cancel_patches_refresh_follow_up_timer()
        self._patches_refresh_scheduled = True
        set_timer = getattr(self, "set_timer", None)
        if not callable(set_timer):
            self._patches_refresh_scheduled = False
            self._schedule_patches_async_refresh()
            return
        try:
            self._patches_refresh_follow_up_timer = set_timer(
                delay, self._on_patches_refresh_follow_up_timer
            )
        except Exception:
            self._patches_refresh_scheduled = False
            self._schedule_patches_async_refresh()

    def _on_patches_refresh_follow_up_timer(self) -> None:
        self._patches_refresh_follow_up_timer = None
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
        started = time.monotonic()
        try:
            await self._reload_and_reposition_async()
        finally:
            self._last_patches_reload_duration = time.monotonic() - started
            self._patches_loading = False
            if self._patches_refresh_pending:
                self._patches_refresh_pending = False
                delay = min(
                    getattr(self, "_last_patches_reload_duration", 0.0),
                    _PATCH_REFRESH_FOLLOW_UP_CAP_SECONDS,
                )
                if delay > 0:
                    self._arm_patches_refresh_follow_up(delay)
                else:
                    self._schedule_patches_async_refresh()

    def _resolve_applied_patch_relation_index(
        self,
        patches: list[Patch],
        *,
        relation_index: RelationIndex | None,
        relation_index_deferred: bool | None,
    ) -> tuple[RelationIndex | None, bool]:
        if relation_index is not None:
            deferred = (
                bool(relation_index_deferred)
                if relation_index_deferred is not None
                else False
            )
            return relation_index, deferred
        return resolve_patch_relation_index(
            patches, build_relations=patches_pane_is_visible(self)
        )
