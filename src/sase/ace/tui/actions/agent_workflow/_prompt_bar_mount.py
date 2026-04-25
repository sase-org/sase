"""Mount / unmount / focus lifecycle for the agent prompt input bar."""

from __future__ import annotations

import os
import re
from typing import ClassVar

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._types import PromptContext


def has_edit_directive(prompt: str) -> tuple[bool, str]:
    """Quick check for ``%edit`` / ``%e`` directive, returning cleaned prompt.

    If the directive is present, runs full directive extraction to get the
    properly cleaned prompt text.  Returns ``(True, cleaned_prompt)`` when
    found, ``(False, original_prompt)`` otherwise.
    """
    if "%" not in prompt:
        return False, prompt
    if not re.search(r"(?:^|\s)%(?:edit|e)(?:[:+(]|\s|$)", prompt, re.MULTILINE):
        return False, prompt
    from sase.xprompt.directives import extract_prompt_directives

    cleaned, directives = extract_prompt_directives(prompt)
    return directives.edit, cleaned


class PromptBarMountMixin:
    """Mount/unmount + focus management for the prompt input bar."""

    _prompt_context: PromptContext | None
    _TRIVIAL_PROMPT_PATTERNS: ClassVar[frozenset[str]]

    def _show_prompt_input_bar(
        self,
        project_name: str | None,
        cl_name: str | None,
        update_target: str,
        history_sort_key: str,
    ) -> None:
        """Show prompt input bar for agent workflow.

        Args:
            project_name: The project name.
            cl_name: The selected CL name (or None for project-only).
            update_target: What to checkout (CL name or "p4head").
            history_sort_key: Branch/CL name to sort prompt history by.
        """
        from sase.workflows.commit.project_file_utils import create_project_file
        from sase.core.time import generate_timestamp
        from sase.running_field import (
            get_first_available_axe_workspace,
            get_workspace_directory_for_num,
        )

        from ...widgets import PromptInputBar

        if project_name is None:
            self.notify("No project selected", severity="error")  # type: ignore[attr-defined]
            return

        project_file = os.path.expanduser(
            f"~/.sase/projects/{project_name}/{project_name}.gp"
        )

        # Create project file if it doesn't exist
        if not os.path.isfile(project_file):
            if not create_project_file(project_name):
                self.notify(  # type: ignore[attr-defined]
                    f"Failed to create project file: {project_file}",
                    severity="error",
                )
                return

        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"
        display_name = cl_name or project_name

        # For bulk runs, skip workspace resolution here;
        # _launch_bulk_agents() resolves workspaces per-changespec.
        if self._bulk_changespecs:  # type: ignore[attr-defined]
            workspace_num = 0
            workspace_dir = ""
        else:
            workspace_num = get_first_available_axe_workspace(project_file)
            try:
                workspace_dir, _ = get_workspace_directory_for_num(
                    workspace_num, project_name
                )
            except RuntimeError as e:
                self.notify(f"Failed to get workspace: {e}", severity="error")  # type: ignore[attr-defined]
                return

        # Remove any existing prompt bar before mounting a new one.
        # Must happen before overwriting _prompt_context so the old bar's
        # text is saved with the old context's project/branch.
        self._unmount_prompt_bar()

        # Store context for when prompt is submitted
        self._prompt_context = PromptContext(
            project_name=project_name,
            cl_name=cl_name,
            project_file=project_file,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            workflow_name=workflow_name,
            timestamp=timestamp,
            history_sort_key=history_sort_key,
            display_name=display_name,
            update_target=update_target,
        )

        # Immediately show prompt input bar (workspace prep happens in runner)
        self.mount(PromptInputBar(id="prompt-input-bar"))  # type: ignore[attr-defined]

    def _save_bar_text_as_cancelled(self, bar: object) -> None:
        """Extract text from bar and save to history as cancelled.

        Skips empty text and trivial trigger patterns (`.`, `.x`, VCS dot-prompts).
        Safe to call even if the prompt was already saved — add_or_update_prompt
        never downgrades a non-cancelled entry to cancelled.
        """
        try:
            text_area = bar.query_one("#prompt-input", PromptTextArea)  # type: ignore[attr-defined]
            text = text_area.text.strip()
        except Exception:
            return

        if not text:
            return

        # Skip trigger patterns that aren't real prompts
        if text in self._TRIVIAL_PROMPT_PATTERNS:
            return
        # Skip VCS dot-prompts like "#gh:sase ." or "#gh:sase .x"
        if text.endswith((" .", " .x")) and text.startswith("#"):
            return

        ctx = self._prompt_context
        if ctx:
            from sase.history.prompt import add_or_update_prompt

            add_or_update_prompt(
                text,
                project_name=ctx.project_name,
                branch_or_workspace=ctx.history_sort_key,
                cancelled=True,
            )
        else:
            from sase.history.prompt import add_or_update_prompt

            add_or_update_prompt(text, cancelled=True)

        from sase.history.file_references import (
            extract_recordable_file_refs,
            record_file_references,
        )

        refs = extract_recordable_file_refs(text)
        if refs:
            record_file_references(refs)

    def _unmount_prompt_bar(self) -> None:
        """Unmount the prompt input bar if present, saving any unsaved text."""
        from ...widgets import PromptInputBar

        try:
            bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
        except Exception:
            return  # Bar not present

        # Save any non-trivial text as cancelled before removing the bar.
        # This is the safety net — every code path that dismisses the bar
        # flows through here, so no prompt text can ever be silently lost.
        self._save_bar_text_as_cancelled(bar)

        # Transfer focus to a live widget *before* the forcible detach below.
        # Without this, Screen.focused can be left pointing at the PromptTextArea
        # that is about to be ripped out of the DOM, swallowing the next keys
        # the user types (e.g. j/k right after <enter>).
        self._transfer_focus_off_prompt_bar(bar)

        # Synchronously detach from parent's node list so the ID is freed
        # immediately. Without this, bar.remove() only schedules async
        # removal and a subsequent mount() would hit DuplicateIds.
        parent = bar._parent
        if parent is not None:
            parent._nodes._remove(bar)
        bar.remove()

    def _transfer_focus_off_prompt_bar(self, bar: object) -> None:
        """Move focus from *bar*'s descendants to the active tab's list widget.

        Must be called *before* the bar is detached from its parent so that
        Textual's focus-transfer machinery sees a live widget tree.
        """
        screen = getattr(self, "screen", None)
        focused = getattr(screen, "focused", None) if screen is not None else None

        # Only re-target focus if it is currently inside the bar (the common
        # case — the PromptTextArea owns focus while the bar is mounted).
        if focused is None or not self._widget_contains(bar, focused):
            return

        target = self._post_unmount_focus_target()
        if target is not None:
            try:
                target.focus()  # type: ignore[attr-defined]
                return
            except Exception:
                pass

        # Fallback: move focus to the next focusable sibling so we never leave
        # Screen.focused dangling on the about-to-be-detached text area.
        try:
            self.focus_next()  # type: ignore[attr-defined]
        except Exception:
            pass

    @staticmethod
    def _widget_contains(ancestor: object, descendant: object) -> bool:
        """Return True if *descendant* is *ancestor* or a child of it."""
        node = descendant
        while node is not None:
            if node is ancestor:
                return True
            node = getattr(node, "_parent", None)
        return False

    def _post_unmount_focus_target(self) -> object | None:
        """Return the widget that should own focus after the bar is unmounted.

        Keyed off the currently active tab.  Returns ``None`` if no
        suitable target can be resolved.
        """
        tab = getattr(self, "current_tab", None)
        candidates: tuple[str, ...]
        if tab == "agents":
            candidates = ("#agent-list-panel",)
        elif tab == "axe":
            candidates = ("#bgcmd-list-panel",)
        else:
            candidates = ("#list-panel",)

        for selector in candidates:
            try:
                widget = self.query_one(selector)  # type: ignore[attr-defined]
            except Exception:
                continue
            if getattr(widget, "display", True) and getattr(widget, "can_focus", True):
                return widget
        return None

    def _setup_home_prompt_context(
        self,
        display_name: str = "~",
        history_sort_key: str = "home",
    ) -> None:
        """Set up prompt context for home directory mode without showing UI.

        Args:
            display_name: Display name shown in the prompt context.
            history_sort_key: Key used to sort/filter prompt history.
        """
        from pathlib import Path

        from sase.core.time import generate_timestamp

        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"

        self._prompt_context = PromptContext(
            project_name="home",
            cl_name=None,
            project_file=os.path.expanduser("~/.sase/projects/home/home.gp"),
            workspace_dir=str(Path.home()),
            workspace_num=0,
            workflow_name=workflow_name,
            timestamp=timestamp,
            history_sort_key=history_sort_key,
            display_name=display_name,
            update_target="",
            is_home_mode=True,
        )

    def _load_prompt_into_bar(self, prompt: str) -> None:
        """Load text into the mounted prompt input bar's text area."""
        from ...widgets import PromptInputBar

        try:
            bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
            text_area = bar.query_one("#prompt-input", PromptTextArea)
            text_area.load_text(prompt)
            text_area.focus()
        except Exception:
            pass

    def _show_prompt_input_bar_for_home(
        self,
        initial_text: str = "",
        display_name: str = "~",
        history_sort_key: str = "home",
    ) -> None:
        """Show prompt input bar for home directory mode.

        This skips CL name and bug modals, running the agent from the user's
        home directory without version control or workspace management.

        Args:
            initial_text: Pre-populated text for the prompt input bar.
            display_name: Display name shown in the prompt context.
            history_sort_key: Key used to sort/filter prompt history.
        """
        from ...widgets import PromptInputBar

        # Remove any existing prompt bar before mounting a new one.
        # Must happen before overwriting _prompt_context so the old bar's
        # text is saved with the old context's project/branch.
        self._unmount_prompt_bar()

        self._setup_home_prompt_context(
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

        # Show prompt input bar
        self.mount(PromptInputBar(initial_value=initial_text, id="prompt-input-bar"))  # type: ignore[attr-defined]

    def _select_and_open_editor_for_home(
        self,
        initial_text: str = "",
        display_name: str = "~",
        history_sort_key: str = "home",
    ) -> None:
        """Set up home-mode prompt context and open editor directly.

        Combines ``_show_prompt_input_bar_for_home`` + ``ctrl+g`` into a
        single step so the user never sees the prompt input bar.

        Args:
            initial_text: Pre-populated text for the editor.
            display_name: Display name shown in the prompt context.
            history_sort_key: Key used to sort/filter prompt history.
        """
        self._setup_home_prompt_context(
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

        prompt = self._open_editor_for_agent_prompt(initial_text)  # type: ignore[attr-defined]
        if prompt:
            has_edit, cleaned = has_edit_directive(prompt)
            if has_edit:
                self._show_prompt_input_bar_for_home(initial_text=cleaned)
            else:
                self._finish_agent_launch(prompt)  # type: ignore[attr-defined]
        else:
            if initial_text.strip():
                from sase.history.prompt import add_or_update_prompt

                add_or_update_prompt(initial_text.strip(), cancelled=True)
            self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._prompt_context = None
