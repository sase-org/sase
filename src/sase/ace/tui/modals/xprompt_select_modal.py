"""XPrompt selection modal with filtering for the ace TUI."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.hints import build_editor_args
from sase.xprompt import get_all_prompts
from sase.xprompt.models import UNSET, InputArg
from sase.xprompt.reference_display import (
    workflow_reference_insertion,
    workflow_kind_value,
    workflow_reference_prefix,
    workflow_reference_suffix,
)
from sase.xprompt.workflow_models import Workflow

from ..util.frontmatter_syntax import markdown_document_syntax
from ..widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    xprompt_assist_entry_from_workflow,
)
from .base import OptionListNavigationMixin
from .xprompt_browser_helpers import (
    append_input_args,
    classify_source,
    resolve_source_to_file_path,
)

# ``Ctrl+I`` inline-expansion handler supplied by the prompt-bar request layer.
# Called with the selected ``(name, workflow)``; returns ``None`` on success
# (the caller has rendered/applied the expansion) or a user-facing error
# message to surface while keeping the selector open.
InlineExpandCallback = Callable[[str, "Workflow"], str | None]


@dataclass(frozen=True, slots=True)
class XPromptSelection:
    """Selection payload for inserting an xprompt after an existing ``#``."""

    suffix: str
    entry: XPromptAssistEntry | None = None


class _XPromptFilterInput(Input):
    """Custom input for XPrompt modal with scroll key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+d", "scroll_preview_down", "Scroll Down"),
        ("ctrl+u", "scroll_preview_up_or_clear", "Scroll Up/Clear"),
        ("ctrl+e", "forward('open_selected_in_editor')", "Open Definition"),
        ("ctrl+o", "forward('open_selected_for_editing')", "Edit Here"),
        ("ctrl+i", "forward('expand_selected')", "Expand"),
    ]

    def action_forward(self, action_name: str) -> None:
        """Forward an action to the parent modal."""
        modal = self.screen
        if isinstance(modal, XPromptSelectModal):
            getattr(modal, f"action_{action_name}")()

    def action_scroll_preview_down(self) -> None:
        """Scroll the preview panel down."""
        modal = self.screen
        if isinstance(modal, XPromptSelectModal):
            modal.scroll_preview_down()

    def action_scroll_preview_up_or_clear(self) -> None:
        """Scroll preview up, or clear input if already at top."""
        modal = self.screen
        if isinstance(modal, XPromptSelectModal):
            scroll = modal.query_one("#xprompt-preview-scroll", VerticalScroll)
            if scroll.scroll_y > 0:
                modal.scroll_preview_up()
            elif self.cursor_position > 0:
                # At top - clear line (unix line discard behavior)
                self.value = self.value[self.cursor_position :]
                self.cursor_position = 0


class XPromptSelectModal(
    OptionListNavigationMixin, ModalScreen[XPromptSelection | None]
):
    """Modal for selecting an xprompt with filtering and preview."""

    _option_list_id = "xprompt-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("ctrl+e", "open_selected_in_editor", "Open Definition"),
        ("ctrl+o", "open_selected_for_editing", "Edit Here"),
        ("ctrl+i", "expand_selected", "Expand"),
    ]
    _edit_definition_request_id = 0

    def __init__(
        self,
        project: str | None = None,
        extra_prompts: dict[str, Workflow] | None = None,
        expand_callback: InlineExpandCallback | None = None,
    ) -> None:
        """Initialize the xprompt modal.

        Args:
            project: Optional project name to include project-specific xprompts.
            extra_prompts: Additional prompts to merge (e.g. project-local
                xprompts detected from a VCS tag in the prompt text).
            expand_callback: Optional ``Ctrl+I`` handler invoked with the
                selected ``(name, workflow)``. It renders/applies the inline
                expansion and returns ``None`` on success or a user-facing
                error message to show while keeping the selector open. When
                ``None``, inline expansion is disabled and ``Ctrl+I`` is a
                no-op.
        """
        super().__init__()
        self._project = project
        self._extra_prompts = extra_prompts or {}
        self._expand_callback = expand_callback
        self._prompts: dict[str, Workflow] = {}
        self._all_items: dict[str, tuple[str, str]] = {}
        self._filtered_names: list[str] = []
        self._load_prompts()

    def _load_prompts(self) -> None:
        """Load xprompts and rebuild the preview catalog."""
        # Use unified loader - all items are Workflow objects now
        prompts = get_all_prompts(project=self._project)
        if self._extra_prompts:
            # Merge extra prompts; they take precedence on collision
            prompts = {**prompts, **self._extra_prompts}
        self._prompts = prompts

        # Build unified items dict: name -> (content/preview, kind)
        # Simple xprompts show raw content, complex workflows show step preview
        self._all_items = {}
        for name, workflow in self._prompts.items():
            kind = workflow_kind_value(workflow)
            if workflow.is_simple_xprompt():
                # Simple xprompt - show prompt_part content directly
                self._all_items[name] = (self._create_simple_preview(workflow), kind)
            else:
                # Complex workflow - show structured preview
                preview = self._create_workflow_preview(workflow)
                self._all_items[name] = (preview, kind)
        self._filtered_names = sorted(self._all_items.keys())

    def _create_simple_preview(self, workflow: Workflow) -> str:
        """Create a preview for a simple xprompt, adding rich metadata when present."""
        content = workflow.get_prompt_part_content()
        inputs = [inp for inp in workflow.inputs if not inp.is_step_input]
        has_input_descriptions = any(inp.description for inp in inputs)
        if workflow.memory_type is not None:
            memory_lines: list[str] = [
                f"# Memory: {workflow.name}",
                "",
                f"memory type: {workflow.memory_type}",
                "",
            ]
            if workflow.description:
                memory_lines.extend([workflow.description, ""])
            if inputs:
                memory_lines.append("## Inputs")
                memory_lines.extend(_input_preview_lines(inputs))
                memory_lines.append("")
            memory_lines.extend(["## Content", content])
            return "\n".join(memory_lines)
        if not workflow.description and not has_input_descriptions:
            return content

        lines: list[str] = [f"# XPrompt: {workflow.name}", ""]
        if workflow.description:
            lines.extend([workflow.description, ""])
        if inputs:
            lines.append("## Inputs")
            lines.extend(_input_preview_lines(inputs))
            lines.append("")
        lines.extend(["## Content", content])
        return "\n".join(lines)

    def _create_workflow_preview(self, workflow: Workflow) -> str:
        """Create a preview string for a workflow.

        Args:
            workflow: The Workflow object.

        Returns:
            A preview string showing workflow details.
        """
        lines: list[str] = []
        lines.append(f"# Workflow: {workflow.name}")
        lines.append("")

        if workflow.description:
            lines.append(workflow.description)
            lines.append("")

        inputs = [inp for inp in workflow.inputs if not inp.is_step_input]
        if inputs:
            lines.append("## Inputs")
            lines.extend(_input_preview_lines(inputs))
            lines.append("")

        lines.append("## Steps")
        for i, step in enumerate(workflow.steps, 1):
            if step.agent:
                step_type = "agent"
                step_label = step.agent.split("\n")[0][:50]  # First line, truncated
            elif step.bash:
                step_type = "bash"
                step_label = step.bash
            elif step.python:
                step_type = "python"
                step_label = step.python
            elif step.prompt_part:
                step_type = "prompt_part"
                step_label = step.prompt_part.split("\n")[0][
                    :50
                ]  # First line, truncated
            else:
                step_type = "unknown"
                step_label = "?"
            lines.append(f"{i}. [{step_type}] {step.name}: {step_label}")

        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="xprompt-modal-container"):
            yield Label("Select XPrompt", id="modal-title")
            if not self._all_items:
                yield Label("No xprompts configured")
            else:
                yield _XPromptFilterInput(
                    placeholder="Type to filter...", id="xprompt-filter-input"
                )
                with Horizontal(id="xprompt-panels"):
                    with Vertical(id="xprompt-list-panel"):
                        yield Label("XPrompts", id="xprompt-list-label")
                        yield OptionList(
                            *self._create_options(self._filtered_names),
                            id="xprompt-list",
                        )
                    with Vertical(id="xprompt-preview-panel"):
                        yield Label("Preview", id="xprompt-preview-label")
                        with VerticalScroll(id="xprompt-preview-scroll"):
                            yield Static("", id="xprompt-preview")
                yield Static(
                    "j/k ↑/↓: navigate • ^d/^u: scroll preview • ^e: open definition • ^o: edit here • ^i: expand • Enter: select • Esc/q: cancel",
                    id="xprompt-hints",
                )

    def _create_styled_label(self, name: str) -> Text:
        """Create styled text for an xprompt or workflow name."""
        text = Text()
        kind = self._all_items.get(name, ("", "xprompt"))[1]
        workflow = self._prompts.get(name)
        prefix = workflow_reference_prefix(workflow) if workflow else "#"
        if kind == "standalone_workflow":
            text.append("▶ ", style="bold #FFD700")
            text.append(prefix, style="bold #87D7FF")
            text.append(name)
        elif kind == "embeddable_workflow":
            text.append("⚙ ", style="bold #FFD700")  # Gold gear for workflows
            text.append(prefix, style="bold #87D7FF")
            text.append(name)
        elif kind == "memory":
            text.append(prefix, style="bold #87D7FF")
            text.append(name)
            if workflow and workflow.memory_type:
                text.append(
                    f"  memory · {workflow.memory_type}",
                    style="dim #87D7FF",
                )
        else:
            text.append(prefix, style="bold #87D7FF")
            text.append(name)
        # Append input arg signatures
        if workflow:
            append_input_args(text, workflow.inputs)
        return text

    def _create_options(self, names: list[str]) -> list[Option]:
        """Create options from xprompt names."""
        return [Option(self._create_styled_label(name), id=name) for name in names]

    def _get_filtered_names(self, filter_text: str) -> list[str]:
        """Get xprompt and workflow names that match the filter text."""
        all_names = sorted(self._all_items.keys())
        if not filter_text:
            return all_names
        filter_lower = filter_text.lower()
        return [
            name
            for name in all_names
            if filter_lower in self._filter_text_for_name(name).casefold()
        ]

    def _filter_text_for_name(self, name: str) -> str:
        workflow = self._prompts.get(name)
        content, _kind = self._all_items.get(name, ("", ""))
        parts = [name, content]
        if workflow is not None:
            parts.append(workflow.description or "")
            parts.extend(
                inp.description or ""
                for inp in workflow.inputs
                if not inp.is_step_input
            )
        return "\n".join(part for part in parts if part)

    def on_mount(self) -> None:
        """Focus the input and show initial preview on mount."""
        if self._all_items:
            filter_input = self.query_one("#xprompt-filter-input", _XPromptFilterInput)
            filter_input.focus()
            # Show preview for first item
            if self._filtered_names:
                self._update_preview_for_name(self._filtered_names[0])

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input change - update the option list."""
        self._filtered_names = self._get_filtered_names(event.value)
        option_list = self.query_one("#xprompt-list", OptionList)
        self._replace_options(option_list)
        # Update preview for first filtered item
        if self._filtered_names:
            self._update_preview_for_name(self._filtered_names[0])
        else:
            self._clear_preview()

    def on_key(self, event: events.Key) -> None:
        """Route ``Ctrl+I`` to inline expansion across every focus state.

        Terminals deliver ``Ctrl+I`` as the Tab byte, and Textual's focus
        cycling claims a bare Tab before the declared ``ctrl+i`` binding can
        fire (the same collision handled in :class:`PromptHistoryModal`).
        Intercepting ``tab`` here makes the expansion keymap work whether the
        filter input or the option list holds focus; a genuine ``ctrl+i`` event
        (enhanced keyboard protocol or the test harness) still routes through
        the declared bindings and is left untouched here.
        """
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self.action_expand_selected()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Handle Enter key in input - select highlighted item."""
        if not self._filtered_names:
            return

        option_list = self.query_one("#xprompt-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self._filtered_names):
            self.dismiss(self._selection_for_name(self._filtered_names[highlighted]))
        else:
            # Select first item if none highlighted
            self.dismiss(self._selection_for_name(self._filtered_names[0]))

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update preview when highlighting changes."""
        if event.option and event.option.id:
            self._update_preview_for_name(str(event.option.id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        if event.option and event.option.id:
            self.dismiss(self._selection_for_name(str(event.option.id)))

    def _selected_name(self) -> str | None:
        """Return the highlighted xprompt name, falling back to the first match."""
        if not self._filtered_names:
            return None

        try:
            option_list = self.query_one("#xprompt-list", OptionList)
            highlighted = option_list.highlighted
        except Exception:
            highlighted = None

        if highlighted is not None and 0 <= highlighted < len(self._filtered_names):
            return self._filtered_names[highlighted]
        return self._filtered_names[0]

    def action_open_selected_in_editor(self) -> None:
        """Open the selected xprompt or workflow definition in ``$EDITOR``."""
        selected_name = self._selected_name()
        if selected_name is None:
            self.notify("No xprompt selected", severity="warning")
            return

        workflow = self._prompts.get(selected_name)
        if workflow is None:
            self.notify("Could not find selected xprompt", severity="warning")
            return

        file_path = resolve_source_to_file_path(workflow.source_path)
        if file_path is None:
            self.notify("Could not resolve source file path", severity="error")
            return

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [file_path])

        try:
            with self.app.suspend():
                subprocess.run(editor_args, check=False)
        except OSError as exc:
            self.notify(f"Could not launch editor: {exc}", severity="error")
            return

        self._reload_prompts(selected_name=selected_name)

    def action_open_selected_for_editing(self) -> None:
        """Load the selected simple definition into the prompt bar for editing."""
        selected_name = self._selected_name()
        if selected_name is None:
            self.notify("No xprompt selected", severity="warning")
            return

        workflow = self._prompts.get(selected_name)
        if workflow is None:
            self.notify("Could not find selected xprompt", severity="warning")
            return
        if not workflow.is_simple_xprompt():
            self.notify("Workflow graphs use ^e / $EDITOR", severity="warning")
            return

        file_path = resolve_source_to_file_path(workflow.source_path)
        if file_path is None:
            self.notify("Definition source is unavailable", severity="error")
            return

        _category, _display, editable = classify_source(workflow.source_path)
        request_id = self._edit_definition_request_id + 1
        self._edit_definition_request_id = request_id
        self.run_worker(
            self._load_selected_definition_for_editing(
                name=selected_name,
                source_path=workflow.source_path,
                editable=editable,
                reference=workflow_reference_insertion(selected_name, workflow),
                request_id=request_id,
            ),
            exclusive=True,
            group="xprompt-selector-definition-load",
        )

    async def _load_selected_definition_for_editing(
        self,
        *,
        name: str,
        source_path: str | None,
        editable: bool,
        reference: str,
        request_id: int,
    ) -> None:
        """Read and apply the selected definition outside the widget pump."""
        from .xprompt_definition_loader import load_xprompt_definition_for_prompt_bar

        try:
            loaded = await load_xprompt_definition_for_prompt_bar(
                name=name,
                source_path=source_path,
                editable=editable,
                reference=reference,
            )
        except Exception as exc:
            if request_id == self._edit_definition_request_id:
                self.notify(f"Could not load definition: {exc}", severity="error")
            return

        if request_id != self._edit_definition_request_id:
            return
        if not getattr(self, "is_mounted", False):
            return
        loader = getattr(self.app, "load_xprompt_definition_into_home_prompt_bar", None)
        if not callable(loader):
            return
        loader(
            loaded.markdown,
            display_name=loaded.display_name,
            binding=loaded.binding,
            read_only=loaded.read_only,
            read_only_path=loaded.read_only_path,
            has_comments=loaded.has_comments,
        )

    def action_expand_selected(self) -> None:
        """Inline-expand the highlighted xprompt into the originating pane (``Ctrl+I``).

        Unlike ``Enter`` -- which inserts a ``#name`` reference -- this hands the
        selected ``(name, workflow)`` to the caller-supplied expansion callback,
        which renders the xprompt body and splices it into the pane that opened
        the ``#@`` selector. The callback returns ``None`` on success or a
        user-facing error message:

        - success: dismiss with no payload so the normal insertion callback is a
          no-op and no ``#name`` reference is inserted as well.
        - error: notify and stay open, leaving the current filter and highlight
          untouched so the user can pick another entry or fall back to ``Enter``.
        """
        if self._expand_callback is None:
            return

        selected_name = self._selected_name()
        if selected_name is None:
            self.notify("No xprompt selected", severity="warning")
            return

        workflow = self._prompts.get(selected_name)
        if workflow is None:
            self.notify("Could not find selected xprompt", severity="warning")
            return

        error = self._expand_callback(selected_name, workflow)
        if error:
            self.notify(error, severity="error")
            return

        # Success: the callback already rendered/applied the expansion. Dismiss
        # with no payload so the push-screen insertion callback returns early
        # and does not also insert a ``#name`` reference.
        self.dismiss(None)

    def _reload_prompts(self, *, selected_name: str | None = None) -> None:
        """Reload prompt definitions and preserve filter and selection state."""
        filter_text = ""
        try:
            filter_input = self.query_one("#xprompt-filter-input", _XPromptFilterInput)
            filter_text = filter_input.value
        except Exception:
            pass

        selected_name = selected_name or self._selected_name()
        self._load_prompts()
        self._filtered_names = self._get_filtered_names(filter_text)

        option_list = self.query_one("#xprompt-list", OptionList)
        self._replace_options(option_list)
        if not self._filtered_names:
            option_list.highlighted = None
            self._clear_preview()
            return

        try:
            highlighted = self._filtered_names.index(selected_name or "")
        except ValueError:
            highlighted = 0
        option_list.highlighted = highlighted
        self._update_preview_for_name(self._filtered_names[highlighted])

    def _replace_options(self, option_list: OptionList) -> None:
        """Replace the visible option list with the current filtered names."""
        option_list.clear_options()
        for option in self._create_options(self._filtered_names):
            option_list.add_option(option)

    def _selection_for_name(self, name: str) -> XPromptSelection:
        """Return the insertion payload for a selected xprompt name."""
        workflow = self._prompts.get(name)
        if workflow is None:
            return XPromptSelection(suffix=name)
        return XPromptSelection(
            suffix=workflow_reference_suffix(name, workflow),
            entry=xprompt_assist_entry_from_workflow(name, workflow),
        )

    def _insertion_suffix(self, name: str) -> str:
        """Return the text inserted after the existing ``#`` from ``#@``."""
        workflow = self._prompts.get(name)
        if workflow is None:
            return name
        return workflow_reference_suffix(name, workflow)

    def scroll_preview_down(self) -> None:
        """Scroll preview panel down (half page)."""
        scroll = self.query_one("#xprompt-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def scroll_preview_up(self) -> None:
        """Scroll preview panel up (half page)."""
        scroll = self.query_one("#xprompt-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def _update_preview_for_name(self, name: str) -> None:
        """Update preview for an xprompt or workflow by name."""
        try:
            preview = self.query_one("#xprompt-preview", Static)
            item = self._all_items.get(name)
            if item:
                content, _ = item
            else:
                content = ""
            # Show raw content with markdown syntax highlighting
            syntax = markdown_document_syntax(content)
            preview.update(syntax)
        except Exception:
            pass

    def _clear_preview(self) -> None:
        """Clear the preview panel."""
        try:
            preview = self.query_one("#xprompt-preview", Static)
            preview.update("")
        except Exception:
            pass


def _input_preview_lines(inputs: list[InputArg]) -> list[str]:
    lines: list[str] = []
    for inp in inputs:
        description_str = f" - {inp.description}" if inp.description else ""
        lines.append(
            f"- **{inp.name}**: {inp.type.value}{_default_suffix(inp)}{description_str}"
        )
    return lines


def _default_suffix(inp: InputArg) -> str:
    if inp.default is UNSET:
        return ""
    if inp.default is None:
        return " (default: null)"
    return f" (default: {inp.default})"
