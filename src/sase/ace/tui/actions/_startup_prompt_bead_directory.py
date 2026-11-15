"""App-level warm bead-store directory for prompt K previews."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sase.ace.tui.models.bead_preview import (
        BeadMentionIndex,
        BeadMentionResolutionPlan,
        BeadStoreDirectory,
        BeadStoreRef,
    )

log = logging.getLogger(__name__)


class StartupPromptBeadDirectoryMixin:
    """Mixin for the app-wide warm bead-store directory used by prompt K."""

    _bead_store_directory: BeadStoreDirectory | None
    _bead_store_directory_generation: int
    _bead_store_directory_warming: bool
    _bead_mention_index: BeadMentionIndex
    _bead_mention_pending: set[str]
    _bead_mention_resolution_in_flight: bool

    def get_bead_store_directory(
        self: Any,
        *,
        schedule: bool = True,
    ) -> BeadStoreDirectory | None:
        """Return the memory-only bead-store directory, or ``None`` if cold."""
        if self._bead_store_directory is not None:
            return self._bead_store_directory
        if schedule:
            self.warm_bead_store_directory()
        return None

    def warm_bead_store_directory(self: Any) -> None:
        """Schedule one in-flight off-thread directory warm."""
        if self._bead_store_directory is not None:
            return
        if self._bead_store_directory_warming:
            return
        self._bead_store_directory_warming = True
        generation = self._bead_store_directory_generation

        async def run_warm() -> None:
            await self._run_bead_store_directory_warm(generation)

        try:
            self.run_worker(
                cast(Any, run_warm),
                name=f"prompt-bead-directory:{generation}",
                group="prompt-bead-directory",
                exclusive=False,
            )
        except Exception:
            self._bead_store_directory_warming = False
            log.exception("Failed to schedule prompt bead-store directory warm")

    async def _run_bead_store_directory_warm(
        self: Any,
        generation: int,
    ) -> None:
        """Load the directory off-thread and publish it if still current."""
        import asyncio

        from sase.ace.tui.models.bead_preview import load_bead_store_directory

        try:
            directory = await asyncio.to_thread(load_bead_store_directory)
        except Exception:
            log.exception("Prompt bead-store directory warm failed")
            return
        finally:
            if generation == self._bead_store_directory_generation:
                self._bead_store_directory_warming = False

        if generation != self._bead_store_directory_generation:
            return
        self.publish_bead_store_directory(directory, generation=generation)

    def publish_bead_store_directory(
        self: Any,
        directory: BeadStoreDirectory,
        *,
        generation: int | None = None,
    ) -> None:
        """Publish a directory loaded inline by a K worker while the cache was cold."""
        if (
            generation is not None
            and generation != self._bead_store_directory_generation
        ):
            return
        self._bead_store_directory = directory
        self._bead_store_directory_warming = False
        self._request_visible_bead_mention_resolution()

    def _request_visible_bead_mention_resolution(self: Any) -> None:
        """Request mention resolution for every mounted prompt pane's text.

        Runs when the warm directory publishes: each pane scans its own
        text (memory only) and queues unresolved IDs. The worker refreshes
        surfaces when results land.
        """
        try:
            from ..widgets.prompt_text_area import PromptTextArea

            text_areas = list(self.query(PromptTextArea))
        except Exception:
            return
        for text_area in text_areas:
            if not getattr(text_area, "is_mounted", False):
                continue
            if not getattr(text_area, "display", True):
                continue
            if not getattr(text_area, "visible", True):
                continue
            try:
                requester = getattr(
                    text_area, "_request_bead_mention_resolution_for_text", None
                )
                if callable(requester):
                    requester()
            except Exception:
                log.debug("Failed to request bead mentions", exc_info=True)

    def _invalidate_bead_store_directory(self: Any, *, reason: str) -> None:
        """Drop the warm directory after config/project source changes."""
        del reason
        self._bead_store_directory_generation += 1
        self._bead_store_directory = None
        self._bead_store_directory_warming = False
        try:
            self._bead_mention_index.clear()
        except Exception:
            pass
        try:
            self._bead_mention_pending.clear()
        except Exception:
            pass

    def bead_mention_index_for_render(self: Any) -> BeadMentionIndex | None:
        """Return the memory-only bead-mention index, or ``None`` if missing.

        Never schedules work: the highlight path calls this per rebuild.
        """
        index = getattr(self, "_bead_mention_index", None)
        return index

    def seed_bead_mention_status(
        self: Any,
        bead_id: str,
        status: str | None,
        *,
        store_key: str,
        fingerprint_token: str | None,
    ) -> bool:
        """Seed one index entry from a just-loaded bead card (memory only).

        Returns whether the index changed. Callers refresh surfaces only
        when this returns ``True``.
        """
        from sase.ace.tui.models.bead_preview import BeadMentionEntry

        index = getattr(self, "_bead_mention_index", None)
        if index is None or not bead_id or not store_key:
            return False
        try:
            changed = index.store(
                bead_id,
                BeadMentionEntry(
                    status=status,
                    store_key=store_key,
                    fingerprint_token=fingerprint_token,
                ),
            )
        except Exception:
            log.debug("Failed to seed bead mention %r", bead_id, exc_info=True)
            return False
        if changed:
            try:
                refresher = getattr(
                    self, "_refresh_visible_prompt_semantic_surfaces", None
                )
                if callable(refresher):
                    refresher(global_change=True)
            except Exception:
                log.debug("Failed to refresh bead mention surfaces", exc_info=True)
        return changed

    def request_bead_mention_resolution(self: Any, bead_ids: Iterable[str]) -> None:
        """Queue bead IDs for off-thread status resolution (coalesced).

        Memory only: unknown IDs accumulate in a pending set and one worker
        resolves them. A second call while a worker is in flight only grows
        the set (last-request-wins); the worker drains it whole and
        reschedules when new IDs arrived meanwhile. Never call per
        keystroke: triggers are prompt mount, directory publish, NORMAL-mode
        entry, and K/Ctrl+] resolutions.
        """
        pending = getattr(self, "_bead_mention_pending", None)
        if pending is None:
            return
        wanted = {str(bead_id) for bead_id in bead_ids}
        wanted.discard("")
        if wanted:
            pending.update(wanted)
        if not pending:
            return
        if getattr(self, "_bead_store_directory", None) is None:
            try:
                self.warm_bead_store_directory()
            except Exception:
                log.debug("Failed to warm bead directory for mentions", exc_info=True)
            return
        if getattr(self, "_bead_mention_resolution_in_flight", False):
            return
        self._bead_mention_resolution_in_flight = True
        generation = int(getattr(self, "_bead_store_directory_generation", 0))

        async def run_resolve() -> None:
            await self._run_bead_mention_resolution(generation)

        try:
            self.run_worker(
                cast(Any, run_resolve),
                name=f"prompt-bead-mentions:{generation}",
                group="prompt-bead-mentions",
                exclusive=False,
            )
        except Exception:
            self._bead_mention_resolution_in_flight = False
            log.exception("Failed to schedule bead mention resolution")

    async def _run_bead_mention_resolution(
        self: Any,
        generation: int,
    ) -> None:
        """Resolve pending mention IDs off-thread and publish if current."""
        import asyncio

        try:
            directory = getattr(self, "_bead_store_directory", None)
            index = getattr(self, "_bead_mention_index", None)
            pending = getattr(self, "_bead_mention_pending", None)
            if directory is None or index is None or pending is None:
                return
            requested = sorted(pending)
            pending.clear()
            if not requested:
                return
            plan = self._plan_bead_mention_resolution(requested, directory, index)
            if not plan:
                return
            from sase.ace.tui.models.bead_preview import (
                resolve_bead_mention_updates,
            )

            updates = await asyncio.to_thread(resolve_bead_mention_updates, plan)
        except Exception:
            log.exception("Bead mention resolution failed")
            return
        finally:
            if generation == getattr(self, "_bead_store_directory_generation", 0):
                self._bead_mention_resolution_in_flight = False

        if generation != getattr(self, "_bead_store_directory_generation", 0):
            return
        changed = False
        seen: set[str] = set()
        for bead_id, entry in updates:
            if bead_id in seen:
                continue
            seen.add(bead_id)
            try:
                changed = self._bead_mention_index.store(bead_id, entry) or changed
            except Exception:
                log.debug("Failed to publish bead mention %r", bead_id, exc_info=True)
        if changed:
            try:
                self._refresh_visible_prompt_semantic_surfaces(global_change=True)
            except Exception:
                log.debug("Failed to refresh bead mention surfaces", exc_info=True)
        if self._bead_mention_pending:
            self.request_bead_mention_resolution(())

    def _plan_bead_mention_resolution(
        self: Any,
        requested: list[str],
        directory: BeadStoreDirectory,
        index: BeadMentionIndex,
    ) -> BeadMentionResolutionPlan:
        """Group requested IDs by owning store (memory only, UI thread).

        Drops IDs no store owns. Known entries ride along per store so the
        worker can revalidate their fingerprint tokens without another pass.
        """
        from sase.ace.tui.models.bead_preview import BeadMentionStorePlan

        from sase.bead.cross_project import bead_id_prefix

        groups: dict[str, tuple[BeadStoreRef, list[str]]] = {}
        order: list[str] = []
        for bead_id in requested:
            try:
                prefix = bead_id_prefix(bead_id)
            except Exception:
                continue
            if prefix is None:
                continue
            try:
                owners = directory.owners_for_prefix(prefix)
            except Exception:
                continue
            if not owners:
                continue
            store = owners[0]
            key = str(store.beads_dir)
            if key not in groups:
                groups[key] = (store, [])
                order.append(key)
            if bead_id not in groups[key][1]:
                groups[key][1].append(bead_id)
        planned: list[BeadMentionStorePlan] = []
        for key in order:
            store, candidates = groups[key]
            try:
                known = index.entries_for_store(key)
            except Exception:
                known = ()
            known_ids = {bead_id for bead_id, _entry in known}
            stale = [bead_id for bead_id in known_ids if bead_id not in candidates]
            planned.append(
                BeadMentionStorePlan(
                    store=store,
                    candidates=tuple(candidates + stale),
                    known=tuple(known),
                )
            )
        return tuple(planned)


__all__ = ["StartupPromptBeadDirectoryMixin"]
