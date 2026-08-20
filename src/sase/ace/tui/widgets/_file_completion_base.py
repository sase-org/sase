"""Shared state, panel, and candidate helpers for prompt completion."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets._file_completion_artifact_candidates import (
    FileCompletionArtifactCandidatesMixin,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    AtReferenceFileCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
    completion_scroll_offset,
)
from sase.ace.tui.widgets.prompt_word_completion import (
    WordCompletionResult,
    build_prompt_word_completion_result,
)
from sase.ace.tui.widgets.vcs_ref_completion import (
    VCS_REF_COMPLETION_KIND,
    vcs_ref_completion_title,
)
from sase.ace.tui.widgets.vcs_repo_completion import (
    VCS_REPO_COMPLETION_KIND,
    vcs_repo_completion_title,
)
from sase.xprompt.model_completion import build_model_completion_catalog
from sase.xprompt.vcs_project_completion import build_vcs_project_completion_entries

if TYPE_CHECKING:
    from sase.artifact_refs import ArtifactRefContext
    from sase.ace.tui.agent_completion import AgentCompletionCandidate
    from sase.ace.tui.widgets.artifact_ref_completion import (
        ArtifactRefBugCandidate,
        ArtifactRefCompletionCatalog,
    )
    from sase.ace.tui.widgets.prompt_commit_inventory import PromptCommitSnapshot
    from sase.ace.tui.widgets.prompt_path_inventory import PromptPathSnapshot
    from sase.ace.tui.widgets.xprompt_arg_assist import (
        ActiveXPromptArgHint,
        XPromptAssistEntry,
    )
    from sase.ace.tui.widgets.placeholder_completion import (
        PlaceholderCompletionResult,
    )
    from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
    from sase.xprompt.vcs_ref_completion import VcsRefTrigger
    from sase.xprompt.vcs_repo_completion import VcsRepoFetchResult, VcsRepoTrigger


class FileCompletionBaseMixin(FileCompletionArtifactCandidatesMixin):
    """Mixin providing shared completion state helpers."""

    if TYPE_CHECKING:
        _file_completion_candidates: list[CompletionCandidate]
        _file_completion_index: int
        _file_completion_active: bool
        _completion_kind: str
        _completion_selection_moved: bool
        _artifact_ref_completion_force: bool
        _artifact_ref_completion_stats: tuple[int, int, int]
        _artifact_ref_files_revealed: bool
        _artifact_ref_files_suppressed: bool
        # ``"auto"`` or ``"manual"``, recorded for the lifetime of an open
        # placeholder menu so refresh and accept keep resolving the same
        # candidate set the user is looking at.
        _placeholder_completion_trigger: str | None
        _agent_completion_candidates: list[AgentCompletionCandidate] | None
        _active_xprompt_arg_hint: ActiveXPromptArgHint | None
        _vcs_repo_completion_key: tuple[str, str] | None
        _vcs_repo_completion_result: VcsRepoFetchResult | None
        _vcs_repo_completion_inflight: set[tuple[str, str]]
        _vcs_ref_completion_has_namespaces: bool
        _prompt_path_snapshots: dict[str, PromptPathSnapshot]
        _prompt_path_inflight: set[str]
        _prompt_path_completion_directory_key: str | None
        _prompt_commit_snapshots: dict[str | None, PromptCommitSnapshot]
        _prompt_commit_inflight: set[str | None]
        _prompt_commit_worker_projects: dict[str, str | None]
        _wait_bead_inventory: tuple[dict[str, str], ...] | None
        _wait_bead_available: bool
        _wait_bead_project: str | None
        _wait_bead_inflight: set[str]
        _artifact_ref_bug_projection: (
            tuple[object, str | None, tuple[ArtifactRefBugCandidate, ...]] | None
        )

        def _find_prompt_bar(self) -> Any: ...
        def _prompt_completion_settings(self) -> PromptCompletionSettings: ...
        def _placeholder_completion_at_cursor(
            self,
            *,
            include_common_when_prefix_empty: bool = False,
        ) -> PlaceholderCompletionResult | None: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _get_vcs_ref_trigger(self) -> VcsRefTrigger | None: ...
        def _get_vcs_repo_trigger(self) -> VcsRepoTrigger | None: ...
        def _note_xprompt_completion_spacer(
            self,
            entry: XPromptAssistEntry,
        ) -> None: ...
        def _show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None: ...
        def _get_xprompt_arg_assist_entries(self) -> list[XPromptAssistEntry]: ...
        def _get_warm_xprompt_arg_assist_entries(
            self,
        ) -> list[XPromptAssistEntry] | None: ...
        def _xprompt_arg_assist_project_from_text(self) -> str | None: ...
        def _build_warm_xprompt_completion_candidates(
            self,
            token: str,
            *,
            inline_reference_only: bool = False,
        ) -> tuple[list[CompletionCandidate], str] | None: ...
        def _refresh_xprompt_arg_hint_from_cursor(self) -> None: ...
        def _refresh_history_word_completion(
            self,
            words: list[str] | None = None,
        ) -> None: ...
        def _refresh_file_completion_from_cursor(self) -> None: ...
        def _get_warm_artifact_ref_completion_catalog(
            self,
        ) -> ArtifactRefCompletionCatalog | None: ...
        def _get_warm_artifact_ref_known_kinds(self) -> frozenset[str] | None: ...
        def _get_warm_artifact_ref_context(self) -> ArtifactRefContext | None: ...
        def _warm_current_artifact_ref_completion_catalog(self) -> None: ...
        def _schedule_wait_bead_inventory_load(self, project_key: str) -> None: ...
        def _artifact_ref_sync_row(
            self,
            project: str | None,
            kind: str,
        ) -> CompletionCandidate | None: ...
        def _artifact_ref_sync_new_payloads(
            self,
            project: str | None,
            kind: str,
        ) -> frozenset[str]: ...
        def _expand_snippet_template_at_range(
            self,
            template: str,
            start: tuple[int, int],
            end: tuple[int, int],
            *,
            session_policy: str,
        ) -> bool: ...

    def _prompt_word_completion_result(
        self,
        cursor_offset: int,
    ) -> WordCompletionResult | None:
        """Build prompt-local words with the configured shared threshold."""
        return build_prompt_word_completion_result(
            self.text,
            cursor_offset,
            min_length=self._prompt_completion_settings().word_min_length,
        )

    def _commit_word_completion(
        self,
        result: WordCompletionResult,
        insertion: str,
    ) -> None:
        """Replace the typed prefix, separating a preserved same-word suffix.

        Shared by prompt-local and history-word acceptance, for both the lone
        ``Ctrl+T`` shortcut and Enter/Ctrl+L menu acceptance, so committed
        word insertion follows one unambiguous contract: only the typed
        prefix is replaced, and a single ASCII space is inserted before any
        identifier-like suffix that already followed the cursor, with the
        cursor left immediately after the completed word.
        """
        replacement = f"{insertion} " if result.has_word_suffix else insertion
        self._replace_absolute_range(
            result.replacement_start,
            result.replacement_end,
            replacement,
        )
        if result.has_word_suffix:
            self.cursor_location = self._location_from_absolute(
                result.replacement_start + len(insertion)
            )

    def _update_file_completion_panel(self, token: str) -> None:
        """Sync completion UI with the current completion state."""
        bar = self._find_prompt_bar()
        if bar is None:
            return

        if not self._file_completion_active or not self._file_completion_candidates:
            bar.hide_file_completions()
            return

        rows = self._file_completion_candidates
        group_rule = self._completion_group_rule_reserved()
        scroll_offset = completion_scroll_offset(
            len(rows),
            self._file_completion_index,
            group_rule=group_rule,
        )
        display_token = token
        group_directory = ""
        if self._completion_kind == VCS_REF_COMPLETION_KIND:
            ref_trigger = self._get_vcs_ref_trigger()
            if ref_trigger is not None:
                display_token = vcs_ref_completion_title(
                    ref_trigger.workflow,
                    has_namespaces=self._vcs_ref_completion_has_namespaces,
                )
        elif self._completion_kind == VCS_REPO_COMPLETION_KIND:
            repo_trigger = self._get_vcs_repo_trigger()
            if repo_trigger is not None:
                display_token = vcs_repo_completion_title(
                    self._vcs_repo_completion_result,
                    workflow=repo_trigger.workflow,
                    namespace=repo_trigger.namespace,
                )
        elif self._completion_kind == ARTIFACT_REF_COMPLETION_KIND:
            artifact_ctx = self._get_artifact_ref_completion_context()
            if artifact_ctx is not None:
                display_token = artifact_ctx.panel_title
                if artifact_ctx.stage == "kind":
                    group_directory = (
                        self._prompt_path_completion_directory_key
                        or self._prompt_path_directory_key(
                            artifact_ctx.path_directory or ""
                        )
                    )

        bar.show_file_completions(
            display_token,
            rows,
            self._file_completion_index,
            scroll_offset,
            completion_kind=self._completion_kind,
            group_rule=group_rule,
            group_directory=group_directory,
            artifact_ref_payload_count=self._artifact_ref_completion_stats[0],
            artifact_ref_payload_total=self._artifact_ref_completion_stats[1],
            artifact_ref_truncated_payloads=self._artifact_ref_completion_stats[2],
            artifact_ref_files_suppressed=self._artifact_ref_files_suppressed,
            word_ranking_signals=self._prompt_completion_settings().word_ranking_signals,
            placeholder_ranking_signals=(
                self._prompt_completion_settings().placeholder_ranking_signals
            ),
        )

    def _completion_group_rule_reserved(self) -> bool:
        """Return True when the panel draws a group rule for the active menu.

        The rule costs one of the panel's content lines, so the row budget has
        to know about it before any rows are windowed. Providers that render
        grouped menus identify themselves through their row metadata.
        """
        if self._completion_kind != ARTIFACT_REF_COMPLETION_KIND:
            return False
        has_artifacts = any(
            isinstance(candidate.metadata, ArtifactRefKindCompletionMetadata)
            for candidate in self._file_completion_candidates
        )
        has_files = any(
            isinstance(candidate.metadata, AtReferenceFileCompletionMetadata)
            for candidate in self._file_completion_candidates
        )
        return has_artifacts and has_files

    def _clear_file_completion(self, *, clear_xprompt_arg_hint: bool = True) -> None:
        """Reset manual completion state and hide its panel."""
        self._file_completion_active = False
        self._file_completion_candidates = []
        self._file_completion_index = 0
        self._completion_kind = "file"
        self._completion_selection_moved = False
        self._artifact_ref_completion_force = False
        self._artifact_ref_completion_stats = (0, 0, 0)
        self._artifact_ref_files_revealed = False
        self._artifact_ref_files_suppressed = False
        self._placeholder_completion_trigger = None
        self._agent_completion_candidates = None
        self._vcs_repo_completion_key = None
        self._vcs_repo_completion_result = None
        self._vcs_ref_completion_has_namespaces = False
        self._prompt_path_completion_directory_key = None
        self._update_file_completion_panel("")
        if clear_xprompt_arg_hint:
            self._clear_xprompt_arg_hint()

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
            build_directive_clause_candidates,
            clause_needs_agent_snapshot,
            clause_needs_bead_inventory,
        )
        from sase.ace.tui.widgets.file_completion import build_completion_candidates

        if not isinstance(clause, DirectiveClauseCompletion):
            return [], ""

        if clause_needs_bead_inventory(clause):
            self._ensure_wait_bead_inventory()
        raw_state, bead_inventory = self._wait_bead_inventory_state()
        beads_state: BeadsState
        if raw_state == "warm":
            beads_state = "warm"
        elif raw_state == "loading":
            beads_state = "loading"
        else:
            beads_state = "unavailable"
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

    def _placeholder_completion_includes_common_at_empty_prefix(self) -> bool:
        """Return the empty-prefix rule for the placeholder menu that is open.

        A stray ``<`` is common in prose and code, so an automatically opened
        menu stays exactly as quiet as it is today until a prefix character
        narrows the saved group.  An explicit ``Ctrl+T`` asked for the full
        list and gets it.
        """
        return self._placeholder_completion_trigger == "manual"

    def _warm_common_placeholder_cache(self) -> None:
        """Warm saved placeholders off the mount and keystroke paths."""
        warmer = getattr(self.app, "warm_common_placeholders", None)
        if callable(warmer):
            warmer()

    def _warm_history_word_completion_cache(self) -> None:
        """Warm prompt-history words off the mount and keystroke paths."""
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        if self._prompt_completion_settings().history_word_count <= 0:
            return
        self._schedule_history_word_completion_load()

    def _warm_vcs_project_completion_catalog(self) -> None:
        """Warm the ``+`` project catalog off the keystroke path.

        The catalog build touches disk (project enumeration + provider
        detection), so it must never run synchronously inside key handling
        (``sase/memory/tui_perf.md``). Building once in a background thread
        populates the module-level cache in
        :mod:`sase.xprompt.vcs_project_completion`, so the first valid ``+`` opens
        the menu instantly. Gated on the real app's completion-settings
        capability so lightweight test harnesses skip it.
        """
        if getattr(self, "_vcs_project_catalog_warmed", False):
            return
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        self._vcs_project_catalog_warmed = True
        self.run_worker(
            _warm_vcs_completion_catalogs,
            name="prompt-vcs-project-catalog",
            thread=True,
        )

    def _warm_prompt_path_inventory(self) -> None:
        """Warm the prompt's base directory off the keystroke path."""
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        directory_key = self._prompt_path_directory_key()
        snapshot = self._get_warm_prompt_path_snapshot(directory_key)
        self._schedule_prompt_path_inventory_load(directory_key, snapshot)

    def _warm_model_completion_catalog(self) -> None:
        """Warm the static ``%model`` catalog off the keystroke path."""
        if getattr(self, "_model_completion_catalog_warmed", False):
            return
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        self._model_completion_catalog_warmed = True
        self.run_worker(
            build_model_completion_catalog,
            name="prompt-model-catalog",
            thread=True,
        )


def _warm_vcs_completion_catalogs() -> None:
    """Warm VCS project and ref-root namespace completion caches."""
    build_vcs_project_completion_entries()

    from sase.workspace_provider import get_workflow_names
    from sase.xprompt.vcs_ref_completion import vcs_ref_namespaces_by_workflow

    vcs_ref_namespaces_by_workflow(get_workflow_names())
