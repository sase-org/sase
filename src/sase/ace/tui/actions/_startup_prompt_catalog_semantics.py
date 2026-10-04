"""Glossary/repo-mention catalogs and prompt surface refresh for ACE startup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ..glossary_catalog import PromptGlossaryContext
    from ..repo_mention_catalog import PromptRepoMentionContext
    from sase.macro.glossary_catalog import EditorGlossaryCatalog
    from sase.macro.repo_mention_catalog import EditorRepoMentionCatalog

log = logging.getLogger(__name__)


def _is_inert_spare_area(area: object) -> bool:
    """Return whether *area* sits inside an inert hidden prompt spare.

    A child of a ``display: none`` parent still reports ``display=True``,
    so callers cannot rely on the area's own display flag alone.
    """
    try:
        node = getattr(area, "_parent", None)
        while node is not None:
            if type(node).__name__ == "PromptInputBar" and bool(
                getattr(node, "_is_prompt_spare", False)
            ):
                return True
            node = getattr(node, "_parent", None)
    except Exception:  # noqa: BLE001 - spare check is best-effort.
        return False
    return False


class StartupPromptCatalogSemanticsMixin:
    """Mixin for glossary/repo-mention catalogs and surface refresh."""

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
    _prompt_repo_mention_generation: int
    _prompt_repo_mention_catalogs_by_context: dict[
        PromptRepoMentionContext,
        EditorRepoMentionCatalog | None,
    ]
    _prompt_repo_mention_diagnostics_by_context: dict[
        PromptRepoMentionContext,
        tuple[str, ...],
    ]
    _prompt_repo_mention_warming_contexts: set[PromptRepoMentionContext]
    _pending_selected_agent_semantic_refresh: bool

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
        self._refresh_visible_prompt_semantic_surfaces(context)

    def _invalidate_prompt_glossary_catalogs(self: Any, *, reason: str) -> None:
        """Drop warm glossary catalogs after config/project source changes."""
        del reason
        self._prompt_glossary_generation += 1
        self._prompt_glossary_catalogs_by_context = {}
        self._prompt_glossary_diagnostics_by_context = {}
        self._prompt_glossary_warming_contexts = set()
        self._refresh_visible_prompt_semantic_surfaces(global_change=True)

    def _refresh_visible_prompt_glossary_surfaces(
        self: Any,
        context: PromptGlossaryContext | None = None,
        *,
        global_change: bool = False,
    ) -> None:
        """Refresh mounted prompt panes that may show glossary spans."""
        self._refresh_visible_prompt_semantic_surfaces(
            context, global_change=global_change
        )

    def get_prompt_repo_mention_catalog(
        self: Any,
        context: PromptRepoMentionContext,
        *,
        schedule: bool = True,
    ) -> EditorRepoMentionCatalog | None:
        """Return the memory-only repo-mention catalog selected by *context*."""
        if context in self._prompt_repo_mention_catalogs_by_context:
            return self._prompt_repo_mention_catalogs_by_context[context]
        if schedule:
            self.warm_prompt_repo_mention_catalog(context)
        return None

    def is_prompt_repo_mention_catalog_warm(
        self: Any,
        context: PromptRepoMentionContext,
    ) -> bool:
        """Return whether *context* has a completed repo-mention lookup."""
        return context in self._prompt_repo_mention_catalogs_by_context

    def warm_prompt_repo_mention_catalog(
        self: Any,
        context: PromptRepoMentionContext,
    ) -> None:
        """Schedule an off-thread repo-mention warm for *context*."""
        if context in self._prompt_repo_mention_catalogs_by_context:
            return
        if context in self._prompt_repo_mention_warming_contexts:
            return
        self._prompt_repo_mention_warming_contexts.add(context)
        generation = self._prompt_repo_mention_generation

        async def run_warm() -> None:
            await self._run_prompt_repo_mention_warm(context, generation)

        try:
            self.run_worker(
                cast(Any, run_warm),
                name=f"prompt-repo-mentions:{generation}:{hash(context)}",
                group="prompt-repo-mentions",
                exclusive=False,
            )
        except Exception:
            self._prompt_repo_mention_warming_contexts.discard(context)
            log.exception("Failed to schedule prompt repo-mention warm")

    async def _run_prompt_repo_mention_warm(
        self: Any,
        context: PromptRepoMentionContext,
        generation: int,
    ) -> None:
        """Load one repo-mention context off-thread and publish it if current."""
        import asyncio

        from ..repo_mention_catalog import load_prompt_repo_mention_context

        try:
            result = await asyncio.to_thread(
                load_prompt_repo_mention_context,
                context,
                generation=generation,
            )
        except Exception:
            log.exception("Prompt repo-mention warm failed")
            if generation == self._prompt_repo_mention_generation:
                self._prompt_repo_mention_catalogs_by_context[context] = None
                self._prompt_repo_mention_diagnostics_by_context[context] = (
                    "prompt repo-mention warm failed",
                )
            return
        finally:
            self._prompt_repo_mention_warming_contexts.discard(context)

        if result.generation != self._prompt_repo_mention_generation:
            return
        self._prompt_repo_mention_catalogs_by_context[context] = result.catalog
        self._prompt_repo_mention_diagnostics_by_context[context] = result.diagnostics
        self._refresh_visible_prompt_semantic_surfaces(context)

    def _invalidate_prompt_repo_mention_catalogs(self: Any, *, reason: str) -> None:
        """Drop warm repo-mention catalogs after config/project source changes."""
        del reason
        self._prompt_repo_mention_generation += 1
        self._prompt_repo_mention_catalogs_by_context = {}
        self._prompt_repo_mention_diagnostics_by_context = {}
        self._prompt_repo_mention_warming_contexts = set()
        self._refresh_visible_prompt_semantic_surfaces(global_change=True)

    def _refresh_visible_prompt_repo_mention_surfaces(
        self: Any,
        context: PromptRepoMentionContext | None = None,
        *,
        global_change: bool = False,
    ) -> None:
        """Refresh mounted prompt panes that may show repo-mention spans."""
        self._refresh_visible_prompt_semantic_surfaces(
            context, global_change=global_change
        )

    def _refresh_visible_prompt_semantic_surfaces(
        self: Any,
        context: PromptGlossaryContext | PromptRepoMentionContext | None = None,
        *,
        global_change: bool = False,
    ) -> None:
        """Refresh prompt-input overlays and the selected Agents detail."""
        try:
            from ..widgets.prompt_text_area import PromptTextArea

            text_areas = list(self.query(PromptTextArea))
        except Exception:
            text_areas = []
        for text_area in text_areas:
            if not getattr(text_area, "is_mounted", False):
                continue
            if not getattr(text_area, "display", True):
                continue
            if not getattr(text_area, "visible", True):
                continue
            if _is_inert_spare_area(text_area):
                continue
            try:
                text_area._build_highlight_map()
                text_area.refresh()
            except Exception:
                log.debug("Failed to refresh prompt semantic surface", exc_info=True)
        self._schedule_selected_agent_semantic_refresh(
            context, global_change=global_change
        )

    def _semantic_context_matches_selected_agent(self: Any, context: Any) -> bool:
        """Return True when *context* can affect the selected Agents detail.

        The comparison mirrors the ``(project, workspace)`` derivation in
        ``agent_prompt_highlight_context``: a warm for another context cannot
        change what the detail shows for the selected agent. Hosts without a
        selected-agent accessor keep the legacy always-repaint behavior, and
        an empty selection never needs a context-scoped repaint.
        """
        get_selected = getattr(self, "_get_selected_agent", None)
        if not callable(get_selected):
            return True
        try:
            agent = get_selected()
        except Exception:
            return True
        if agent is None:
            return False
        try:
            project_ref = getattr(context, "project_ref", None)
            launch_workspace = getattr(context, "launch_workspace", None)
        except Exception:
            return True
        agent_project: str | None = None
        try:
            project_file = getattr(agent, "project_file", None)
            if isinstance(project_file, str) and project_file:
                from pathlib import Path

                agent_project = Path(project_file).parent.name or None
        except Exception:
            agent_project = None
        agent_workspace: str | None = None
        try:
            workspace_dir = getattr(agent, "workspace_dir", None)
            if isinstance(workspace_dir, str) and workspace_dir:
                agent_workspace = workspace_dir
        except Exception:
            agent_workspace = None
        return project_ref == agent_project and launch_workspace == agent_workspace

    def _schedule_selected_agent_semantic_refresh(
        self: Any,
        context: PromptGlossaryContext | PromptRepoMentionContext | None = None,
        *,
        global_change: bool = False,
    ) -> None:
        """Repaint the selected Agents detail through the shared debouncer.

        Phase ``post-open-quiet``: a context-scoped warm repaints only when
        its context matches the selected agent. While a prompt is active the
        repaint is deferred instead, and ``_detach_prompt_bar`` flushes it
        once on dismissal. A missing context (or ``global_change``) keeps the
        legacy always-repaint behavior.
        """
        if getattr(self, "current_tab", None) != "agents":
            return
        prompt_active = getattr(self, "_prompt_input_active", None)
        try:
            active = bool(prompt_active()) if callable(prompt_active) else False
        except Exception:
            active = False
        if active:
            try:
                self._pending_selected_agent_semantic_refresh = True
            except Exception:
                log.debug(
                    "Failed to record pending agent semantic refresh", exc_info=True
                )
            return
        if not global_change and context is not None:
            try:
                matches = self._semantic_context_matches_selected_agent(context)
            except Exception:
                matches = True
            if not matches:
                return
        refresh = getattr(self, "_refresh_agent_focus_detail", None)
        if callable(refresh):
            refresh(render_immediate=False)

    def _flush_pending_selected_agent_semantic_refresh(self: Any) -> None:
        """Repaint once after dismissal if warms landed while prompted.

        Called from the prompt-bar detach path; coalesces every deferred
        repaint into a single debounced detail refresh.
        """
        try:
            pending = bool(
                getattr(self, "_pending_selected_agent_semantic_refresh", False)
            )
        except Exception:
            return
        if not pending:
            return
        try:
            self._pending_selected_agent_semantic_refresh = False
        except Exception:
            pass
        if getattr(self, "current_tab", None) != "agents":
            return
        refresh = getattr(self, "_refresh_agent_focus_detail", None)
        if callable(refresh):
            try:
                refresh(render_immediate=False)
            except Exception:
                log.debug(
                    "Failed to flush pending agent semantic refresh", exc_info=True
                )

    def _refresh_visible_prompt_catalog_surfaces(self: Any) -> None:
        """Refresh currently-mounted prompt completion/hint surfaces."""
        try:
            from ..widgets.prompt_text_area import PromptTextArea

            text_areas = list(self.query(PromptTextArea))
        except Exception:
            text_areas = []
        for text_area in text_areas:
            if not getattr(text_area, "is_mounted", False):
                continue
            if not getattr(text_area, "display", True):
                continue
            if not getattr(text_area, "visible", True):
                continue
            if _is_inert_spare_area(text_area):
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
                if getattr(
                    text_area, "_file_completion_active", False
                ) and completion_kind.startswith(("macro", "macro_arg_")):
                    text_area._refresh_file_completion_from_cursor()
                if getattr(text_area, "_active_macro_arg_hint", None) is not None:
                    text_area._refresh_macro_arg_hint_from_cursor()
                if "/" in text_area.text:
                    text_area._build_highlight_map()
                    text_area.refresh()
                text_area._on_prompt_completion_context_changed()
            except Exception:
                log.debug("Failed to refresh prompt catalog surface", exc_info=True)
        self._schedule_selected_agent_semantic_refresh(global_change=True)
