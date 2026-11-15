"""App-level warm bead-store directory for prompt K previews."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sase.ace.tui.models.bead_preview import (
        BeadMentionIndex,
        BeadMentionEntry,
        BeadMentionRequest,
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
    _bead_mention_pending: set[BeadMentionRequest]
    _bead_mention_resolution_in_flight: bool
    _bead_mention_resolution_request_id: int
    _bead_mention_resolution_owner: tuple[int, int] | None

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
        self._bead_mention_resolution_owner = None
        self._bead_mention_resolution_in_flight = False
        try:
            self.warm_bead_store_directory()
        except Exception:
            log.debug("Failed to restart bead-store directory warm", exc_info=True)

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
        project_ref: str | None = None,
        context_key: str | None = None,
    ) -> bool:
        """Seed one index entry from a just-loaded bead card (memory only).

        Returns whether the index changed. Callers refresh surfaces only
        when this returns ``True``.
        """
        from sase.ace.tui.models.bead_preview import BeadMentionEntry

        # A card status and a later token observation are not one atomic
        # snapshot. Treat the seed as provisional; the background resolver
        # will read status and fingerprint together on the next discrete run.
        del fingerprint_token

        index = getattr(self, "_bead_mention_index", None)
        if index is None or not bead_id or not store_key:
            return False
        try:
            changed = index.store(
                bead_id,
                BeadMentionEntry(
                    status=status,
                    store_key=store_key,
                    fingerprint_token=None,
                ),
                project_ref=project_ref,
                context_key=context_key,
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
        self.request_bead_mention_resolution(
            (bead_id,),
            project_ref=project_ref,
            context_key=context_key,
        )
        return changed

    def request_bead_mention_resolution(
        self: Any,
        bead_ids: Iterable[str],
        *,
        project_ref: str | None = None,
        context_key: str | None = None,
    ) -> None:
        """Queue scoped bead mentions for off-thread resolution (coalesced).

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
        from sase.ace.tui.models.bead_preview import BeadMentionRequest

        wanted = {
            BeadMentionRequest(str(bead_id), project_ref, context_key)
            for bead_id in bead_ids
            if str(bead_id)
        }
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
        generation = int(getattr(self, "_bead_store_directory_generation", 0))
        request_id = int(getattr(self, "_bead_mention_resolution_request_id", 0)) + 1
        self._bead_mention_resolution_request_id = request_id
        owner = (generation, request_id)
        self._bead_mention_resolution_owner = owner
        self._bead_mention_resolution_in_flight = True

        async def run_resolve() -> None:
            await self._run_bead_mention_resolution(generation, request_id)

        try:
            self.run_worker(
                cast(Any, run_resolve),
                name=f"prompt-bead-mentions:{generation}",
                group="prompt-bead-mentions",
                exclusive=False,
            )
        except Exception:
            if getattr(self, "_bead_mention_resolution_owner", None) == owner:
                self._bead_mention_resolution_owner = None
                self._bead_mention_resolution_in_flight = False
            log.exception("Failed to schedule bead mention resolution")

    async def _run_bead_mention_resolution(
        self: Any,
        generation: int,
        request_id: int,
    ) -> None:
        """Resolve pending mention IDs off-thread and publish if current."""
        import asyncio

        owner = (generation, request_id)
        owns_request = False
        updates: list[tuple[BeadMentionRequest, BeadMentionEntry]] = []
        try:
            directory = getattr(self, "_bead_store_directory", None)
            index = getattr(self, "_bead_mention_index", None)
            pending = getattr(self, "_bead_mention_pending", None)
            if directory is None or index is None or pending is None:
                return
            requested = sorted(
                pending,
                key=lambda item: (
                    item.bead_id,
                    item.project_ref or "",
                    item.context_key or "",
                ),
            )
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
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Bead mention resolution failed")
        finally:
            owns_request = (
                getattr(self, "_bead_mention_resolution_owner", None) == owner
            )
            if owns_request:
                self._bead_mention_resolution_owner = None
                self._bead_mention_resolution_in_flight = False

        if not owns_request or generation != getattr(
            self, "_bead_store_directory_generation", 0
        ):
            return
        changed = False
        for request, entry in updates:
            try:
                changed = (
                    self._bead_mention_index.store(
                        request.bead_id,
                        entry,
                        project_ref=request.project_ref,
                        context_key=request.context_key,
                    )
                    or changed
                )
            except Exception:
                log.debug(
                    "Failed to publish bead mention %r",
                    request.bead_id,
                    exc_info=True,
                )
        if changed:
            try:
                self._refresh_visible_prompt_semantic_surfaces(global_change=True)
            except Exception:
                log.debug("Failed to refresh bead mention surfaces", exc_info=True)
        if getattr(self, "_bead_mention_pending", None):
            self.request_bead_mention_resolution(())

    def _plan_bead_mention_resolution(
        self: Any,
        requested: list[BeadMentionRequest],
        directory: BeadStoreDirectory,
        index: BeadMentionIndex,
    ) -> BeadMentionResolutionPlan:
        """Capture cached entries for scoped requests without doing routing.

        Actual Rust-backed owner routing and store reads run in the background
        worker; this UI-thread snapshot only copies bounded cache entries.
        """
        from sase.ace.tui.models.bead_preview import BeadMentionResolutionPlan

        known: list[tuple[BeadMentionRequest, Any]] = []
        for request in requested:
            try:
                entry = index.peek(
                    request.bead_id,
                    request.project_ref,
                    context_key=request.context_key,
                )
            except Exception:
                entry = None
            if entry is not None:
                known.append((request, entry))
        return BeadMentionResolutionPlan(
            directory=directory,
            requests=tuple(requested),
            known=tuple(known),
        )


__all__ = ["StartupPromptBeadDirectoryMixin"]
