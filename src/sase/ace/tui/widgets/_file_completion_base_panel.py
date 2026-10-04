"""Word and panel helpers for prompt completion."""

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
from sase.ace.tui.widgets.next_word_menu import NEXT_WORD_COMPLETION_KIND
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

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sase.ace.tui.widgets._snippets import SnippetExpansionPolicy
    from sase.artifact_refs import ArtifactRefContext
    from sase.ace.tui.agent_completion import AgentCompletionCandidate
    from sase.ace.tui.widgets.artifact_ref_completion import (
        ArtifactRefBugCandidate,
        ArtifactRefCompletionCatalog,
    )
    from sase.ace.tui.widgets.prompt_commit_inventory import PromptCommitSnapshot
    from sase.ace.tui.widgets.prompt_path_inventory import PromptPathSnapshot
    from sase.ace.tui.widgets.macro_arg_assist import (
        ActiveMacroArgHint,
        MacroAssistEntry,
    )
    from sase.ace.tui.widgets.placeholder_completion import (
        PlaceholderCompletionResult,
    )
    from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
    from sase.macro.vcs_ref_completion import VcsRefTrigger
    from sase.macro.vcs_repo_completion import VcsRepoFetchResult, VcsRepoTrigger


class FileCompletionBasePanelMixin(FileCompletionArtifactCandidatesMixin):
    """Mixin providing word results and completion panel sync."""

    # Shared completion-state contract for this mixin chain and its downstream
    # mixins; keep every declaration even when this file does not use it.
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
        _macro_arg_completion_trigger: str | None
        _agent_completion_candidates: list[AgentCompletionCandidate] | None
        _active_macro_arg_hint: ActiveMacroArgHint | None
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
        _finalizer_inventory: tuple[dict[str, object], ...] | None
        _finalizer_available: bool
        _finalizer_inflight: bool
        _machine_inventory: tuple[dict[str, str], ...] | None
        _machine_available: bool
        _machine_inflight: bool
        _model_completion_catalog_loaded: bool
        _model_completion_catalog_available: bool
        _model_completion_catalog_inflight: bool
        _model_completion_catalog_request: tuple[str, str | None, str, int, str] | None
        _vim_mode: str
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
        def _clear_macro_arg_hint(self) -> None: ...
        def _get_vcs_ref_trigger(self) -> VcsRefTrigger | None: ...
        def _get_vcs_repo_trigger(self) -> VcsRepoTrigger | None: ...
        def _note_macro_completion_spacer(
            self,
            entry: MacroAssistEntry,
        ) -> None: ...
        def _show_macro_arg_hint(self, hint: ActiveMacroArgHint) -> None: ...
        def _get_macro_arg_assist_entries(self) -> list[MacroAssistEntry]: ...
        def _get_warm_macro_arg_assist_entries(
            self,
        ) -> list[MacroAssistEntry] | None: ...
        def _macro_arg_assist_project_from_text(self) -> str | None: ...
        def _build_warm_macro_completion_candidates(
            self,
            token: str,
            *,
            inline_reference_only: bool = False,
        ) -> tuple[list[CompletionCandidate], str] | None: ...
        def _refresh_macro_arg_hint_from_cursor(self) -> None: ...
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
        def _schedule_finalizer_inventory_load(self) -> None: ...
        def _schedule_machine_inventory_load(self) -> None: ...
        def _schedule_model_completion_catalog_load(
            self,
            *,
            force: bool = False,
        ) -> None: ...
        def _prompt_app_or_none(self) -> object | None: ...
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
            session_policy: SnippetExpansionPolicy,
            variables: Mapping[str, str] | None = None,
        ) -> bool: ...

    def _prompt_word_completion_result(
        self,
        cursor_offset: int,
    ) -> WordCompletionResult | None:
        """Build prompt-local words with the configured shared threshold.

        Candidates the prediction model forecasts for the preceding words
        sort first and carry context evidence for the sequence signal; a
        cold or disabled model leaves the nearest-first order untouched.
        """
        from dataclasses import replace

        from sase.ace.tui.widgets._prompt_context_ranking import (
            apply_context_promotion,
        )

        result = build_prompt_word_completion_result(
            self.text,
            cursor_offset,
            min_length=self._prompt_completion_settings().word_min_length,
        )
        if result is None:
            return None
        ranked = self._rank_prefix_context(
            self.text[: result.replacement_start],
            result.prefix,
        )
        promoted = apply_context_promotion(result.candidates, ranked)
        if promoted is result.candidates:
            return result
        return replace(result, candidates=promoted)

    def _commit_word_completion(
        self,
        result: WordCompletionResult,
        insertion: str,
    ) -> None:
        """Replace the typed prefix, separating a preserved same-word suffix.

        Shared by prompt-local and history-word acceptance, for both the lone
        ``Ctrl+T`` shortcut and Ctrl+F/Ctrl+L menu acceptance, so committed
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

        if self._completion_kind != NEXT_WORD_COMPLETION_KIND:
            # Every other menu disarms the chain on open; the next-word menu
            # opens from the armed chain and every accept arms it again.
            try:
                clearer = getattr(self, "_clear_next_word_chain", None)
                if callable(clearer):
                    clearer()
            except Exception:
                pass

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

    def _clear_file_completion(self, *, clear_macro_arg_hint: bool = True) -> None:
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
        self._macro_arg_completion_trigger = None
        self._agent_completion_candidates = None
        self._vcs_repo_completion_key = None
        self._vcs_repo_completion_result = None
        self._vcs_ref_completion_has_namespaces = False
        self._prompt_path_completion_directory_key = None
        self._model_completion_catalog_request = None
        self._update_file_completion_panel("")
        if clear_macro_arg_hint:
            self._clear_macro_arg_hint()
