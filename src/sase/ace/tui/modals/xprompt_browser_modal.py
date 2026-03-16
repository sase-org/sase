"""XPrompt browser modal for exploring and managing xprompts."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.hints import build_editor_args
from sase.xprompt import get_all_prompts
from sase.xprompt.loader import get_sase_package_xprompts_dir
from sase.xprompt.models import UNSET, InputArg
from sase.xprompt.workflow_models import Workflow

from .base import OptionListNavigationMixin


def _append_input_args(text: Text, inputs: list[InputArg]) -> None:
    """Append styled input arg signatures to a Rich Text label.

    Renders user-facing inputs on a new indented line below the xprompt name.
    Required args appear bright; optional args are dimmed with defaults or ``?``.
    """
    user_inputs = [inp for inp in inputs if not inp.is_step_input]
    if not user_inputs:
        return
    for inp in user_inputs:
        text.append("\n     ")  # new line + 5-space indent
        required = inp.default is UNSET
        if required:
            text.append(inp.name, style="#D7AF87")
        else:
            text.append(inp.name, style="dim #D7AF87")
            has_default = inp.default is not None and str(inp.default) != ""
            if has_default:
                text.append(f"={inp.default}", style="dim #888888")
            else:
                text.append("?", style="dim #888888")


@dataclass
class _BrowserItem:
    """An xprompt item in the browser list."""

    name: str
    workflow: Workflow
    source_category: str
    source_path: str | None
    display_path: str
    is_editable: bool
    item_type: str  # "xprompt" or "workflow"


def _classify_source(source_path: str | None) -> tuple[str, str, bool]:
    """Classify a source path into (category_label, display_path, is_editable)."""
    if source_path is None:
        return "Built-in", "", False

    home = str(Path.home())
    cwd = str(Path.cwd())
    sase_pkg_dir = str(get_sase_package_xprompts_dir())

    # Plugin sources: "plugin:module_name/filename.md" (xprompts/ dirs)
    # or "plugin_config:module_name" (default_config.yml)
    if source_path.startswith("plugin:") or source_path.startswith("plugin_config:"):
        if source_path.startswith("plugin_config:"):
            module_name = source_path.removeprefix("plugin_config:")
        else:
            module_part = source_path.removeprefix("plugin:")
            module_name = (
                module_part.split("/")[0] if "/" in module_part else module_part
            )
        short_name = module_name.replace("_", "-")
        return f"Plugin ({short_name})", source_path, False

    # Built-in default config xprompts
    if source_path == "default_config":
        return "Built-in", "sase default_config.yml", False

    # Config sources: user sase.yml
    if source_path == "config":
        return "User sase.yml", "~/.config/sase/sase.yml", True

    # Config overlay sources: sase_*.yml files
    if source_path.startswith("config_overlay:"):
        filename = source_path.removeprefix("config_overlay:")
        return "User sase.yml", f"~/.config/sase/{filename}", True

    # Local sase.yml in CWD
    if source_path == "local_config":
        return "Local sase.yml", "./sase.yml", True

    # Inside sase package (built-in)
    if source_path.startswith(sase_pkg_dir):
        return "Built-in", source_path.replace(home, "~"), False

    # Project-specific: ~/.config/sase/xprompts/{proj}/
    project_prefix = os.path.join(home, ".config", "sase", "xprompts")
    if source_path.startswith(project_prefix + "/"):
        remainder = source_path[len(project_prefix) + 1 :]
        proj = remainder.split("/")[0]
        return f"Project ({proj})", source_path.replace(home, "~"), True

    # CWD directories
    cwd_hidden = os.path.join(cwd, ".xprompts")
    cwd_visible = os.path.join(cwd, "xprompts")
    if source_path.startswith(cwd_hidden + "/"):
        return "CWD .xprompts/", source_path.replace(cwd, "."), True
    if source_path.startswith(cwd_visible + "/"):
        return "CWD xprompts/", source_path.replace(cwd, "."), True

    # Home directories
    home_hidden = os.path.join(home, ".xprompts")
    home_visible = os.path.join(home, "xprompts")
    if source_path.startswith(home_hidden + "/"):
        return "Home ~/.xprompts/", source_path.replace(home, "~"), True
    if source_path.startswith(home_visible + "/"):
        return "Home ~/xprompts/", source_path.replace(home, "~"), True

    # Fallback
    return "Other", source_path.replace(home, "~"), True


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


class XPromptBrowserModal(OptionListNavigationMixin, ModalScreen[None]):
    """Modal for browsing, inspecting, and managing xprompts."""

    _option_list_id = "browser-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "edit_xprompt", "Edit"),
    ]

    def __init__(self, project: str | None = None) -> None:
        super().__init__()
        self._project = project
        self._all_items: list[_BrowserItem] = []
        self._grouped: list[tuple[str, list[_BrowserItem]]] = []
        self._load_xprompts()

    def _load_xprompts(self) -> None:
        """Load all xprompts and organize into groups."""
        prompts = get_all_prompts(project=self._project)
        items: list[_BrowserItem] = []

        for name, workflow in prompts.items():
            source_path = workflow.source_path
            category, display_path, is_editable = _classify_source(source_path)
            item_type = "xprompt" if workflow.is_simple_xprompt() else "workflow"
            items.append(
                _BrowserItem(
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
        groups: dict[str, list[_BrowserItem]] = {}
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

        ordered: list[tuple[str, list[_BrowserItem]]] = []
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

    def _get_flat_items(self) -> list[_BrowserItem]:
        """Get flat list of items from grouped data (for index lookups)."""
        result: list[_BrowserItem] = []
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

    def _create_item_label(self, item: _BrowserItem) -> Text:
        """Create styled label for an xprompt item."""
        text = Text()
        if item.item_type == "workflow":
            text.append("  ⚙ ", style="bold #FFD700")  # Gold gear for workflows
            text.append("#", style="bold #87D7FF")
        else:
            text.append("  #", style="bold #87D7FF")
        text.append(item.name)
        # Append input arg signatures
        _append_input_args(text, item.workflow.inputs)
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

    def _get_highlighted_item(self) -> _BrowserItem | None:
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

    def action_edit_xprompt(self) -> None:
        """Open highlighted xprompt in $EDITOR."""
        item = self._get_highlighted_item()
        if item is None:
            return

        if not item.is_editable:
            self.notify("This xprompt is read-only", severity="warning")
            return

        if item.source_path is None:
            self.notify("No source file available", severity="warning")
            return

        # For config-based xprompts, open the config file
        if item.source_path == "config":
            config_path = Path.home() / ".config" / "sase" / "sase.yml"
            if not config_path.exists():
                self.notify("Config file not found", severity="error")
                return
            file_path = str(config_path)
        elif item.source_path and item.source_path.startswith("config_overlay:"):
            filename = item.source_path.removeprefix("config_overlay:")
            config_path = Path.home() / ".config" / "sase" / filename
            if not config_path.exists():
                self.notify("Config file not found", severity="error")
                return
            file_path = str(config_path)
        else:
            file_path = item.source_path

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [file_path])

        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

        self._reload_xprompts()

    def action_add_xprompt(self) -> None:
        """Add a new xprompt via input modal."""
        from .add_xprompt_modal import AddXPromptModal

        def _on_add(path: str | None) -> None:
            if path is None:
                return
            self._create_and_edit_xprompt(path)

        self.app.push_screen(AddXPromptModal(), _on_add)

    def _create_and_edit_xprompt(self, path: str) -> None:
        """Create a skeleton xprompt file and open in editor."""
        expanded = os.path.expanduser(path)
        file_path = Path(expanded)

        file_path.parent.mkdir(parents=True, exist_ok=True)

        if not file_path.exists():
            name = file_path.stem
            skeleton = f"# {name}\n\nYour xprompt content here.\n"
            file_path.write_text(skeleton, encoding="utf-8")

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [str(file_path)])

        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

        self._reload_xprompts()

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

    def _update_preview(self, item: _BrowserItem) -> None:
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
