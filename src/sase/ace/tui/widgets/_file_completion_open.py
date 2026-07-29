"""Open and build manual prompt completion menus."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._file_completion_tab import FileCompletionTabMixin
from sase.ace.tui.widgets._file_completion_xprompt_args import (
    build_xprompt_arg_completion_candidates,
)
from sase.ace.tui.widgets.directive_completion import (
    build_directive_arg_completion_candidates,
    build_directive_completion_candidates,
    is_directive_like_token,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    at_reference_leading_match_count,
)
from sase.ace.tui.widgets.file_completion import (
    build_file_history_completion_candidates,
)
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
    PlaceholderCompletionResult,
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
    build_loading_placeholder,
    vcs_repo_completion_candidates,
)
from sase.xprompt.vcs_repo_completion import peek_cached_repo_candidates

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings


class FileCompletionOpenMixin(FileCompletionTabMixin):
    """Mixin providing completion menu open/build behavior."""

    if TYPE_CHECKING:

        def _placeholder_completion_at_cursor(
            self,
            *,
            include_common_when_prefix_empty: bool = False,
        ) -> PlaceholderCompletionResult | None: ...
        def _prompt_completion_settings(self) -> PromptCompletionSettings: ...

    def _try_auto_placeholder_completion(self) -> bool:
        """Open placeholder completion when automatic completion is enabled.

        Automatic opens keep the saved group out of a bare ``<`` so a stray
        less-than in prose or code never pops a menu of unrelated tags.
        """
        if self._prompt_completion_settings().auto == "off":
            return False
        result = self._placeholder_completion_at_cursor(
            include_common_when_prefix_empty=False,
        )
        if result is None:
            if (
                self._file_completion_active
                and self._completion_kind == PLACEHOLDER_COMPLETION_KIND
            ):
                self._clear_file_completion()
            return False
        self._open_placeholder_completion(result, trigger="auto")
        return True

    def _open_placeholder_completion(
        self,
        result: PlaceholderCompletionResult,
        *,
        trigger: str = "auto",
    ) -> None:
        """Populate the shared hard-popup state from a placeholder result."""
        self._completion_kind = PLACEHOLDER_COMPLETION_KIND
        self._placeholder_completion_trigger = trigger
        self._file_completion_active = True
        self._file_completion_candidates = result.candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(result.prefix)

    def _try_vcs_project_completion(self) -> bool:
        """Open the ``+`` project completion menu at a valid ``+query`` token.

        Returns ``True`` when a ``+`` trigger is present (menu opened,
        empty-state row shown, or query matched nothing and the menu was
        dismissed), so the caller stops dispatching other completion kinds.
        Returns ``False`` only when there is no ``+`` trigger or the bar is not
        in prompt mode.
        """
        bar = self._find_prompt_bar()
        if bar is not None and getattr(bar, "_mode", "prompt") != "prompt":
            return False
        trigger = self._get_vcs_project_trigger()
        if trigger is None:
            return False

        candidates, catalog_empty = vcs_project_completion_candidates(trigger.query)
        if catalog_empty:
            candidates = [build_no_active_projects_placeholder()]
        elif not candidates:
            self._clear_file_completion()
            return True

        self._completion_kind = VCS_PROJECT_COMPLETION_KIND
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(trigger.query)
        return True

    def _try_vcs_repo_completion(self) -> bool:
        """Open the repository completion menu inside a VCS workflow ref."""
        bar = self._find_prompt_bar()
        if bar is not None and getattr(bar, "_mode", "prompt") != "prompt":
            return False
        trigger = self._get_vcs_repo_trigger()
        if trigger is None:
            return False

        key = (trigger.workflow, trigger.namespace)
        result = peek_cached_repo_candidates(trigger.workflow, trigger.namespace)
        if result is None:
            candidates = [build_loading_placeholder(trigger.namespace)]
            self._vcs_repo_completion_key = key
            self._vcs_repo_completion_result = None
            self._schedule_vcs_repo_completion_fetch(trigger)
        else:
            candidates, used_placeholder = vcs_repo_completion_candidates(
                result,
                trigger.query,
                trigger.namespace,
            )
            if not candidates and not used_placeholder:
                self._clear_file_completion()
                return True
            self._vcs_repo_completion_key = key
            self._vcs_repo_completion_result = result

        self._completion_kind = VCS_REPO_COMPLETION_KIND
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(trigger.query)
        return True

    def _try_vcs_ref_completion(self, *, force: bool = False) -> bool:
        """Open the VCS ref-root completion menu inside a workflow ref.

        Returns ``True`` whenever a ref-root trigger is present, even when
        candidate-gated auto-open stays silent, so lower-priority prompt
        reference menus do not take over known VCS refs.
        """
        bar = self._find_prompt_bar()
        if bar is not None and getattr(bar, "_mode", "prompt") != "prompt":
            return False
        trigger = self._get_vcs_ref_trigger()
        if trigger is None:
            return False

        candidates, source_empty, has_namespaces = vcs_ref_completion_candidates(
            trigger.workflow,
            trigger.query,
        )
        self._vcs_ref_completion_has_namespaces = has_namespaces
        if source_empty:
            if not force:
                self._clear_file_completion()
                return True
            candidates = [build_no_known_refs_placeholder()]
        elif not candidates:
            self._clear_file_completion()
            return True

        self._completion_kind = VCS_REF_COMPLETION_KIND
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(trigger.query)
        return True

    def _try_auto_prompt_reference_completion(self) -> bool:
        """Open the directive or xprompt/skill menu while typing a reference.

        Generalizes the prior ``#``-only automatic xprompt menu to also cover
        ``%`` directives and ``/`` skills. Each branch is gated by its own
        auto-menu setting, and the ``+`` project trigger keeps precedence.
        Returns ``True`` when a menu was opened.
        """
        bar = self._find_prompt_bar()
        if bar is not None and getattr(bar, "_mode", "prompt") != "prompt":
            return False
        if self._try_auto_placeholder_completion():
            return True
        if self._get_vcs_project_trigger() is not None:
            return False

        settings = self._prompt_completion_settings()
        if settings.auto_xprompt_menu and self._try_vcs_repo_completion():
            return True
        if settings.auto_xprompt_menu and self._try_vcs_ref_completion():
            return True
        if settings.auto_directive_menu:
            if self._try_auto_directive_arg_completion():
                return True
            if self._try_auto_directive_completion():
                return True
        if settings.auto_xprompt_menu:
            if self._try_auto_xprompt_arg_completion():
                return True
        if settings.auto_artifact_menu and self._try_artifact_ref_completion():
            return True
        if settings.auto_xprompt_menu:
            if self._try_auto_xprompt_completion():
                return True
        return False

    def _try_artifact_ref_completion(self, *, force: bool = False) -> bool:
        """Open shared ``@`` rows from warm artifact and path inventories."""
        bar = self._find_prompt_bar()
        if bar is not None and getattr(bar, "_mode", "prompt") != "prompt":
            return False
        context = self._get_artifact_ref_completion_context()
        if context is None:
            return False
        if context.stage == "kind" and context.path_directory is not None:
            directory_key = self._prompt_path_directory_key(context.path_directory)
            if self._prompt_path_completion_directory_key != directory_key:
                self._open_prompt_path_directory(context.path_directory)
        else:
            self._prompt_path_completion_directory_key = None
        if self._get_warm_artifact_ref_completion_catalog() is None:
            self._warm_current_artifact_ref_completion_catalog()

        result = self._artifact_ref_completion_result()
        if result is None:
            self._warm_current_artifact_ref_completion_catalog()
            if (
                self._file_completion_active
                and self._completion_kind == ARTIFACT_REF_COMPLETION_KIND
            ):
                self._clear_file_completion()
            return True
        if not result.candidates:
            self._clear_file_completion()
            return True

        self._completion_kind = ARTIFACT_REF_COMPLETION_KIND
        self._file_completion_active = True
        self._file_completion_candidates = result.candidates
        self._file_completion_index = 0
        self._completion_selection_moved = False
        self._artifact_ref_completion_force = force
        self._update_file_completion_panel(context.prefix)
        if force and at_reference_leading_match_count(result.candidates) == 1:
            self._accept_artifact_ref_completion(result.candidates[0])
        elif force and result.shared_extension:
            self._replace_absolute_range(
                context.query_start,
                context.query_end,
                f"{context.prefix}{result.shared_extension}",
            )
            self._try_artifact_ref_completion(force=True)
        return True

    def _try_auto_directive_arg_completion(self) -> bool:
        """Open fixed-value directive argument completion after ``:``."""
        ctx = self._get_directive_arg_token_context()
        if ctx is None:
            return False

        _row, _start, _end, directive_name, partial, selected_values = ctx
        candidates, _shared_extension = build_directive_arg_completion_candidates(
            directive_name,
            partial,
            agent_candidates=(
                self._snapshot_agent_completion_candidates()
                if directive_name == "wait"
                else None
            ),
            selected_values=selected_values,
        )
        if not candidates:
            if directive_name == "wait":
                self._agent_completion_candidates = None
            return False

        self._completion_kind = "directive_arg"
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(partial)
        return True

    def _try_auto_directive_completion(self) -> bool:
        """Open the directive completion menu while typing a ``%`` token.

        Unlike xprompt/slash completion, a directive-valid bare ``%`` opens the
        menu immediately; only invalid contexts (``word%``, ``50%``) and
        unknown directives stay quiet.
        """
        ctx = self._get_directive_token_context()
        if ctx is None:
            return False
        _row, _start, _end, token = ctx
        if not is_directive_like_token(token):
            return False

        candidates, _shared_extension = build_directive_completion_candidates(token)
        if not candidates:
            return False

        self._completion_kind = "directive"
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(token)
        return True

    def _try_auto_xprompt_arg_completion(self) -> bool:
        """Open agent-name completion inside an xprompt argument."""
        arg_ctx = self._get_xprompt_arg_completion_context()
        if arg_ctx is None or arg_ctx.completion_kind != "xprompt_arg_agent":
            return False

        candidates, _shared_extension = build_xprompt_arg_completion_candidates(
            arg_ctx,
            base_dir=self._prompt_completion_base_dir(),
            agent_candidates=self._snapshot_agent_completion_candidates(),
        )
        if not candidates:
            self._agent_completion_candidates = None
            return False

        self._completion_kind = arg_ctx.completion_kind
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(arg_ctx.token)
        return True

    def _try_auto_xprompt_completion(self) -> bool:
        """Open the xprompt completion menu while typing a ``#`` or ``/`` token."""
        bar = self._find_prompt_bar()
        if bar is not None and getattr(bar, "_mode", "prompt") != "prompt":
            return False
        if self._get_vcs_project_trigger() is not None:
            return False

        ctx = self._get_xprompt_token_context()
        if ctx is None:
            return False
        _row, span = ctx
        token = span.token
        # Bare ``#`` / ``/`` stay quiet; open only once an identifier follows.
        if len(token) < 2:
            return False

        result = self._build_warm_xprompt_completion_candidates(
            token,
            inline_reference_only=span.clamped,
        )
        if result is None:
            return False
        candidates, _shared_extension = result
        if not candidates:
            return False

        self._completion_kind = "xprompt"
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(token)
        return True

    def _try_file_history_completion(self) -> bool:
        """Show the file-reference history panel at an empty cursor prefix."""
        candidates, _shared = build_file_history_completion_candidates()
        if not candidates:
            self._clear_file_completion()
            return True

        self._completion_kind = "file_history"
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel("")
        return True
