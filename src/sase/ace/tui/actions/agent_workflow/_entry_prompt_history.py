"""Prompt-history entry points for agent launch."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.core.paths import sase_projects_dir

from ._prompt_bar_mount import strip_editor_review_markers
from ._types import PromptContext

if TYPE_CHECKING:
    from ...modals import SelectionItem


class EntryPromptHistoryMixin:
    """Mixin providing prompt-history launch entry points."""

    _prompt_context: PromptContext | None

    if TYPE_CHECKING:

        def _load_last_custom_agent_selection(
            self,
        ) -> tuple[SelectionItem | None, bool]: ...

        def _vcs_prompt_prefix_or_notify(
            self, project_file: str, name: str
        ) -> str | None: ...

    def _start_prompt_history_from_last_selection(
        self, *, show_cancelled: bool = False, edit_first: bool = False
    ) -> None:
        """Show prompt history modal for the last agent selection (bound to ,.)."""
        from sase.core.time import generate_timestamp

        from ...modals import (
            PromptHistoryAction,
            PromptHistoryModal,
            PromptHistoryResult,
        )

        # Load last selection (same as Ctrl+Space)
        last, stale_cleared = self._load_last_custom_agent_selection()
        if last is None:
            if not stale_cleared:
                self.notify("No previous +/Ctrl+Space selection", severity="warning")  # type: ignore[attr-defined]
            return

        # Resolve VCS prefix. The substituted prefix and bar label show the
        # configured project name; the history grouping key stays the canonical
        # directory key (Patch names are already user-facing on both).
        from sase.project_display_names import project_display_name_for

        project_name: str = last.project_name
        project_dir = str(sase_projects_dir() / project_name)
        project_file = preferred_project_spec_path(project_dir, project_name)
        history_key = (
            last.cl_name if last.item_type == "cl" and last.cl_name else project_name
        )
        name = (
            last.cl_name
            if last.item_type == "cl" and last.cl_name
            else project_display_name_for(project_name)
        )
        prefix = self._vcs_prompt_prefix_or_notify(project_file, name)
        if prefix is None:
            return
        vcs_prefix = prefix.rstrip()

        # Set up prompt context (same as _show_prompt_input_bar_for_home)
        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"
        self._prompt_context = PromptContext(
            project_name="home",
            cl_name=None,
            project_file=preferred_project_spec_path(
                str(sase_projects_dir() / "home"), "home"
            ),
            workspace_dir=str(Path.home()),
            workspace_num=0,
            workflow_name=workflow_name,
            timestamp=timestamp,
            history_sort_key=history_key,
            display_name=name,
            update_target="",
            is_home_mode=True,
        )

        def _build_prompt(prompt_text: str) -> str:
            if vcs_prefix:
                from sase.xprompt import replace_vcs_workflow_tags

                return replace_vcs_workflow_tags(prompt_text, vcs_prefix)
            return prompt_text

        def _edit_prompt(prompt_text: str) -> None:
            prompt_for_editor = _build_prompt(prompt_text)
            edited_prompt = self._open_editor_for_agent_prompt(prompt_for_editor)  # type: ignore[attr-defined]
            if edited_prompt:
                marked, cleaned = strip_editor_review_markers(edited_prompt)
                if marked:
                    # A ` @` review marker requests review instead of launch:
                    # mount the prompt bar with this selection's context and
                    # editor-file semantics so a multi-agent markdown buffer
                    # re-stacks into panes with its frontmatter rather than
                    # launching directly.
                    self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                        initial_text=cleaned,
                        display_name=name,
                        history_sort_key=history_key,
                        as_xprompt_markdown=True,
                    )
                else:
                    self._finish_agent_launch(edited_prompt)  # type: ignore[attr-defined]
            else:
                self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
                self._prompt_context = None

        if edit_first:
            prompt_text = self._first_prompt_history_entry_for_editor()
            if prompt_text is None:
                self.notify("No prompt history entry to edit", severity="warning")  # type: ignore[attr-defined]
                self._prompt_context = None
                return
            _edit_prompt(prompt_text)
            return

        def on_history_select(result: PromptHistoryResult | None) -> None:
            if result is None:
                self._prompt_context = None
                return

            if result.action == PromptHistoryAction.SUBMIT:
                self._finish_agent_launch(_build_prompt(result.prompt_text))  # type: ignore[attr-defined]
            elif result.action == PromptHistoryAction.LOAD:
                # Mount prompt bar and load text into it
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=_build_prompt(result.prompt_text),
                    display_name=name,
                    history_sort_key=history_key,
                )
            else:
                _edit_prompt(result.prompt_text)

        self.push_screen(  # type: ignore[attr-defined]
            PromptHistoryModal(show_cancelled=show_cancelled),
            on_history_select,
        )

    def _first_prompt_history_entry_for_editor(self) -> str | None:
        """Return the default prompt-history entry highlighted by the modal."""
        from sase.history.prompt import list_prompt_records

        records = list_prompt_records(limit=1)
        if records:
            return records[0].text
        return None
