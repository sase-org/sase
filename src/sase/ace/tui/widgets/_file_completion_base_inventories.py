"""Inventory helpers for prompt completion."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets._file_completion_base_panel import (
    FileCompletionBasePanelMixin,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.model_alias_completion import (
    MODEL_ALIAS_COMPLETION_KIND,
    ModelAliasShortcutContext,
    build_loading_model_alias_placeholder,
    build_model_alias_completion_candidates,
    build_unavailable_model_alias_placeholder,
)
from sase.ace.tui.widgets.model_explicit_completion import (
    MODEL_EXPLICIT_COMPLETION_KIND,
    ModelExplicitShortcutContext,
    build_loading_model_explicit_placeholder,
    build_model_explicit_completion_candidates,
    build_unavailable_model_explicit_placeholder,
)
from sase.llm_provider.provider_priority_peek import peek_provider_routing_context
from sase.llm_provider.temporary_override import peek_active_alias_overrides
from sase.macro.model_completion import peek_cached_model_completion_catalog

if TYPE_CHECKING:
    from sase.ace.tui.agent_completion import AgentCompletionCandidate


class FileCompletionBaseInventoriesMixin(FileCompletionBasePanelMixin):
    """Mixin providing directive-argument and catalog inventory state."""

    def _snapshot_agent_completion_candidates(self) -> list[AgentCompletionCandidate]:
        """Return the per-menu visible-agent completion snapshot."""
        cached = self._agent_completion_candidates
        if cached is not None:
            return cached

        provider = getattr(self.app, "visible_agent_completion_candidates", None)
        if not callable(provider):
            self._agent_completion_candidates = []
            return self._agent_completion_candidates

        try:
            self._agent_completion_candidates = list(provider())
        except Exception:
            self._agent_completion_candidates = []
        return self._agent_completion_candidates

    def _build_live_directive_arg_candidates(
        self,
        clause: object,
    ) -> tuple[list[CompletionCandidate], str]:
        """Build directive-argument rows from warm snapshots and the shared core."""
        from sase.ace.tui.widgets.directive_completion import (
            BeadsState,
            DirectiveClauseCompletion,
            FinalizersState,
            MachinesState,
            build_directive_clause_candidates,
            clause_needs_agent_snapshot,
            clause_needs_bead_inventory,
            clause_needs_finalizer_inventory,
            clause_needs_machine_inventory,
        )
        from sase.ace.tui.widgets.file_completion import build_completion_candidates

        if not isinstance(clause, DirectiveClauseCompletion):
            return [], ""

        if clause_needs_bead_inventory(clause):
            self._ensure_wait_bead_inventory()
        if clause_needs_finalizer_inventory(clause):
            self._ensure_finalizer_inventory()
        if clause_needs_machine_inventory(clause):
            self._ensure_machine_inventory()
        raw_state, bead_inventory = self._wait_bead_inventory_state()
        beads_state: BeadsState
        if raw_state == "warm":
            beads_state = "warm"
        elif raw_state == "loading":
            beads_state = "loading"
        else:
            beads_state = "unavailable"
        finalizer_raw, finalizer_inventory = self._finalizer_inventory_state()
        finalizers_state: FinalizersState
        if finalizer_raw == "warm":
            finalizers_state = "warm"
        elif finalizer_raw == "loading":
            finalizers_state = "loading"
        else:
            finalizers_state = "unavailable"
        machine_raw, machine_inventory = self._machine_inventory_state()
        machines_state: MachinesState
        if machine_raw == "warm":
            machines_state = "warm"
        elif machine_raw == "loading":
            machines_state = "loading"
        else:
            machines_state = "unavailable"
        agent_candidates = (
            self._snapshot_agent_completion_candidates()
            if clause_needs_agent_snapshot(clause)
            else None
        )
        base_dir = self._prompt_completion_base_dir()

        def path_candidates(token: str) -> tuple[list[CompletionCandidate], str]:
            path_token = token if token else "./"
            return build_completion_candidates(path_token, base_dir=base_dir)

        return build_directive_clause_candidates(
            clause,
            agent_candidates=agent_candidates,
            bead_inventory=bead_inventory,
            beads_state=beads_state,
            finalizer_inventory=finalizer_inventory,
            finalizers_state=finalizers_state,
            machine_inventory=machine_inventory,
            machines_state=machines_state,
            path_candidates=path_candidates,
        )

    def _wait_bead_project_key(self) -> str | None:
        """Return the project whose bead store should back directive completion."""
        project = self._xprompt_arg_assist_project_from_text()
        if isinstance(project, str) and project:
            return project
        ctx = getattr(self.app, "_prompt_context", None)
        if ctx is not None and not bool(getattr(ctx, "is_home_mode", False)):
            project_name = getattr(ctx, "project_name", None)
            if isinstance(project_name, str) and project_name:
                return project_name
        return None

    def _wait_bead_inventory_state(
        self,
    ) -> tuple[str, tuple[dict[str, str], ...] | None]:
        provider = getattr(self.app, "wait_bead_inventory", None)
        if callable(provider):
            provided = provider()
            if isinstance(provided, tuple) and len(provided) == 2:
                rows, available = provided
                if available:
                    return "warm", tuple(rows)
                return "unavailable", ()
        project = self._wait_bead_project_key()
        if self._wait_bead_inventory is not None and self._wait_bead_project == project:
            if self._wait_bead_available:
                return "warm", self._wait_bead_inventory
            return "unavailable", ()
        if not project:
            return "unavailable", ()
        return "loading", None

    def _ensure_wait_bead_inventory(self) -> None:
        """Warm the wait-bead inventory off the keystroke path."""
        if self._wait_bead_inventory_state()[0] != "loading":
            return
        project = self._wait_bead_project_key()
        if not project:
            self._wait_bead_inventory = ()
            self._wait_bead_available = False
            self._wait_bead_project = None
            return
        self._schedule_wait_bead_inventory_load(project)

    def _finalizer_inventory_state(
        self,
    ) -> tuple[str, tuple[dict[str, object], ...] | None]:
        provider = getattr(self._prompt_app_or_none(), "finalizer_inventory", None)
        if callable(provider):
            provided = provider()
            if isinstance(provided, tuple) and len(provided) == 2:
                rows, available = provided
                if available:
                    return "warm", tuple(rows)
                return "unavailable", ()
        if self._finalizer_inventory is not None:
            if self._finalizer_available:
                return "warm", self._finalizer_inventory
            return "unavailable", ()
        return "loading", None

    def _ensure_finalizer_inventory(self) -> None:
        """Warm the finalizer catalog off the keystroke path."""
        if callable(getattr(self._prompt_app_or_none(), "finalizer_inventory", None)):
            return
        if self._finalizer_inventory_state()[0] != "loading":
            return
        self._schedule_finalizer_inventory_load()

    def _machine_inventory_state(
        self,
    ) -> tuple[str, tuple[dict[str, str], ...] | None]:
        if self._machine_inventory is not None:
            if self._machine_available:
                return "warm", self._machine_inventory
            return "unavailable", ()
        return "loading", None

    def _ensure_machine_inventory(self) -> None:
        """Warm the dispatch-machine catalog off the keystroke path."""
        if self._machine_inventory_state()[0] != "loading":
            return
        self._schedule_machine_inventory_load()

    def _model_completion_catalog_state(
        self,
    ) -> tuple[str, tuple[Any, ...] | None]:
        """Return the model catalog state without building on the UI thread."""
        provider = getattr(self._prompt_app_or_none(), "model_completion_catalog", None)
        if callable(provider):
            try:
                provided = provider()
            except Exception:
                return "unavailable", ()
            if isinstance(provided, tuple) and len(provided) == 2:
                rows, available = provided
                if rows is None:
                    return "loading", None
                if available:
                    return "warm", tuple(rows)
                return "unavailable", ()

        cached = peek_cached_model_completion_catalog(
            overrides=peek_active_alias_overrides(),
            routing_context=peek_provider_routing_context(),
        )
        if cached is not None:
            return "warm", tuple(cached)
        if (
            self._model_completion_catalog_loaded
            and not self._model_completion_catalog_available
        ):
            return "unavailable", ()
        return "loading", None

    def _model_alias_completion_rows(
        self,
        context: ModelAliasShortcutContext,
        *,
        retry_unavailable: bool = False,
    ) -> list[CompletionCandidate]:
        """Build shortcut rows, scheduling a cold catalog load when needed."""
        state, entries = self._model_completion_catalog_state()
        if state == "warm" and entries is not None:
            return build_model_alias_completion_candidates(context, entries)
        if state == "unavailable" and retry_unavailable:
            self._remember_model_completion_catalog_request(MODEL_ALIAS_COMPLETION_KIND)
            self._schedule_model_completion_catalog_load(force=True)
            return [build_loading_model_alias_placeholder()]
        if state == "loading":
            self._remember_model_completion_catalog_request(MODEL_ALIAS_COMPLETION_KIND)
            self._schedule_model_completion_catalog_load()
            return [build_loading_model_alias_placeholder()]
        return [build_unavailable_model_alias_placeholder()]

    def _model_explicit_completion_rows(
        self,
        context: ModelExplicitShortcutContext,
        *,
        retry_unavailable: bool = False,
    ) -> list[CompletionCandidate]:
        """Build shortcut rows, scheduling a cold catalog load when needed."""
        state, entries = self._model_completion_catalog_state()
        if state == "warm" and entries is not None:
            return build_model_explicit_completion_candidates(context, entries)
        if state == "unavailable" and retry_unavailable:
            self._remember_model_completion_catalog_request(
                MODEL_EXPLICIT_COMPLETION_KIND
            )
            self._schedule_model_completion_catalog_load(force=True)
            return [build_loading_model_explicit_placeholder()]
        if state == "loading":
            self._remember_model_completion_catalog_request(
                MODEL_EXPLICIT_COMPLETION_KIND
            )
            self._schedule_model_completion_catalog_load()
            return [build_loading_model_explicit_placeholder()]
        return [build_unavailable_model_explicit_placeholder()]

    def _remember_model_completion_catalog_request(
        self,
        completion_kind: str,
    ) -> None:
        """Record the prompt state that asked a worker to warm model rows."""
        self._model_completion_catalog_request = (
            completion_kind,
            self.id,
            self.text,
            self._absolute_offset(self.cursor_location),
            self._vim_mode,
        )
