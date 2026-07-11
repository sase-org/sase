"""Modal for choosing where to save the current draft as an xprompt."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.xprompt import get_all_prompts
from sase.xprompt.loader import get_all_project_local_prompts
from sase.xprompt.save import SaveTargetFormat
from sase.xprompt.workflow_models import Workflow

from .base import FilterInput, OptionListNavigationMixin
from .xprompt_browser_helpers import classify_source, resolve_source_to_file_path


@dataclass(frozen=True)
class XPromptSaveTarget:
    """A selected save target."""

    kind: Literal["create", "overwrite", "create_snippet", "write"]
    name: str = ""
    path: str = ""
    target_format: SaveTargetFormat | None = None
    entry_name: str | None = None
    display_path: str = ""
    exists: bool = False


@dataclass(frozen=True)
class _XPromptSaveRow:
    """One xprompt row in the save-target picker."""

    name: str
    workflow: Workflow
    source_category: str
    source_path: str | None
    display_path: str
    target: XPromptSaveTarget | None
    disabled_reason: str | None = None

    @property
    def is_selectable(self) -> bool:
        return self.target is not None and self.disabled_reason is None


class _SaveTargetFilterInput(FilterInput):
    """Filter input with forwarding for save-target modal actions."""

    BINDINGS = [
        *FilterInput.BINDINGS,
        ("ctrl+d", "scroll_preview_down", "Scroll Down"),
        ("ctrl+u", "scroll_preview_up_or_clear", "Scroll Up/Clear"),
        ("ctrl+n", "forward('next_option')", "Next"),
        ("ctrl+p", "forward('prev_option')", "Prev"),
        ("enter", "forward('select_target')", "Select"),
    ]

    def action_forward(self, action_name: str) -> None:
        modal = self.screen
        if isinstance(modal, XPromptSaveTargetModal):
            getattr(modal, f"action_{action_name}")()

    def action_scroll_preview_down(self) -> None:
        modal = self.screen
        if isinstance(modal, XPromptSaveTargetModal):
            modal.scroll_preview_down()

    def action_scroll_preview_up_or_clear(self) -> None:
        modal = self.screen
        if not isinstance(modal, XPromptSaveTargetModal):
            return
        scroll = modal.query_one("#save-target-preview-scroll", VerticalScroll)
        if scroll.scroll_y > 0:
            modal.scroll_preview_up()
        elif self.cursor_position > 0:
            self.value = self.value[self.cursor_position :]
            self.cursor_position = 0


class XPromptSaveTargetModal(
    OptionListNavigationMixin, ModalScreen[XPromptSaveTarget | None]
):
    """Modal for selecting an existing xprompt to overwrite or creating one."""

    _option_list_id = "save-target-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_target", "Select"),
        ("ctrl+d", "scroll_preview_down", "Scroll Down"),
        ("ctrl+u", "scroll_preview_up", "Scroll Up"),
    ]

    def __init__(
        self,
        rows: list[_XPromptSaveRow] | None = None,
        *,
        project: str | None = None,
        pane_count: int = 0,
        has_frontmatter: bool = False,
        allow_create_snippet: bool = False,
    ) -> None:
        super().__init__()
        self._rows = rows if rows is not None else _load_xprompt_save_rows(project)
        self._pane_count = pane_count
        self._has_frontmatter = has_frontmatter
        self._allow_create_snippet = allow_create_snippet
        self._visible_rows: list[_XPromptSaveRow] = []

    def compose(self) -> ComposeResult:
        with Container(id="save-target-container"):
            yield Label("Save draft as xprompt", id="save-target-title")
            yield _SaveTargetFilterInput(
                placeholder="Type to filter...",
                id="save-target-filter-input",
            )
            with Horizontal(id="save-target-panels"):
                with Vertical(id="save-target-list-panel"):
                    yield OptionList(id="save-target-list")
                with Vertical(id="save-target-preview-panel"):
                    with VerticalScroll(id="save-target-preview-scroll"):
                        yield Static("", id="save-target-preview")
            yield Static(
                "^n/^p navigate • enter select • ^d/^u scroll • Esc cancel",
                id="save-target-hints",
            )

    def on_mount(self) -> None:
        self.query_one("#save-target-filter-input", _SaveTargetFilterInput).focus()
        self._rebuild_options("")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._rebuild_options(event.value)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        self._update_preview_for_highlight()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_select_target()

    def action_next_option(self) -> None:
        option_list = self.query_one("#save-target-list", OptionList)
        current = option_list.highlighted
        if current is None:
            self._skip_to_first_selectable(option_list)
            return
        for index in range(current + 1, option_list.option_count):
            if self._option_is_selectable(option_list, index):
                option_list.highlighted = index
                return

    def action_prev_option(self) -> None:
        option_list = self.query_one("#save-target-list", OptionList)
        current = option_list.highlighted
        if current is None:
            return
        for index in range(current - 1, -1, -1):
            if self._option_is_selectable(option_list, index):
                option_list.highlighted = index
                return

    def action_select_target(self) -> None:
        target = self._get_highlighted_target()
        if target is not None:
            self.dismiss(target)

    def _rebuild_options(self, filter_text: str) -> None:
        option_list = self.query_one("#save-target-list", OptionList)
        option_list.clear_options()
        options = self._create_options(filter_text)
        for option in options:
            option_list.add_option(option)
        self._skip_to_first_selectable(option_list)
        self._update_preview_for_highlight()

    def _create_options(self, filter_text: str = "") -> list[Option]:
        filter_lower = filter_text.casefold()
        options: list[Option] = [
            Option(
                Text("  +  Create new xprompt...", style="bold #FFD700"),
                id="__create__",
            )
        ]
        if self._allow_create_snippet:
            options.append(
                Option(
                    Text("  +  Create a new snippet...", style="bold #FFD700"),
                    id="__create_snippet__",
                )
            )

        filtered = [
            row
            for row in self._rows
            if not filter_lower or _row_matches_filter(row, filter_lower)
        ]
        self._visible_rows = filtered

        for category, rows in _group_rows(filtered):
            header = Text(f"-- {category} --", style="bold dim")
            options.append(Option(header, id=f"__header__{category}", disabled=True))
            for index, row in enumerate(filtered):
                if row.source_category != category:
                    continue
                options.append(
                    Option(
                        _row_label(row),
                        id=f"row__{index}",
                        disabled=not row.is_selectable,
                    )
                )
        return options

    def _skip_to_first_selectable(self, option_list: OptionList) -> None:
        for index in range(option_list.option_count):
            if self._option_is_selectable(option_list, index):
                option_list.highlighted = index
                return
        option_list.highlighted = None

    def _option_is_selectable(self, option_list: OptionList, index: int) -> bool:
        try:
            option = option_list.get_option_at_index(index)
        except Exception:
            return False
        return bool(option.id) and not getattr(option, "disabled", False)

    def _get_highlighted_target(self) -> XPromptSaveTarget | None:
        option_list = self.query_one("#save-target-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        if getattr(option, "disabled", False) or option.id is None:
            return None
        option_id = str(option.id)
        if option_id == "__create__":
            return XPromptSaveTarget(kind="create")
        if option_id == "__create_snippet__":
            return XPromptSaveTarget(kind="create_snippet")
        if not option_id.startswith("row__"):
            return None
        index = int(option_id.removeprefix("row__"))
        if 0 <= index < len(self._visible_rows):
            return self._visible_rows[index].target
        return None

    def _get_highlighted_row(self) -> _XPromptSaveRow | None:
        option_list = self.query_one("#save-target-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        if not option.id or str(option.id) in {"__create__", "__create_snippet__"}:
            return None
        option_id = str(option.id)
        if not option_id.startswith("row__"):
            return None
        index = int(option_id.removeprefix("row__"))
        return (
            self._visible_rows[index] if 0 <= index < len(self._visible_rows) else None
        )

    def _update_preview_for_highlight(self) -> None:
        preview = self.query_one("#save-target-preview", Static)
        target = self._get_highlighted_target()
        row = self._get_highlighted_row()
        if target is not None and target.kind == "create":
            preview.update(Syntax(self._create_preview(), "markdown", theme="monokai"))
            return
        if target is not None and target.kind == "create_snippet":
            preview.update(
                Syntax(self._create_snippet_preview(), "markdown", theme="monokai")
            )
            return
        if row is None:
            preview.update("")
            return
        preview.update(
            Syntax(self._overwrite_preview(row), "markdown", theme="monokai")
        )

    def _create_preview(self) -> str:
        return "\n".join(
            [
                "# Create New XPrompt",
                "",
                "Choose a location and name after selecting this row.",
                "",
                self._draft_summary(),
            ]
        )

    def _create_snippet_preview(self) -> str:
        lines = [
            "# Create New Snippet",
            "",
            "Save the current prompt pane as an ACE snippet under",
            "`ace.snippets`. Choose a config file and trigger name after",
            "selecting this row.",
            "",
        ]
        if self._pane_count > 1:
            # The xprompt body spans every pane, but a snippet is a single
            # template, so only the active pane is saved here.
            lines.append(
                "Snippet source: the current pane only "
                f"({self._pane_count} panes in the draft)."
            )
        else:
            lines.append("Snippet source: the current prompt pane.")
        return "\n".join(lines)

    def _overwrite_preview(self, row: _XPromptSaveRow) -> str:
        workflow = row.workflow
        lines = [
            f"# Will overwrite: {row.name}",
            "",
            f"Source: {row.display_path}",
            self._draft_summary(),
            "",
        ]
        if row.disabled_reason:
            lines.extend([f"Disabled: {row.disabled_reason}", ""])
        if workflow.is_simple_xprompt():
            lines.extend(
                ["## Existing Content", "", workflow.get_prompt_part_content()]
            )
        else:
            lines.extend(["## Existing Workflow", "", f"{len(workflow.steps)} steps"])
        return "\n".join(lines)

    def _draft_summary(self) -> str:
        frontmatter = "yes" if self._has_frontmatter else "no"
        pane_word = "pane" if self._pane_count == 1 else "panes"
        return f"Draft: {self._pane_count} {pane_word}, frontmatter: {frontmatter}"

    def scroll_preview_down(self) -> None:
        scroll = self.query_one("#save-target-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def scroll_preview_up(self) -> None:
        scroll = self.query_one("#save-target-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)


def _load_xprompt_save_rows(project: str | None = None) -> list[_XPromptSaveRow]:
    """Load save-target rows from the xprompt catalog."""
    prompts = get_all_prompts(project=project)
    prompts = {**get_all_project_local_prompts(), **prompts}

    rows: list[_XPromptSaveRow] = []
    for name, workflow in prompts.items():
        if not workflow.is_simple_xprompt():
            continue
        category, display_path, _editable = classify_source(workflow.source_path)
        rows.append(
            _XPromptSaveRow(
                name=name,
                workflow=workflow,
                source_category=category,
                source_path=workflow.source_path,
                display_path=display_path,
                target=_target_for_workflow(name, workflow, project=project),
                disabled_reason=_disabled_reason(name, workflow, project=project),
            )
        )
    return rows


def _target_for_workflow(
    name: str, workflow: Workflow, *, project: str | None
) -> XPromptSaveTarget | None:
    if not workflow.is_simple_xprompt():
        return None
    path = resolve_source_to_file_path(workflow.source_path)
    if path is None:
        return None
    if _is_config_source(workflow.source_path):
        return XPromptSaveTarget(
            kind="overwrite",
            name=name,
            path=path,
            target_format=SaveTargetFormat.CONFIG,
            entry_name=_config_entry_name(name, workflow.source_path, project),
            display_path=_short_display_path(path),
        )
    if Path(path).suffix == ".md":
        return XPromptSaveTarget(
            kind="overwrite",
            name=name,
            path=path,
            target_format=SaveTargetFormat.MARKDOWN,
            display_path=_short_display_path(path),
        )
    return None


def _disabled_reason(
    name: str, workflow: Workflow, *, project: str | None
) -> str | None:
    path = resolve_source_to_file_path(workflow.source_path)
    if path is None:
        return "source path could not be resolved"
    target = _target_for_workflow(name, workflow, project=project)
    if target is None or target.target_format is None:
        return "unsupported source format"
    file_path = Path(path)
    if file_path.exists():
        if not os.access(file_path, os.W_OK):
            return "source file is read-only"
    else:
        parent = file_path.parent
        if not parent.exists() or not os.access(parent, os.W_OK):
            return "source directory is not writable"
    return None


def _is_config_source(source_path: str | None) -> bool:
    if source_path in {"config", "local_config", "default_config"}:
        return True
    if source_path is None:
        return False
    return source_path.startswith(
        ("config_overlay:", "project_local_config:", "plugin_config:")
    )


def _config_entry_name(
    name: str,
    source_path: str | None,
    project: str | None,
) -> str:
    if source_path and source_path.startswith("project_local_config:"):
        project_name = source_path.removeprefix("project_local_config:")
        prefix = f"{project_name}/"
        return name.removeprefix(prefix)
    if source_path == "local_config" and project:
        return name.removeprefix(f"{project}/")
    return name


def _group_rows(rows: list[_XPromptSaveRow]) -> list[tuple[str, list[_XPromptSaveRow]]]:
    groups: dict[str, list[_XPromptSaveRow]] = {}
    for row in rows:
        groups.setdefault(row.source_category, []).append(row)
    for grouped_rows in groups.values():
        grouped_rows.sort(key=lambda row: row.name)

    known_order = [
        "CWD .xprompts/",
        "CWD xprompts/",
        "Home ~/.xprompts/",
        "Home ~/xprompts/",
    ]
    ordered: list[tuple[str, list[_XPromptSaveRow]]] = []
    seen: set[str] = set()
    for category in known_order:
        if category in groups:
            ordered.append((category, groups[category]))
            seen.add(category)
    for category in sorted(groups):
        if category.startswith("Project (") and category not in seen:
            ordered.append((category, groups[category]))
            seen.add(category)
    if "User sase.yml" in groups and "User sase.yml" not in seen:
        ordered.append(("User sase.yml", groups["User sase.yml"]))
        seen.add("User sase.yml")
    for category in sorted(groups):
        if category.startswith("Plugin (") and category not in seen:
            ordered.append((category, groups[category]))
            seen.add(category)
    if "Built-in" in groups and "Built-in" not in seen:
        ordered.append(("Built-in", groups["Built-in"]))
        seen.add("Built-in")
    for category in sorted(groups):
        if category not in seen:
            ordered.append((category, groups[category]))
    return ordered


def _row_matches_filter(row: _XPromptSaveRow, filter_lower: str) -> bool:
    parts = [
        row.name,
        row.workflow.description or "",
        row.display_path,
        row.disabled_reason or "",
    ]
    return filter_lower in "\n".join(parts).casefold()


def _row_label(row: _XPromptSaveRow) -> Text:
    text = Text()
    text.append("  # ", style="bold #87D7FF")
    text.append(row.name, style="bold" if row.is_selectable else "dim")
    text.append(f"\n     {row.display_path}", style="dim")
    if row.disabled_reason:
        text.append(f"  ({row.disabled_reason})", style="italic #888888")
    return text


def _short_display_path(path: str) -> str:
    home = str(Path.home())
    cwd = str(Path.cwd())
    if path.startswith(cwd + "/"):
        return "./" + path[len(cwd) + 1 :]
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


__all__ = [
    "XPromptSaveTarget",
    "XPromptSaveTargetModal",
]
