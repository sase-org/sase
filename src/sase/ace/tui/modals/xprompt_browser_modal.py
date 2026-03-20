"""XPrompt browser modal for exploring and managing xprompts."""

from __future__ import annotations

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.xprompt import get_all_prompts
from sase.xprompt.workflow_models import Workflow

from .base import OptionListNavigationMixin
from .xprompt_browser_actions import XPromptBrowserActionsMixin
from .xprompt_browser_helpers import BrowserItem, append_input_args, classify_source


class _BrowserFilterInput(Input):
    """Custom input for XPrompt browser with navigation key bindings.

    Since the filter input always has focus, Ctrl-key combinations are used
    for navigation and actions to avoid conflicts with text input.
    """

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+d", "scroll_preview_down", "Scroll Down"),
        ("ctrl+u", "scroll_preview_up_or_clear", "Scroll Up/Clear"),
        ("ctrl+n", "forward('next_option')", "Next"),
        ("ctrl+p", "forward('prev_option')", "Prev"),
        ("enter", "forward('edit_xprompt')", "Edit"),
        ("ctrl+o", "forward('add_xprompt')", "Add"),
    ]

    def action_forward(self, action_name: str) -> None:
        """Forward an action to the parent modal."""
        modal = self.screen
        if isinstance(modal, XPromptBrowserModal):
            getattr(modal, f"action_{action_name}")()

    def action_scroll_preview_down(self) -> None:
        """Scroll the preview panel down."""
        modal = self.screen
        if isinstance(modal, XPromptBrowserModal):
            modal.scroll_preview_down()

    def action_scroll_preview_up_or_clear(self) -> None:
        """Scroll preview up, or clear input if already at top."""
        modal = self.screen
        if isinstance(modal, XPromptBrowserModal):
            scroll = modal.query_one("#browser-preview-scroll", VerticalScroll)
            if scroll.scroll_y > 0:
                modal.scroll_preview_up()
            elif self.cursor_position > 0:
                self.value = self.value[self.cursor_position :]
                self.cursor_position = 0


class XPromptBrowserModal(
    XPromptBrowserActionsMixin, OptionListNavigationMixin, ModalScreen[None]
):
    """Modal for browsing, inspecting, and managing xprompts."""

    _option_list_id = "browser-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "edit_xprompt", "Edit"),
    ]

    def __init__(self, project: str | None = None) -> None:
        super().__init__()
        self._project = project
        self._all_items: list[BrowserItem] = []
        self._grouped: list[tuple[str, list[BrowserItem]]] = []
        self._load_xprompts()

    def _load_xprompts(self) -> None:
        """Load all xprompts and organize into groups."""
        prompts = get_all_prompts(project=self._project)
        items: list[BrowserItem] = []

        for name, workflow in prompts.items():
            source_path = workflow.source_path
            category, display_path, is_editable = classify_source(source_path)
            item_type = "xprompt" if workflow.is_simple_xprompt() else "workflow"
            items.append(
                BrowserItem(
                    name=name,
                    workflow=workflow,
                    source_category=category,
                    source_path=source_path,
                    display_path=display_path,
                    is_editable=is_editable,
                    item_type=item_type,
                )
            )

        self._all_items = items
        self._rebuild_groups()

    def _rebuild_groups(self, filter_text: str = "") -> None:
        """Rebuild grouped items, optionally filtered."""
        filter_lower = filter_text.lower()

        filtered = (
            [item for item in self._all_items if filter_lower in item.name.lower()]
            if filter_lower
            else list(self._all_items)
        )

        # Group by category
        groups: dict[str, list[BrowserItem]] = {}
        for item in filtered:
            groups.setdefault(item.source_category, []).append(item)

        for items_list in groups.values():
            items_list.sort(key=lambda x: x.name)

        # Order groups: known categories first, then dynamic ones
        known_order = [
            "CWD .xprompts/",
            "CWD xprompts/",
            "Home ~/.xprompts/",
            "Home ~/xprompts/",
        ]

        ordered: list[tuple[str, list[BrowserItem]]] = []
        seen: set[str] = set()

        for cat in known_order:
            if cat in groups:
                ordered.append((cat, groups[cat]))
                seen.add(cat)

        # Project categories
        for cat in sorted(groups.keys()):
            if cat.startswith("Project (") and cat not in seen:
                ordered.append((cat, groups[cat]))
                seen.add(cat)

        if "User sase.yml" in groups and "User sase.yml" not in seen:
            ordered.append(("User sase.yml", groups["User sase.yml"]))
            seen.add("User sase.yml")

        # Plugin categories
        for cat in sorted(groups.keys()):
            if cat.startswith("Plugin (") and cat not in seen:
                ordered.append((cat, groups[cat]))
                seen.add(cat)

        if "Built-in" in groups and "Built-in" not in seen:
            ordered.append(("Built-in", groups["Built-in"]))
            seen.add("Built-in")

        # Any remaining
        for cat in sorted(groups.keys()):
            if cat not in seen:
                ordered.append((cat, groups[cat]))

        self._grouped = ordered

    def _get_flat_items(self) -> list[BrowserItem]:
        """Get flat list of items from grouped data (for index lookups)."""
        result: list[BrowserItem] = []
        for _, items in self._grouped:
            result.extend(items)
        return result

    def compose(self) -> ComposeResult:
        total = len(self._all_items)
        with Container(id="browser-container"):
            yield Label(
                f"XPrompt Browser [{total} xprompts]",
                id="browser-title",
            )
            yield _BrowserFilterInput(
                placeholder="Type to filter...",
                id="browser-filter-input",
            )
            with Horizontal(id="browser-panels"):
                with Vertical(id="browser-list-panel"):
                    yield OptionList(
                        *self._create_options(),
                        id="browser-list",
                    )
                with Vertical(id="browser-preview-panel"):
                    with VerticalScroll(id="browser-preview-scroll"):
                        yield Static("", id="browser-preview")
                    yield Static("", id="browser-meta")
            yield Static(
                "^n/^p: navigate  enter: edit  ^o: add new  ^d/^u: scroll  Esc: close",
                id="browser-hints",
            )

    def _create_options(self) -> list[Option]:
        """Create OptionList items with group headers as disabled options."""
        options: list[Option] = []
        for category, items in self._grouped:
            header_text = Text(f"── {category} ──", style="bold dim")
            options.append(
                Option(header_text, id=f"__header__{category}", disabled=True)
            )
            for item in items:
                options.append(
                    Option(
                        self._create_item_label(item),
                        id=f"item__{item.name}",
                    )
                )
        return options

    def _create_item_label(self, item: BrowserItem) -> Text:
        """Create styled label for an xprompt item."""
        text = Text()
        if item.item_type == "workflow":
            text.append("  ⚙ ", style="bold #FFD700")  # Gold gear for workflows
            text.append("#", style="bold #87D7FF")
        else:
            text.append("  #", style="bold #87D7FF")
        text.append(item.name)
        # Append input arg signatures
        append_input_args(text, item.workflow.inputs)
        return text

    def on_mount(self) -> None:
        filter_input = self.query_one("#browser-filter-input", _BrowserFilterInput)
        filter_input.focus()
        flat_items = self._get_flat_items()
        if flat_items:
            self._update_preview(flat_items[0])
            option_list = self.query_one("#browser-list", OptionList)
            self._skip_to_first_item(option_list)

    def _skip_to_first_item(self, option_list: OptionList) -> None:
        """Skip to the first non-header item."""
        for i in range(option_list.option_count):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def on_input_changed(self, event: Input.Changed) -> None:
        self._rebuild_groups(event.value)
        option_list = self.query_one("#browser-list", OptionList)
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)

        flat_items = self._get_flat_items()
        if flat_items:
            self._skip_to_first_item(option_list)
            self._update_preview(flat_items[0])
        else:
            self._clear_preview()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option and event.option.id:
            opt_id = str(event.option.id)
            if opt_id.startswith("__header__"):
                return
            name = opt_id.removeprefix("item__")
            for item in self._get_flat_items():
                if item.name == name:
                    self._update_preview(item)
                    return

    def action_next_option(self) -> None:
        """Move to next non-header option."""
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        current = option_list.highlighted
        if current is None:
            self._skip_to_first_item(option_list)
            return
        for i in range(current + 1, option_list.option_count):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def action_prev_option(self) -> None:
        """Move to previous non-header option."""
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        current = option_list.highlighted
        if current is None:
            return
        for i in range(current - 1, -1, -1):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def _get_highlighted_item(self) -> BrowserItem | None:
        """Get the currently highlighted browser item."""
        option_list = self.query_one("#browser-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            opt = option_list.get_option_at_index(highlighted)
            if opt.id and not str(opt.id).startswith("__header__"):
                name = str(opt.id).removeprefix("item__")
                for item in self._get_flat_items():
                    if item.name == name:
                        return item
        except Exception:
            pass
        return None

    def _reload_xprompts(self) -> None:
        """Reload all xprompts and rebuild the list."""
        try:
            filter_input = self.query_one("#browser-filter-input", _BrowserFilterInput)
            filter_text = filter_input.value
        except Exception:
            filter_text = ""

        highlighted_item = self._get_highlighted_item()
        highlighted_name = highlighted_item.name if highlighted_item else None

        self._load_xprompts()
        self._rebuild_groups(filter_text)

        try:
            title = self.query_one("#browser-title", Label)
            title.update(f"XPrompt Browser [{len(self._all_items)} xprompts]")
        except Exception:
            pass

        option_list = self.query_one("#browser-list", OptionList)
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)

        flat_items = self._get_flat_items()
        restored = False
        if highlighted_name:
            for i in range(option_list.option_count):
                try:
                    opt = option_list.get_option_at_index(i)
                    if opt.id == f"item__{highlighted_name}":
                        option_list.highlighted = i
                        for item in flat_items:
                            if item.name == highlighted_name:
                                self._update_preview(item)
                                break
                        restored = True
                        break
                except Exception:
                    continue

        if not restored and flat_items:
            self._skip_to_first_item(option_list)
            self._update_preview(flat_items[0])

    def _update_preview(self, item: BrowserItem) -> None:
        """Update the preview panel for an item."""
        try:
            preview = self.query_one("#browser-preview", Static)
            meta = self.query_one("#browser-meta", Static)
        except Exception:
            return

        workflow = item.workflow
        if workflow.is_simple_xprompt():
            content = workflow.get_prompt_part_content()
        else:
            content = self._create_workflow_preview(workflow)

        syntax = Syntax(content, "markdown", theme="monokai", word_wrap=True)
        preview.update(syntax)

        # Metadata block
        meta_text = Text()
        meta_text.append("── Source Info ──\n", style="bold dim")
        meta_text.append("Source: ", style="bold")
        meta_text.append(f"{item.display_path}\n")
        meta_text.append("Type: ", style="bold")
        meta_text.append(f"{item.item_type}")
        if item.item_type == "workflow":
            meta_text.append(f" ({len(workflow.steps)} steps)")
        else:
            meta_text.append(" (simple)")
        meta_text.append("\n")

        if workflow.inputs:
            input_strs = [
                f"{inp.name} ({inp.type.value})"
                for inp in workflow.inputs
                if not inp.is_step_input
            ]
            if input_strs:
                meta_text.append("Inputs: ", style="bold")
                meta_text.append(", ".join(input_strs))
                meta_text.append("\n")

        meta_text.append("Editable: ", style="bold")
        meta_text.append(
            "yes" if item.is_editable else "no",
            style="green" if item.is_editable else "red",
        )

        meta.update(meta_text)

    def _create_workflow_preview(self, workflow: Workflow) -> str:
        """Create a preview string for a workflow."""
        lines: list[str] = [f"# Workflow: {workflow.name}", ""]
        inputs = [inp for inp in workflow.inputs if not inp.is_step_input]
        if inputs:
            lines.append("## Inputs")
            for inp in inputs:
                default_str = f" (default: {inp.default})" if inp.default else ""
                lines.append(f"- **{inp.name}**: {inp.type.value}{default_str}")
            lines.append("")
        lines.append("## Steps")
        for i, step in enumerate(workflow.steps, 1):
            if step.agent:
                step_type = "agent"
                step_label = step.agent.split("\n")[0][:50]
            elif step.bash:
                step_type = "bash"
                step_label = step.bash
            elif step.python:
                step_type = "python"
                step_label = step.python
            elif step.prompt_part:
                step_type = "prompt_part"
                step_label = step.prompt_part.split("\n")[0][:50]
            else:
                step_type = "unknown"
                step_label = "?"
            lines.append(f"{i}. [{step_type}] {step.name}: {step_label}")
        return "\n".join(lines)

    def _clear_preview(self) -> None:
        """Clear the preview panel."""
        try:
            preview = self.query_one("#browser-preview", Static)
            meta = self.query_one("#browser-meta", Static)
            preview.update("")
            meta.update("")
        except Exception:
            pass

    def scroll_preview_down(self) -> None:
        """Scroll the preview panel down by half a page."""
        scroll = self.query_one("#browser-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def scroll_preview_up(self) -> None:
        """Scroll the preview panel up by half a page."""
        scroll = self.query_one("#browser-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)
