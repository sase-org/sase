"""Mount / unmount / focus lifecycle for the agent prompt input bar."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sase.ace.changespec.project_spec_path import preferred_project_spec_path
from sase.core.paths import sase_projects_dir

from ._types import PromptContext

if TYPE_CHECKING:
    from sase.xprompt.models import InputArg
    from sase.ace.tui.widgets.prompt_stack import XPromptBinding

_EDITOR_REVIEW_MARKER = " @"


def strip_editor_review_markers(prompt: str) -> tuple[bool, str]:
    """Strip trailing `` @`` editor-review markers from returned editor text.

    Scans every line of *prompt*; a line matches when the text before its line
    terminator ends with the exact two-character suffix `` @`` (space then
    ``@``). Strips exactly those two characters from each matching line,
    preserving all other characters, every non-matching line, line order, and
    newline style (including the final newline).

    Returns ``(True, cleaned_text)`` when at least one line matched, otherwise
    ``(False, prompt)`` unchanged.

    This is an editor-return syntax, not a runtime directive: typing `` @`` in
    the prompt bar and submitting it is unaffected. The strip runs before
    xprompt-markdown loading so a marked separator such as ``--- @`` becomes a
    real ``---`` separator before stack parsing.
    """
    if _EDITOR_REVIEW_MARKER not in prompt:
        return False, prompt

    matched = False
    cleaned_lines: list[str] = []
    for line in prompt.splitlines(keepends=True):
        if line.endswith("\r\n"):
            content, terminator = line[:-2], "\r\n"
        elif line.endswith(("\n", "\r")):
            content, terminator = line[:-1], line[-1]
        else:
            content, terminator = line, ""
        if content.endswith(_EDITOR_REVIEW_MARKER):
            content = content[: -len(_EDITOR_REVIEW_MARKER)]
            matched = True
        cleaned_lines.append(content + terminator)

    if not matched:
        return False, prompt
    return True, "".join(cleaned_lines)


class PromptBarMountMixin:
    """Mount/unmount + focus management for the prompt input bar."""

    _prompt_context: PromptContext | None

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
            cl_name: The selected ChangeSpec name (or None for project-only).
            update_target: What to checkout (ChangeSpec name or "p4head").
            history_sort_key: Launch context label propagated to spawned agents.
        """
        from sase.workflows.commit.project_file_utils import create_project_file
        from sase.core.time import generate_timestamp

        from ...widgets import PromptInputBar

        if project_name is None:
            self.notify("No project selected", severity="error")  # type: ignore[attr-defined]
            return

        project_dir = str(sase_projects_dir() / project_name)
        project_file = preferred_project_spec_path(project_dir, project_name)

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

        # Workspace allocation happens at spawn time so launch can retry if
        # another agent claims the slot between preflight and subprocess spawn.
        workspace_num = 0
        workspace_dir = ""

        # Remove any existing prompt bar before mounting a new one.
        # Must happen before overwriting _prompt_context so the old bar's
        # text is saved with the old context.
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

    def _save_bar_text_as_cancelled(self, bar: object) -> str:
        """Extract text from bar and save to history as cancelled.

        Safe to call even if the prompt was already saved — add_or_update_prompt
        never downgrades a non-cancelled entry to cancelled.
        """
        try:
            text = bar.current_prompt_text()  # type: ignore[attr-defined]
        except Exception:
            return ""
        return self._save_text_as_cancelled(text)

    def _save_text_as_cancelled(
        self, text: str, *, record_segments: bool = True
    ) -> str:
        """Save *text* to prompt history as cancelled, with file references.

        Shared by the whole-bar cancel safety net and the Phase 4 per-pane
        ``<ctrl+c>`` cancel, which records only the cancelled pane's text.
        Empty / whitespace-only text is ignored. ``record_segments`` lets the
        all-pane cancel path preserve the joined stack as one history row, and
        ``add_or_update_prompt`` never downgrades a non-cancelled entry to
        cancelled.
        """
        text = text.strip()
        if not text:
            return ""

        from sase.history.prompt import add_or_update_prompt, is_recordable_prompt

        recorded = is_recordable_prompt(text)
        if record_segments:
            add_or_update_prompt(text, cancelled=True)
        else:
            add_or_update_prompt(text, cancelled=True, record_segments=False)

        from sase.history.file_references import (
            extract_recordable_file_refs,
            record_file_references,
        )

        refs = extract_recordable_file_refs(text)
        if refs:
            record_file_references(refs)
        return text if recorded else ""

    def _unmount_prompt_bar(self) -> str:
        """Unmount the prompt input bar if present, saving any unsaved text.

        Cancel/dismiss path. Use ``_unmount_prompt_bar_after_submit()`` from
        the successful-submit path so the just-submitted prompt is not
        re-written to history as ``cancelled=True``.
        """
        from ...widgets import PromptInputBar

        try:
            bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
        except Exception:
            return ""  # Bar not present

        # Save any non-trivial text as cancelled before removing the bar.
        # This is the safety net — every dismissal code path flows through
        # here, so no prompt text can ever be silently lost.
        stored_text = self._save_bar_text_as_cancelled(bar)
        self._detach_prompt_bar(bar)
        return stored_text

    def _unmount_prompt_bar_after_submit(self) -> None:
        """Unmount the prompt input bar after a successful submit.

        Skips the ``_save_bar_text_as_cancelled`` safety net: on a
        successful submit the launch path itself writes the final
        non-cancelled history entry, and routing through the cancel path
        would race that write with a stale ``cancelled=True`` entry.
        """
        self._unmount_prompt_bar_without_cancel_save()

    def _unmount_prompt_bar_without_cancel_save(self) -> None:
        """Unmount the prompt input bar without the cancelled-history safety net."""
        from ...widgets import PromptInputBar

        try:
            bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
        except Exception:
            return  # Bar not present

        self._detach_prompt_bar(bar)

    def _detach_prompt_bar(self, bar: object) -> None:
        # Transfer focus to a live widget *before* the forcible detach below.
        # Without this, Screen.focused can be left pointing at the PromptTextArea
        # that is about to be ripped out of the DOM, swallowing the next keys
        # the user types (e.g. j/k right after <enter>).
        self._transfer_focus_off_prompt_bar(bar)

        # Synchronously detach from parent's node list so the ID is freed
        # immediately. Without this, bar.remove() only schedules async
        # removal and a subsequent mount() would hit DuplicateIds.
        parent = bar._parent  # type: ignore[attr-defined]
        if parent is not None:
            parent._nodes._remove(bar)
        bar.remove()  # type: ignore[attr-defined]

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
        elif getattr(self, "current_artifacts_subtab", "prs") == "bugs":
            candidates = ("#bugs-list",)
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
            history_sort_key: Launch context label propagated to spawned agents.
        """
        from pathlib import Path

        from sase.core.time import generate_timestamp

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
            history_sort_key=history_sort_key,
            display_name=display_name,
            update_target="",
            is_home_mode=True,
        )

    def _load_editor_markdown_into_bar(self, markdown: str) -> None:
        """Reload the mounted prompt bar from cleaned editor markdown.

        Uses editor-file (xprompt markdown) semantics via
        :meth:`PromptInputBar.load_stack_from_xprompt_markdown`: leading xprompt
        frontmatter is lifted into the frontmatter panel and real ``---`` body
        separators split into one prompt pane per agent segment.  Used only for
        ` @`-marker editor returns and whole-stack editor returns — never for
        ordinary history loads, which keep their verbatim single-pane contract.
        """
        from ...widgets import PromptInputBar

        try:
            bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
            bar.load_stack_from_xprompt_markdown(markdown, preserve_target=True)
        except Exception:
            pass

    def _show_prompt_input_bar_for_home(
        self,
        initial_text: str = "",
        display_name: str = "~",
        history_sort_key: str = "home",
        *,
        as_xprompt_markdown: bool = False,
        frontmatter_inputs: list[InputArg] | None = None,
        binding: XPromptBinding | None = None,
    ) -> None:
        """Show prompt input bar for home directory mode.

        This skips ChangeSpec name and bug modals, running the agent from the user's
        home directory without version control or workspace management.

        Args:
            initial_text: Pre-populated text for the prompt input bar.
            display_name: Display name shown in the prompt context.
            history_sort_key: Launch context label propagated to spawned agents.
            as_xprompt_markdown: When True, seed the bar with editor-file
                semantics (lift leading frontmatter, split ``---`` into panes)
                rather than verbatim history-load semantics.  Used by the
                ` @`-marker editor-return remount path.
            frontmatter_inputs: Declared xprompt inputs to stage into the bar's
                prompt frontmatter before mount, so the frontmatter panel
                auto-shows on mount.  Used by the Admin Center XPrompts tab
                ``Ctrl+I`` load (parity with the Select XPrompt ``Ctrl+I`` path).
        """
        from ...widgets import PromptInputBar

        # Remove any existing prompt bar before mounting a new one.
        # Must happen before overwriting _prompt_context so the old bar's
        # text is saved with the old context.
        self._unmount_prompt_bar()

        self._setup_home_prompt_context(
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

        # Show prompt input bar
        if as_xprompt_markdown:
            bar = PromptInputBar(
                initial_xprompt_markdown=initial_text, id="prompt-input-bar"
            )
        else:
            bar = PromptInputBar(initial_value=initial_text, id="prompt-input-bar")
        if binding is not None:
            bar.target_xprompt(binding, source_markdown=initial_text)
        # Stage declared inputs into the stack's frontmatter pre-mount: the
        # panel refresh is a no-op until the bar mounts, and ``on_mount`` then
        # auto-shows the frontmatter panel from the seeded stack.
        if frontmatter_inputs:
            bar.merge_frontmatter_inputs(frontmatter_inputs)
        self.mount(bar)  # type: ignore[attr-defined]

    def load_xprompt_into_home_prompt_bar(
        self,
        expanded_text: str,
        *,
        display_name: str,
        inputs: list[InputArg] | None = None,
    ) -> None:
        """Close the Admin Center and load an inline-expanded xprompt into a bar.

        Drives the Admin Center XPrompts tab ``Ctrl+I`` load: the selected row
        was already rendered via :func:`expand_inline_xprompt`, so this pops the
        Admin Center modal and opens a fresh home-mode prompt bar carrying the
        rendered *expanded_text* for editing/submission.  Declared *inputs* are
        staged into prompt frontmatter (parity with the Select XPrompt
        ``Ctrl+I`` path), which needs no project/ChangeSpec selection.

        Mounting is deferred until after the modal pops so the new bar's
        on-mount focus lands on the revealed main screen rather than fighting
        the closing modal.
        """
        from textual.screen import ModalScreen

        if isinstance(self.screen, ModalScreen):  # type: ignore[attr-defined]
            self.pop_screen()  # type: ignore[attr-defined]

        def _mount() -> None:
            self._show_prompt_input_bar_for_home(
                initial_text=expanded_text,
                display_name=display_name,
                history_sort_key="home",
                frontmatter_inputs=inputs,
            )

        self.call_after_refresh(_mount)  # type: ignore[attr-defined]

    def load_xprompt_definition_into_home_prompt_bar(
        self,
        markdown: str,
        *,
        display_name: str,
        binding: XPromptBinding | None,
        read_only: bool = False,
        has_comments: bool = False,
    ) -> None:
        """Close the browser and author a raw simple xprompt definition."""
        from textual.screen import ModalScreen

        if isinstance(self.screen, ModalScreen):  # type: ignore[attr-defined]
            self.pop_screen()  # type: ignore[attr-defined]

        def _mount() -> None:
            self._show_prompt_input_bar_for_home(
                initial_text=markdown,
                display_name=display_name,
                history_sort_key="home",
                as_xprompt_markdown=True,
                binding=binding,
            )
            if read_only:
                self.notify("Read-only source — gw will save-as", severity="warning")  # type: ignore[attr-defined]
            if has_comments:
                self.notify(  # type: ignore[attr-defined]
                    "Frontmatter comments cannot survive structured save; inspect raw mode",
                    severity="warning",
                )

        self.call_after_refresh(_mount)  # type: ignore[attr-defined]

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
            history_sort_key: Launch context label propagated to spawned agents.
        """
        self._setup_home_prompt_context(
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

        prompt = self._open_editor_for_agent_prompt(initial_text)  # type: ignore[attr-defined]
        if prompt:
            marked, cleaned = strip_editor_review_markers(prompt)
            if marked:
                # A ` @` review marker requests review instead of launch:
                # remount the bar with the caller's display/history context (not
                # the generic home labels) and editor-file semantics so a
                # multi-agent markdown buffer re-stacks into panes with its
                # frontmatter.
                self._show_prompt_input_bar_for_home(
                    initial_text=cleaned,
                    display_name=display_name,
                    history_sort_key=history_sort_key,
                    as_xprompt_markdown=True,
                )
            else:
                self._finish_agent_launch(prompt)  # type: ignore[attr-defined]
        else:
            if initial_text.strip():
                from sase.history.prompt import add_or_update_prompt

                add_or_update_prompt(initial_text.strip(), cancelled=True)
            self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._prompt_context = None
