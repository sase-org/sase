"""Refresh active prompt file completions after cursor or text changes."""

from __future__ import annotations

from sase.ace.tui.widgets._file_completion_accept import FileCompletionAcceptMixin
from sase.ace.tui.widgets._file_completion_xprompt_args import (
    build_xprompt_arg_completion_candidates,
)
from sase.ace.tui.widgets.directive_completion import (
    build_directive_arg_completion_candidates,
    build_directive_completion_candidates,
)
from sase.ace.tui.widgets.file_completion import build_completion_candidates
from sase.ace.tui.widgets.jinja_completion import build_jinja_completion_result
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
)
from sase.ace.tui.widgets.vcs_project_completion import (
    VCS_PROJECT_COMPLETION_KIND,
    build_no_active_projects_placeholder,
    vcs_project_completion_candidates,
)
from sase.ace.tui.widgets.vcs_ref_completion import (
    VCS_REF_COMPLETION_KIND,
    build_no_known_refs_placeholder,
    vcs_ref_completion_candidates,
)
from sase.ace.tui.widgets.vcs_repo_completion import (
    VCS_REPO_COMPLETION_KIND,
    vcs_repo_completion_candidates,
)


class FileCompletionRefreshMixin(FileCompletionAcceptMixin):
    """Mixin providing active completion refresh behavior."""

    def _refresh_file_completion_from_cursor(self) -> None:
        """Recompute active completions after edits or cursor movement."""
        if not self._file_completion_active:
            return

        if self._completion_kind == PLACEHOLDER_COMPLETION_KIND:
            placeholder_result = self._placeholder_completion_at_cursor()
            if placeholder_result is None:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].insertion
            self._file_completion_candidates = placeholder_result.candidates
            self._file_completion_index = min(
                self._file_completion_index,
                len(placeholder_result.candidates) - 1,
            )
            if previous is not None:
                for index, candidate in enumerate(placeholder_result.candidates):
                    if candidate.insertion == previous:
                        self._file_completion_index = index
                        break
            self._update_file_completion_panel(placeholder_result.prefix)
            return

        if self._completion_kind == "jinja":
            jinja_result = build_jinja_completion_result(
                self.text,
                self._absolute_offset(self.cursor_location),
            )
            if jinja_result is None or not jinja_result.candidates:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].insertion
            self._file_completion_candidates = jinja_result.candidates
            if previous is not None:
                for i, candidate in enumerate(jinja_result.candidates):
                    if candidate.insertion == previous:
                        self._file_completion_index = i
                        break
                else:
                    self._file_completion_index = min(
                        self._file_completion_index,
                        len(jinja_result.candidates) - 1,
                    )
            else:
                self._file_completion_index = min(
                    self._file_completion_index,
                    len(jinja_result.candidates) - 1,
                )
            self._update_file_completion_panel(jinja_result.prefix)
            return

        if self._completion_kind == VCS_PROJECT_COMPLETION_KIND:
            project_trigger = self._get_vcs_project_trigger()
            if project_trigger is None:
                self._clear_file_completion()
                return
            candidates, catalog_empty = vcs_project_completion_candidates(
                project_trigger.query
            )
            if catalog_empty:
                self._file_completion_candidates = [
                    build_no_active_projects_placeholder()
                ]
                self._file_completion_index = 0
                self._update_file_completion_panel(project_trigger.query)
                return
            if not candidates:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].name
            self._file_completion_candidates = candidates
            self._file_completion_index = 0
            if previous is not None:
                for i, candidate in enumerate(candidates):
                    if candidate.name == previous:
                        self._file_completion_index = i
                        break
            self._update_file_completion_panel(project_trigger.query)
            return

        if self._completion_kind == VCS_REF_COMPLETION_KIND:
            ref_trigger = self._get_vcs_ref_trigger()
            if ref_trigger is None:
                self._clear_file_completion()
                return
            candidates, source_empty, has_namespaces = vcs_ref_completion_candidates(
                ref_trigger.workflow,
                ref_trigger.query,
            )
            self._vcs_ref_completion_has_namespaces = has_namespaces
            if source_empty:
                self._file_completion_candidates = [build_no_known_refs_placeholder()]
                self._file_completion_index = 0
                self._update_file_completion_panel(ref_trigger.query)
                return
            if not candidates:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].name
            self._file_completion_candidates = candidates
            self._file_completion_index = 0
            if previous is not None:
                for i, candidate in enumerate(candidates):
                    if candidate.name == previous:
                        self._file_completion_index = i
                        break
            self._update_file_completion_panel(ref_trigger.query)
            return

        if self._completion_kind == VCS_REPO_COMPLETION_KIND:
            repo_trigger = self._get_vcs_repo_trigger()
            if repo_trigger is None:
                self._clear_file_completion()
                return
            repo_result = self._vcs_repo_completion_result
            if repo_result is None:
                self._update_file_completion_panel(repo_trigger.query)
                return
            candidates, used_placeholder = vcs_repo_completion_candidates(
                repo_result,
                repo_trigger.query,
                repo_trigger.namespace,
            )
            if not candidates and not used_placeholder:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].name
            self._file_completion_candidates = candidates
            self._file_completion_index = 0
            if previous is not None:
                for i, candidate in enumerate(candidates):
                    if candidate.name == previous:
                        self._file_completion_index = i
                        break
            self._update_file_completion_panel(repo_trigger.query)
            return

        # file_history mode has no active token - any edit that creates one
        # at the cursor dismisses. Cursor movement within whitespace is fine.
        if self._completion_kind == "file_history":
            if self._extract_token_around_cursor() is not None:
                self._clear_file_completion()
            return

        base_dir = self._prompt_completion_base_dir()
        previous = None
        if self._file_completion_candidates:
            previous = self._file_completion_candidates[
                self._file_completion_index
            ].insertion

        if self._completion_kind == "directive_arg":
            directive_arg_ctx = self._get_directive_arg_token_context()
            if directive_arg_ctx is None:
                self._clear_file_completion()
                return
            _row, _start, _end, directive_name, token = directive_arg_ctx
            candidates, _shared = build_directive_arg_completion_candidates(
                directive_name,
                token,
                agent_candidates=(
                    self._snapshot_agent_completion_candidates()
                    if directive_name == "wait"
                    else None
                ),
            )
        else:
            ctx = self._get_token_context()
            if ctx is None:
                self._clear_file_completion()
                return

            _row, _start, _end, token = ctx
            if self._completion_kind == "xprompt":
                candidates, _shared = self._build_xprompt_completion_candidates(token)
            elif self._completion_kind == "directive":
                candidates, _shared = build_directive_completion_candidates(token)
            elif self._completion_kind.startswith("xprompt_arg_"):
                arg_ctx = self._get_xprompt_arg_completion_context()
                if arg_ctx is None:
                    self._clear_file_completion()
                    return
                candidates, _shared = build_xprompt_arg_completion_candidates(
                    arg_ctx,
                    base_dir=base_dir,
                    agent_candidates=(
                        self._snapshot_agent_completion_candidates()
                        if arg_ctx.completion_kind == "xprompt_arg_agent"
                        else None
                    ),
                )
            else:
                candidates, _shared = build_completion_candidates(
                    token,
                    base_dir=base_dir,
                )
        if not candidates:
            self._clear_file_completion()
            return

        self._file_completion_candidates = candidates
        if previous is not None:
            for i, candidate in enumerate(candidates):
                if candidate.insertion == previous:
                    self._file_completion_index = i
                    break
            else:
                self._file_completion_index = min(
                    self._file_completion_index, len(candidates) - 1
                )
        else:
            self._file_completion_index = min(
                self._file_completion_index, len(candidates) - 1
            )

        self._update_file_completion_panel(token)
