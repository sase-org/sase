"""Kind-specific accept helpers for manual prompt completion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._directive_completion_types import (
    DirectiveCompletionMetadata,
)
from sase.ace.tui.widgets._file_completion_base import FileCompletionBaseMixin
from sase.ace.tui.widgets.artifact_ref_completion import (
    AtReferenceFileCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.model_alias_completion import (
    is_model_alias_completion_placeholder,
    plan_model_alias_completion_edit,
)
from sase.ace.tui.widgets.model_explicit_completion import (
    is_model_explicit_completion_placeholder,
    plan_model_explicit_completion_edit,
)
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    detect_xprompt_arg_hint_at_cursor,
    xprompt_completion_skeleton,
)
from sase.workspace_provider import VcsNamespaceEntry, VcsRepoEntry
from sase.xprompt.vcs_project_completion import (
    VcsProjectEntry,
    apply_vcs_project_selection,
)
from sase.xprompt.vcs_ref_completion import apply_vcs_ref_selection
from sase.xprompt.vcs_repo_completion import apply_vcs_repo_selection


class FileCompletionAcceptKindsMixin(FileCompletionBaseMixin):
    """Mixin providing kind-specific completion acceptance helpers."""

    if TYPE_CHECKING:

        def _try_vcs_repo_completion(self) -> bool: ...
        def _try_artifact_ref_completion(self, *, force: bool = False) -> bool: ...

    def _accept_vcs_project_completion(self, selected: CompletionCandidate) -> bool:
        """Apply the canonical expansion for the selected project candidate."""
        entry = selected.metadata
        if not isinstance(entry, VcsProjectEntry):
            # The empty project/PR placeholder is not selectable.
            self._clear_file_completion()
            return False
        trigger = self._get_vcs_project_trigger()
        if trigger is None:
            self._clear_file_completion()
            return False
        old_text = self.text
        new_text = apply_vcs_project_selection(
            old_text, trigger.span, entry.display_tag
        )
        self._replace_absolute_range(0, len(old_text), new_text)
        self._clear_file_completion()
        return True

    def _accept_vcs_repo_completion(self, selected: CompletionCandidate) -> bool:
        """Apply the canonical expansion for the selected repository."""
        entry = selected.metadata
        if not isinstance(entry, VcsRepoEntry):
            self._clear_file_completion()
            return False
        trigger = self._get_vcs_repo_trigger()
        if trigger is None:
            self._clear_file_completion()
            return False
        old_text = self.text
        new_text = apply_vcs_repo_selection(old_text, trigger, entry.ref)
        self._replace_absolute_range(0, len(old_text), new_text)
        self._clear_file_completion()
        return True

    def _accept_vcs_ref_completion(self, selected: CompletionCandidate) -> bool:
        """Apply the canonical token-local expansion for a VCS ref-root row."""
        metadata = selected.metadata
        if isinstance(metadata, VcsProjectEntry):
            selected_ref = metadata.name
            chain = False
        elif isinstance(metadata, VcsNamespaceEntry):
            selected_ref = metadata.name.rstrip("/") + "/"
            chain = True
        else:
            # The empty ref placeholder is not selectable.
            self._clear_file_completion()
            return False

        trigger = self._get_vcs_ref_trigger()
        if trigger is None:
            self._clear_file_completion()
            return False

        old_text = self.text
        new_text = apply_vcs_ref_selection(
            old_text,
            trigger,
            selected_ref,
            chain=chain,
        )
        cursor_offset = _vcs_ref_accept_cursor_offset(
            old_text,
            trigger.value_span[0],
            trigger.value_span[1],
            selected_ref,
            separator=trigger.separator,
            chain=chain,
        )
        self._replace_absolute_range(0, len(old_text), new_text)
        self.cursor_location = self._location_from_absolute(cursor_offset)

        self._clear_file_completion()
        if chain and not self._try_vcs_repo_completion():
            self._clear_file_completion()
        return True

    def _accept_xprompt_completion_candidate(
        self,
        selected: CompletionCandidate,
        row: int,
        start: int,
        end: int,
    ) -> bool:
        """Accept an xprompt candidate using its completion skeleton when eligible."""
        if not isinstance(selected.metadata, XPromptAssistEntry):
            return False
        if not selected.insertion.startswith("#"):
            return False

        # A required-text ``::`` skeleton becomes ``:: `` only when the accepted
        # token ends the line; an inline accept keeps ``::`` so the following text
        # supplies the single delimiter instead of doubling the space.
        line = self.document.get_line(row)
        append_text_arg_space = end == len(line)
        next_char = line[end] if end < len(line) else None
        expanded = self._expand_snippet_template_at_range(
            xprompt_completion_skeleton(
                selected.metadata,
                append_text_arg_space=append_text_arg_space,
                next_char=next_char,
            ),
            (row, start),
            (row, end),
            session_policy="nest",
        )
        if expanded:
            self._note_xprompt_completion_spacer(selected.metadata)
        return expanded

    def _accept_directive_completion_candidate(
        self,
        selected: CompletionCandidate,
        row: int,
        start: int,
        end: int,
    ) -> bool:
        """Accept a directive template row through the snippet engine."""
        metadata = selected.metadata
        if not isinstance(metadata, DirectiveCompletionMetadata):
            return False
        if not metadata.is_snippet or not metadata.template:
            return False
        return self._expand_snippet_template_at_range(
            metadata.template,
            (row, start),
            (row, end),
            session_policy="nest",
        )

    def _refresh_xprompt_completion_skeleton_hint(
        self,
        selected: CompletionCandidate,
    ) -> None:
        """Refresh argument hints from the just-accepted xprompt metadata."""
        if not isinstance(selected.metadata, XPromptAssistEntry):
            self._clear_xprompt_arg_hint()
            return
        cursor_offset = self._absolute_offset(self.cursor_location)
        hint = detect_xprompt_arg_hint_at_cursor(
            self.text,
            cursor_offset,
            [selected.metadata],
        )
        if hint is None:
            self._clear_xprompt_arg_hint()
            return
        self._active_xprompt_arg_hint = hint
        self._show_xprompt_arg_hint(hint)

    def _accept_model_alias_completion(self, selected: CompletionCandidate) -> bool:
        """Accept a ``=alias`` shortcut candidate using the Rust edit plan."""
        if is_model_alias_completion_placeholder(selected):
            return False
        context = self._get_model_alias_completion_context()
        state, entries = self._model_completion_catalog_state()
        if context is None or state != "warm" or entries is None:
            self._clear_file_completion()
            return False
        candidates = self._model_alias_completion_rows(context)
        if selected.insertion not in {candidate.insertion for candidate in candidates}:
            self._clear_file_completion()
            return False
        planned = plan_model_alias_completion_edit(
            self.text,
            self.cursor_location,
            entries,
            selected,
        )
        if planned is None:
            self._clear_file_completion()
            return False
        start = self._location_from_absolute(planned.replacement_start)
        end = self._location_from_absolute(planned.replacement_end)
        self._replace_via_keyboard(planned.replacement, start, end)
        self.cursor_location = self._location_from_absolute(planned.caret_offset)
        self._clear_file_completion()
        return True

    def _accept_model_explicit_completion(
        self,
        selected: CompletionCandidate,
    ) -> bool:
        """Accept a ``==model`` shortcut candidate using the Rust edit plan."""
        if is_model_explicit_completion_placeholder(selected):
            return False
        context = self._get_model_explicit_completion_context()
        state, entries = self._model_completion_catalog_state()
        if context is None or state != "warm" or entries is None:
            self._clear_file_completion()
            return False
        candidates = self._model_explicit_completion_rows(context)
        if selected.insertion not in {candidate.insertion for candidate in candidates}:
            self._clear_file_completion()
            return False
        planned = plan_model_explicit_completion_edit(
            self.text,
            self.cursor_location,
            entries,
            selected,
        )
        if planned is None:
            self._clear_file_completion()
            return False
        start = self._location_from_absolute(planned.replacement_start)
        end = self._location_from_absolute(planned.replacement_end)
        self._replace_via_keyboard(planned.replacement, start, end)
        self.cursor_location = self._location_from_absolute(planned.caret_offset)
        self._clear_file_completion()
        return True

    def _accept_artifact_ref_completion(
        self,
        selected: CompletionCandidate,
    ) -> bool:
        """Accept a kind boundary or replace one complete payload context."""
        context = self._get_artifact_ref_completion_context()
        if context is None:
            self._clear_file_completion()
            return False
        if context.stage == "kind":
            metadata = selected.metadata
            if isinstance(metadata, AtReferenceFileCompletionMetadata):
                self._replace_absolute_range(
                    context.replacement_start,
                    context.replacement_end,
                    selected.insertion,
                )
                self._clear_file_completion()
                if metadata.is_dir:
                    self._try_artifact_ref_completion()
                return True
            if not isinstance(metadata, ArtifactRefKindCompletionMetadata):
                self._clear_file_completion()
                return False
            self._replace_absolute_range(
                context.replacement_start,
                context.replacement_end,
                selected.insertion,
            )
            self._clear_file_completion()
            self._try_artifact_ref_completion()
            return True

        metadata = selected.metadata
        if not isinstance(metadata, ArtifactRefPayloadCompletionMetadata):
            self._clear_file_completion()
            return False
        result = self._artifact_ref_completion_result()
        if result is None or selected.insertion not in {
            candidate.insertion for candidate in result.candidates
        }:
            self._clear_file_completion()
            return False
        self._replace_absolute_range(
            context.replacement_start,
            context.replacement_end,
            selected.insertion,
        )
        self._clear_file_completion()
        return True


def _vcs_ref_accept_cursor_offset(
    prompt: str,
    value_start: int,
    value_end: int,
    selected_ref: str,
    *,
    separator: str,
    chain: bool,
) -> int:
    """Return cursor offset immediately after a VCS ref accept suffix."""
    if chain:
        return value_start + len(selected_ref)
    if separator == "(":
        return value_start + len(selected_ref) + 1
    suffix_length = 0 if prompt[value_end:].startswith(tuple(" \t\r\n")) else 1
    return value_start + len(selected_ref) + suffix_length
