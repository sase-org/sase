"""Open and build prompt file completion menus."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._file_completion_refresh import FileCompletionRefreshMixin
from sase.ace.tui.widgets._file_completion_xprompt_args import (
    build_xprompt_arg_completion_candidates,
    effective_xprompt_arg_token,
)
from sase.ace.tui.widgets.directive_completion import (
    build_directive_arg_completion_candidates,
    build_directive_completion_candidates,
    is_directive_like_token,
)
from sase.ace.tui.widgets.file_completion import (
    build_completion_candidates,
    build_file_history_completion_candidates,
    is_path_like_token,
)
from sase.ace.tui.widgets.jinja_completion import build_jinja_completion_result
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
from sase.ace.tui.widgets.xprompt_completion import is_xprompt_like_token

if TYPE_CHECKING:
    from sase.ace.tui.widgets.jinja_completion import JinjaCompletionResult
    from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
    from sase.ace.tui.widgets.xprompt_arg_assist import XPromptArgCompletionContext


class FileCompletionOpenMixin(FileCompletionRefreshMixin):
    """Mixin providing completion menu open/build behavior."""

    if TYPE_CHECKING:

        def _placeholder_completion_at_cursor(
            self,
        ) -> PlaceholderCompletionResult | None: ...
        def _prompt_completion_settings(self) -> PromptCompletionSettings: ...

    def _try_auto_placeholder_completion(self) -> bool:
        """Open placeholder completion when automatic completion is enabled."""
        if self._prompt_completion_settings().auto == "off":
            return False
        result = self._placeholder_completion_at_cursor()
        if result is None:
            if (
                self._file_completion_active
                and self._completion_kind == PLACEHOLDER_COMPLETION_KIND
            ):
                self._clear_file_completion()
            return False
        self._open_placeholder_completion(result)
        return True

    def _open_placeholder_completion(
        self,
        result: PlaceholderCompletionResult,
    ) -> None:
        """Populate the shared hard-popup state from a placeholder result."""
        self._completion_kind = PLACEHOLDER_COMPLETION_KIND
        self._file_completion_active = True
        self._file_completion_candidates = result.candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(result.prefix)

    def _try_vcs_project_completion(self) -> bool:
        """Open the ``#+`` project completion menu at a ``#+token``.

        Returns ``True`` when a ``#+`` trigger is present (menu opened,
        empty-state row shown, or query matched nothing and the menu was
        dismissed), so the caller stops dispatching other completion kinds.
        Returns ``False`` only when there is no ``#+`` trigger or the bar is not
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
        auto-menu setting, and the ``#+`` project trigger keeps precedence.
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
            if self._try_auto_xprompt_completion():
                return True
        return False

    def _try_auto_directive_arg_completion(self) -> bool:
        """Open fixed-value directive argument completion after ``:``."""
        ctx = self._get_directive_arg_token_context()
        if ctx is None:
            return False

        _row, _start, _end, directive_name, partial = ctx
        candidates, _shared_extension = build_directive_arg_completion_candidates(
            directive_name,
            partial,
            agent_candidates=(
                self._snapshot_agent_completion_candidates()
                if directive_name == "wait"
                else None
            ),
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
        _row, _start, _end, token = ctx
        # Bare ``#`` / ``/`` stay quiet; open only once an identifier follows.
        if len(token) < 2:
            return False
        if not is_xprompt_like_token(token):
            return False

        result = self._build_warm_xprompt_completion_candidates(token)
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

    def _try_file_completion_tab(self) -> bool:
        """Handle Ctrl+T-driven completion for path, xprompt, or history."""
        placeholder_result = self._placeholder_completion_at_cursor()
        if placeholder_result is not None:
            self._open_placeholder_completion(placeholder_result)
            if len(placeholder_result.candidates) == 1:
                self._accept_file_completion()
            return True
        if self._try_vcs_project_completion():
            return True
        if self._try_vcs_repo_completion():
            return True
        if self._try_vcs_ref_completion(force=True):
            return True

        cursor_offset = self._absolute_offset(self.cursor_location)
        jinja_result = build_jinja_completion_result(self.text, cursor_offset)
        if jinja_result is not None:
            return self._try_jinja_completion_tab(jinja_result)

        base_dir = self._prompt_completion_base_dir()
        directive_arg_ctx = self._get_directive_arg_token_context()
        if directive_arg_ctx is not None:
            self._completion_kind = "directive_arg"
            row, start, end, directive_name, token = directive_arg_ctx
            candidates, shared_extension = build_directive_arg_completion_candidates(
                directive_name,
                token,
                agent_candidates=(
                    self._snapshot_agent_completion_candidates()
                    if directive_name == "wait"
                    else None
                ),
            )
        else:
            arg_ctx = self._get_xprompt_arg_completion_context()
            if arg_ctx is not None:
                return self._try_xprompt_arg_completion_tab(arg_ctx)

            self._clear_xprompt_arg_hint()
            directive_ctx = self._get_directive_token_context()
            if directive_ctx is not None and is_directive_like_token(directive_ctx[3]):
                self._completion_kind = "directive"
                row, start, end, token = directive_ctx
                candidates, shared_extension = build_directive_completion_candidates(
                    token
                )
            else:
                token_info = self._extract_token_around_cursor()
                if token_info is None:
                    return self._try_file_history_completion()

                _start, _end, raw_token = token_info

                # Determine completion kind from the raw token.
                if is_xprompt_like_token(raw_token):
                    self._completion_kind = "xprompt"
                    ctx = self._get_xprompt_token_context()
                    if ctx is None:
                        self._clear_file_completion()
                        return False
                    row, start, end, token = ctx
                    candidates, shared_extension = (
                        self._build_xprompt_completion_candidates(token)
                    )
                elif is_path_like_token(raw_token):
                    self._completion_kind = "file"
                    ctx = self._get_path_token_context()
                    if ctx is None:
                        self._clear_file_completion()
                        return False
                    row, start, end, token = ctx
                    candidates, shared_extension = build_completion_candidates(
                        token,
                        base_dir=base_dir,
                    )
                else:
                    self._clear_file_completion()
                    return False

        if not candidates:
            self._clear_file_completion()
            return True

        if len(candidates) == 1:
            selected = candidates[0]
            accepted_kind = self._completion_kind
            used_xprompt_skeleton = (
                accepted_kind == "xprompt"
                and self._accept_xprompt_completion_candidate(selected, row, start, end)
            )
            if not used_xprompt_skeleton:
                self._replace_token_text(row, start, end, selected.insertion)
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            if accepted_kind == "xprompt":
                if used_xprompt_skeleton:
                    self._refresh_xprompt_completion_skeleton_hint(selected)
                else:
                    self._clear_xprompt_arg_hint()
            elif accepted_kind.startswith("xprompt_arg_"):
                self._refresh_xprompt_arg_hint_from_cursor()
            return True

        if shared_extension:
            next_token = f"{token}{shared_extension}"
            self._replace_token_text(row, start, end, next_token)
            ctx = self._get_token_context()
            if ctx is None:
                self._clear_file_completion()
                return True
            row, start, end, token = ctx
            if self._completion_kind == "xprompt":
                candidates, _ = self._build_xprompt_completion_candidates(token)
            elif self._completion_kind == "directive":
                candidates, _ = build_directive_completion_candidates(token)
            elif self._completion_kind == "directive_arg":
                directive_arg_ctx = self._get_directive_arg_token_context()
                if directive_arg_ctx is None:
                    self._clear_file_completion()
                    return True
                row, start, end, directive_name, token = directive_arg_ctx
                candidates, _ = build_directive_arg_completion_candidates(
                    directive_name,
                    token,
                    agent_candidates=(
                        self._snapshot_agent_completion_candidates()
                        if directive_name == "wait"
                        else None
                    ),
                )
            elif self._completion_kind.startswith("xprompt_arg_"):
                arg_ctx = self._get_xprompt_arg_completion_context()
                if arg_ctx is None:
                    self._clear_file_completion()
                    return True
                candidates, _ = build_xprompt_arg_completion_candidates(
                    arg_ctx,
                    base_dir=base_dir,
                    agent_candidates=(
                        self._snapshot_agent_completion_candidates()
                        if arg_ctx.completion_kind == "xprompt_arg_agent"
                        else None
                    ),
                )
            else:
                candidates, _ = build_completion_candidates(
                    token,
                    base_dir=base_dir,
                )
            if not candidates:
                self._clear_file_completion()
                return True

        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(token)
        return True

    def _try_jinja_completion_tab(self, result: JinjaCompletionResult) -> bool:
        """Handle Ctrl+T completion inside a Jinja2 tag."""
        jinja_result = result
        candidates = jinja_result.candidates
        self._completion_kind = "jinja"

        if not candidates:
            self._clear_file_completion()
            return True

        if len(candidates) == 1:
            selected = candidates[0]
            self._replace_absolute_range(
                jinja_result.replacement_start,
                jinja_result.replacement_end,
                selected.insertion,
            )
            self._clear_file_completion()
            return True

        if jinja_result.shared_extension:
            next_token = f"{jinja_result.prefix}{jinja_result.shared_extension}"
            self._replace_absolute_range(
                jinja_result.replacement_start,
                jinja_result.replacement_end,
                next_token,
            )
            refreshed = build_jinja_completion_result(
                self.text,
                self._absolute_offset(self.cursor_location),
            )
            if refreshed is None or not refreshed.candidates:
                self._clear_file_completion()
                return True
            jinja_result = refreshed
            candidates = refreshed.candidates

        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(jinja_result.prefix)
        return True

    def _try_xprompt_arg_completion_tab(
        self,
        ctx: XPromptArgCompletionContext,
    ) -> bool:
        """Handle Ctrl+T-driven completion inside xprompt argument syntax."""
        base_dir = self._prompt_completion_base_dir()
        candidates, shared_extension = build_xprompt_arg_completion_candidates(
            ctx,
            base_dir=base_dir,
            agent_candidates=(
                self._snapshot_agent_completion_candidates()
                if ctx.completion_kind == "xprompt_arg_agent"
                else None
            ),
        )
        self._completion_kind = ctx.completion_kind

        if not candidates:
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            self._refresh_xprompt_arg_hint_from_cursor()
            return True

        if len(candidates) == 1:
            selected = candidates[0]
            self._replace_absolute_range(
                ctx.value_start, ctx.value_end, selected.insertion
            )
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            self._refresh_xprompt_arg_hint_from_cursor()
            return True

        token = effective_xprompt_arg_token(ctx)
        if shared_extension:
            next_token = f"{token}{shared_extension}"
            self._replace_absolute_range(ctx.value_start, ctx.value_end, next_token)
            next_ctx = self._get_xprompt_arg_completion_context()
            if next_ctx is None:
                self._clear_file_completion(clear_xprompt_arg_hint=False)
                self._refresh_xprompt_arg_hint_from_cursor()
                return True
            candidates, _ = build_xprompt_arg_completion_candidates(
                next_ctx,
                base_dir=base_dir,
                agent_candidates=(
                    self._snapshot_agent_completion_candidates()
                    if next_ctx.completion_kind == "xprompt_arg_agent"
                    else None
                ),
            )
            ctx = next_ctx
            token = effective_xprompt_arg_token(ctx)
            self._completion_kind = ctx.completion_kind
            if not candidates:
                self._clear_file_completion(clear_xprompt_arg_hint=False)
                self._refresh_xprompt_arg_hint_from_cursor()
                return True

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
