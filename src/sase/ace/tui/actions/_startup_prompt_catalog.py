"""Prompt catalog and snippet-cache helpers for ACE startup."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ..glossary_catalog import PromptGlossaryContext
    from ..prompt_catalog import PromptCatalogSnapshot
    from ..widgets.prompt_completion import (
        PromptCompletionSettings,
        PromptSpellcheckSettings,
    )
    from ..widgets.xprompt_arg_assist import XPromptAssistEntry
    from sase.xprompt.glossary_catalog import EditorGlossaryCatalog

log = logging.getLogger(__name__)


class StartupPromptCatalogMixin:
    """Mixin for memory-only prompt catalog and snippet state."""

    _snippets_cache: dict[str, str] | None
    _pending_snippet_saves: dict[str, str]
    _prompt_catalog: PromptCatalogSnapshot | None
    _prompt_catalog_rebuild_in_flight: bool
    _prompt_catalog_rebuild_pending: bool
    _prompt_catalog_rebuild_pending_force: bool
    _prompt_catalog_rebuild_pending_config_dirty: bool
    _prompt_catalog_projects: set[str | None]
    _prompt_catalog_generation: int
    _prompt_catalog_token_check_last_mono: float
    _prompt_catalog_assist_entries_cache: dict[
        str | None,
        list[XPromptAssistEntry],
    ]
    _prompt_glossary_generation: int
    _prompt_glossary_catalogs_by_context: dict[
        PromptGlossaryContext,
        EditorGlossaryCatalog | None,
    ]
    _prompt_glossary_diagnostics_by_context: dict[
        PromptGlossaryContext,
        tuple[str, ...],
    ]
    _prompt_glossary_warming_contexts: set[PromptGlossaryContext]

    def get_snippets(self: Any) -> dict[str, str]:
        """Return the memory-only xprompt + user snippet registry."""
        cached = getattr(self, "_snippets_cache", None)
        if cached is not None:
            self._schedule_prompt_catalog_token_fallback_check()
            return cached
        self._schedule_prompt_catalog_rebuild(reason="snippet_cache_miss")
        return self._user_snippets

    def get_prompt_completion_settings(self: Any) -> PromptCompletionSettings:
        """Return parsed prompt completion behavior settings."""
        return self._prompt_completion_settings

    def get_prompt_spellcheck_settings(self: Any) -> PromptSpellcheckSettings:
        """Return parsed sticky-misspelling-highlight behavior settings."""
        return self._prompt_spellcheck_settings

    def get_prompt_catalog_assist_entries(
        self: Any,
        project: str | None,
        *,
        schedule: bool = True,
    ) -> list[XPromptAssistEntry] | None:
        """Return memory-only xprompt assist entries for *project* if warm."""
        self._ensure_prompt_catalog_project(project)
        catalog = self._prompt_catalog
        if catalog is not None:
            entries = catalog.assist_entries_by_project.get(project)
            if entries is not None:
                self._schedule_prompt_catalog_token_fallback_check()
                return self._cached_prompt_catalog_assist_entries(project, entries)
            if project is not None:
                fallback = catalog.assist_entries_by_project.get(None)
                if fallback is not None:
                    if schedule:
                        self._schedule_prompt_catalog_rebuild(
                            reason="assist_project_miss"
                        )
                    return self._cached_prompt_catalog_assist_entries(None, fallback)
        if schedule:
            self._schedule_prompt_catalog_rebuild(reason="assist_cache_miss")
        return None

    def get_warm_prompt_catalog_assist_entries_exact(
        self: Any,
        project: str | None,
    ) -> list[XPromptAssistEntry] | None:
        """Return the exact memory-only project catalog without fallback."""
        self._ensure_prompt_catalog_project(project)
        catalog = self._prompt_catalog
        if catalog is None:
            return None
        entries = catalog.assist_entries_by_project.get(project)
        if entries is None:
            return None
        self._schedule_prompt_catalog_token_fallback_check()
        return self._cached_prompt_catalog_assist_entries(project, entries)

    def _cached_prompt_catalog_assist_entries(
        self: Any,
        project: str | None,
        entries: tuple[XPromptAssistEntry, ...],
    ) -> list[XPromptAssistEntry]:
        """Return a stable list for *entries* during this catalog snapshot."""
        cached = self._prompt_catalog_assist_entries_cache.get(project)
        if cached is None:
            cached = list(entries)
            self._prompt_catalog_assist_entries_cache[project] = cached
        return cached

    def warm_prompt_catalog_project(self: Any, project: str | None) -> None:
        """Schedule an off-thread catalog warm for *project*."""
        self._ensure_prompt_catalog_project(project)
        self._schedule_prompt_catalog_token_fallback_check()
        catalog = self._prompt_catalog
        if (
            catalog is not None
            and project in catalog.assist_entries_by_project
            and self._snippets_cache is not None
        ):
            return
        self._schedule_prompt_catalog_rebuild(reason="assist_warm")

    def get_prompt_glossary_catalog(
        self: Any,
        context: PromptGlossaryContext,
        *,
        schedule: bool = True,
    ) -> EditorGlossaryCatalog | None:
        """Return the memory-only glossary catalog selected by *context*."""
        if context in self._prompt_glossary_catalogs_by_context:
            return self._prompt_glossary_catalogs_by_context[context]
        if schedule:
            self.warm_prompt_glossary_catalog(context)
        return None

    def is_prompt_glossary_catalog_warm(
        self: Any,
        context: PromptGlossaryContext,
    ) -> bool:
        """Return whether *context* has a completed glossary lookup."""
        return context in self._prompt_glossary_catalogs_by_context

    def warm_prompt_glossary_catalog(
        self: Any,
        context: PromptGlossaryContext,
    ) -> None:
        """Schedule an off-thread glossary warm for *context*."""
        if context in self._prompt_glossary_catalogs_by_context:
            return
        if context in self._prompt_glossary_warming_contexts:
            return
        self._prompt_glossary_warming_contexts.add(context)
        generation = self._prompt_glossary_generation

        async def run_warm() -> None:
            await self._run_prompt_glossary_warm(context, generation)

        try:
            self.run_worker(
                cast(Any, run_warm),
                name=f"prompt-glossary:{generation}:{hash(context)}",
                group="prompt-glossary",
                exclusive=False,
            )
        except Exception:
            self._prompt_glossary_warming_contexts.discard(context)
            log.exception("Failed to schedule prompt glossary warm")

    async def _run_prompt_glossary_warm(
        self: Any,
        context: PromptGlossaryContext,
        generation: int,
    ) -> None:
        """Load one glossary context off-thread and publish it if current."""
        import asyncio

        from ..glossary_catalog import load_prompt_glossary_context

        try:
            result = await asyncio.to_thread(
                load_prompt_glossary_context,
                context,
                generation=generation,
            )
        except Exception:
            log.exception("Prompt glossary warm failed")
            if generation == self._prompt_glossary_generation:
                self._prompt_glossary_catalogs_by_context[context] = None
                self._prompt_glossary_diagnostics_by_context[context] = (
                    "prompt glossary warm failed",
                )
            return
        finally:
            self._prompt_glossary_warming_contexts.discard(context)

        if result.generation != self._prompt_glossary_generation:
            return
        self._prompt_glossary_catalogs_by_context[context] = result.catalog
        self._prompt_glossary_diagnostics_by_context[context] = result.diagnostics
        self._refresh_visible_prompt_glossary_surfaces()

    def _invalidate_prompt_glossary_catalogs(self: Any, *, reason: str) -> None:
        """Drop warm glossary catalogs after config/project source changes."""
        del reason
        self._prompt_glossary_generation += 1
        self._prompt_glossary_catalogs_by_context = {}
        self._prompt_glossary_diagnostics_by_context = {}
        self._prompt_glossary_warming_contexts = set()
        self._refresh_visible_prompt_glossary_surfaces()

    def _refresh_visible_prompt_glossary_surfaces(self: Any) -> None:
        """Refresh mounted prompt panes that may show glossary spans."""
        try:
            from ..widgets.prompt_text_area import PromptTextArea

            text_areas = list(self.query(PromptTextArea))
        except Exception:
            return
        for text_area in text_areas:
            if not getattr(text_area, "is_mounted", False):
                continue
            try:
                text_area._build_highlight_map()
                text_area.refresh()
            except Exception:
                log.debug("Failed to refresh prompt glossary surface", exc_info=True)

    def _ensure_prompt_catalog_project(self: Any, project: str | None) -> None:
        """Track requested project catalogs and expand watches when needed."""
        if project in self._prompt_catalog_projects:
            return
        self._prompt_catalog_projects.add(project)
        if self._prompt_source_watcher is not None:
            self._restart_prompt_source_watcher()

    def _schedule_prompt_catalog_token_fallback_check(self: Any) -> None:
        """Schedule a throttled token check when no watcher is active."""
        if self._prompt_source_watcher_active:
            return
        now = time.monotonic()
        if now - self._prompt_catalog_token_check_last_mono < 1.0:
            return
        self._prompt_catalog_token_check_last_mono = now
        self._schedule_prompt_catalog_rebuild(reason="token_fallback")

    def _schedule_prompt_catalog_rebuild(
        self: Any,
        *,
        reason: str,
        force: bool = False,
        config_dirty: bool = False,
    ) -> None:
        """Schedule a prompt catalog rebuild with last-request-wins coalescing."""
        del reason
        self._prompt_catalog_projects.add(None)
        if self._prompt_catalog_rebuild_in_flight:
            self._prompt_catalog_rebuild_pending = True
            self._prompt_catalog_rebuild_pending_force = (
                self._prompt_catalog_rebuild_pending_force or force
            )
            self._prompt_catalog_rebuild_pending_config_dirty = (
                self._prompt_catalog_rebuild_pending_config_dirty or config_dirty
            )
            return

        self._prompt_catalog_rebuild_in_flight = True
        self._prompt_catalog_rebuild_pending = False
        self._prompt_catalog_rebuild_pending_force = False
        self._prompt_catalog_rebuild_pending_config_dirty = False
        generation = self._prompt_catalog_generation
        projects = frozenset(self._prompt_catalog_projects)
        pending_snippet_saves = dict(self._pending_snippet_saves)
        previous_token = (
            None
            if force or config_dirty or self._prompt_catalog is None
            else self._prompt_catalog.source_token
        )

        async def run_rebuild() -> None:
            await self._run_prompt_catalog_rebuild(
                generation,
                projects,
                previous_token,
                pending_snippet_saves,
                config_dirty,
            )

        try:
            self.run_worker(
                cast(Any, run_rebuild),
                name=f"prompt-catalog:{generation}",
                group="prompt-catalog",
                exclusive=False,
            )
        except Exception:
            self._prompt_catalog_rebuild_in_flight = False
            log.exception("Failed to schedule prompt catalog rebuild")

    async def _run_prompt_catalog_rebuild(
        self: Any,
        generation: int,
        projects: frozenset[str | None],
        previous_source_token: tuple[Any, ...] | None,
        pending_snippet_saves: dict[str, str],
        config_dirty: bool,
    ) -> None:
        """Build the prompt catalog off-thread and apply it on the UI task."""
        import asyncio

        from ..prompt_catalog import build_prompt_catalog_snapshot

        snapshot = None
        try:
            snapshot = await asyncio.to_thread(
                build_prompt_catalog_snapshot,
                generation=generation,
                projects=projects,
                previous_source_token=previous_source_token,
                pending_snippet_saves=pending_snippet_saves,
                config_dirty=config_dirty,
            )
        except Exception:
            log.exception("Prompt catalog rebuild failed")
            try:
                self.notify(
                    "Failed to reload snippets/xprompts; keeping previous catalog",
                    severity="warning",
                    timeout=8,
                )
            except Exception:
                pass
        finally:
            self._prompt_catalog_rebuild_in_flight = False

        if snapshot is not None:
            self._apply_prompt_catalog_snapshot(snapshot)

        if self._prompt_catalog_rebuild_pending:
            pending_force = self._prompt_catalog_rebuild_pending_force
            pending_config_dirty = self._prompt_catalog_rebuild_pending_config_dirty
            self._prompt_catalog_rebuild_pending = False
            self._prompt_catalog_rebuild_pending_force = False
            self._prompt_catalog_rebuild_pending_config_dirty = False
            self._schedule_prompt_catalog_rebuild(
                reason="prompt_catalog_pending",
                force=pending_force,
                config_dirty=pending_config_dirty,
            )

    def _request_prompt_catalog_config_refresh(
        self: Any,
        *,
        reason: str,
    ) -> None:
        """Invalidate in-flight work and request a fresh config-backed build."""
        self._prompt_catalog_generation += 1
        self._invalidate_prompt_glossary_catalogs(reason=reason)
        self._schedule_prompt_catalog_rebuild(
            reason=reason,
            force=True,
            config_dirty=True,
        )

    def _apply_prompt_catalog_snapshot(
        self: Any,
        snapshot: PromptCatalogSnapshot,
    ) -> None:
        """Publish a freshly-built prompt catalog snapshot."""
        if snapshot.generation != self._prompt_catalog_generation:
            return
        for trigger, template in tuple(self._pending_snippet_saves.items()):
            if snapshot.user_snippets.get(trigger) == template:
                self._pending_snippet_saves.pop(trigger, None)
        self._prompt_catalog = snapshot
        self._prompt_catalog_assist_entries_cache = {}
        self._user_snippets = dict(snapshot.user_snippets)
        self._snippets_cache = dict(snapshot.snippets)
        self._refresh_visible_prompt_catalog_surfaces()

    def _refresh_visible_prompt_catalog_surfaces(self: Any) -> None:
        """Refresh currently-mounted prompt completion/hint surfaces."""
        try:
            from ..widgets.prompt_text_area import PromptTextArea

            text_areas = list(self.query(PromptTextArea))
        except Exception:
            return
        for text_area in text_areas:
            if not getattr(text_area, "is_mounted", False):
                continue
            try:
                completion_kind = str(getattr(text_area, "_completion_kind", ""))
                invalidate_artifact_refs = getattr(
                    text_area,
                    "invalidate_artifact_ref_completion_cache",
                    None,
                )
                if callable(invalidate_artifact_refs):
                    invalidate_artifact_refs()
                if (
                    getattr(text_area, "_file_completion_active", False)
                    and completion_kind.startswith("xprompt")
                    and completion_kind != "xprompt_arg_ref"
                ):
                    text_area._refresh_file_completion_from_cursor()
                if getattr(text_area, "_active_xprompt_arg_hint", None) is not None:
                    text_area._refresh_xprompt_arg_hint_from_cursor()
                if "/" in text_area.text:
                    text_area._build_highlight_map()
                    text_area.refresh()
                text_area._on_prompt_completion_context_changed()
            except Exception:
                log.debug("Failed to refresh prompt catalog surface", exc_info=True)
