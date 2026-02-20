"""Project/CL selection modal with filtering for the ace TUI."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rich.text import Text
from sase.status_state_machine import remove_workspace_suffix
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from ...changespec import find_all_changespecs, parse_project_file
from .base import FilterInput, OptionListNavigationMixin
from .confirm_delete_modal import ConfirmDeleteModal


@dataclass
class SelectionItem:
    """An item that can be selected in the modal."""

    display_name: str  # What to show in the list (e.g., "[P] myproject")
    item_type: Literal["project", "cl", "home"]  # Type for processing
    project_name: str  # Project name
    cl_name: str | None  # CL name if type is "cl", None for projects/home


class ProjectSelectModal(
    OptionListNavigationMixin, ModalScreen[SelectionItem | str | None]
):
    """Modal for selecting project or CL with filtering."""

    _option_list_id = "selection-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("ctrl+d", "delete_project", "Delete Project", priority=True),
    ]

    def __init__(self) -> None:
        """Initialize the project selection modal."""
        super().__init__()
        self.all_items: list[SelectionItem] = []
        self._load_items()

    def _load_items(self) -> None:
        """Load all projects and CLs."""
        # Add home directory option first
        self.all_items.append(
            SelectionItem(
                display_name="[H] ~ (home directory)",
                item_type="home",
                project_name="home",
                cl_name=None,
            )
        )

        # Load projects from ~/.sase/projects/<p>/<p>.gp
        projects_dir = Path.home() / ".sase" / "projects"
        if projects_dir.exists():
            for project_dir in sorted(projects_dir.iterdir()):
                if project_dir.is_dir():
                    project_name = project_dir.name
                    gp_file = project_dir / f"{project_name}.gp"
                    if gp_file.exists():
                        self.all_items.append(
                            SelectionItem(
                                display_name=f"[P] {project_name}",
                                item_type="project",
                                project_name=project_name,
                                cl_name=None,
                            )
                        )

        # Load CLs with WIP, Draft, Ready, or Mailed status
        for cs in find_all_changespecs():
            base_status = remove_workspace_suffix(cs.status)
            if base_status in ("WIP", "Draft", "Ready", "Mailed"):
                self.all_items.append(
                    SelectionItem(
                        display_name=f"[C] {cs.name} [{base_status}]",
                        item_type="cl",
                        project_name=cs.project_basename,
                        cl_name=cs.name,
                    )
                )

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Select Project or CL", id="modal-title")
            yield FilterInput(placeholder="Type to filter...", id="filter-input")
            yield OptionList(
                *self._create_options(self.all_items),
                id="selection-list",
            )

    def _create_styled_label(self, display_name: str) -> Text:
        """Create styled text for an option label."""
        text = Text()
        if display_name.startswith("[H]"):
            text.append("[H]", style="bold #FFD700")  # Gold for home
            text.append(display_name[3:])
        elif display_name.startswith("[P]"):
            text.append("[P]", style="bold #87D7FF")  # Cyan for projects
            text.append(display_name[3:])
        elif display_name.startswith("[C]"):
            text.append("[C]", style="bold #00D7AF")  # Green for CLs
            text.append(display_name[3:])
        else:
            text.append(display_name)
        return text

    def _create_options(self, items: list[SelectionItem]) -> list[Option]:
        """Create options from items."""
        return [
            Option(self._create_styled_label(item.display_name), id=str(i))
            for i, item in enumerate(items)
        ]

    def _get_filtered_items(self, filter_text: str) -> list[SelectionItem]:
        """Get items that match the filter text."""
        if not filter_text:
            return self.all_items
        filter_lower = filter_text.lower()
        return [
            item for item in self.all_items if filter_lower in item.display_name.lower()
        ]

    def on_mount(self) -> None:
        """Focus the input on mount."""
        filter_input = self.query_one("#filter-input", FilterInput)
        filter_input.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input change - update the option list."""
        filtered_items = self._get_filtered_items(event.value)
        option_list = self.query_one("#selection-list", OptionList)
        option_list.clear_options()
        for i, item in enumerate(filtered_items):
            option_list.add_option(
                Option(self._create_styled_label(item.display_name), id=str(i))
            )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input - select highlighted item or use as custom CL."""
        filter_text = event.value.strip()
        filtered_items = self._get_filtered_items(filter_text)

        if filtered_items:
            # Select the highlighted option or first match
            option_list = self.query_one("#selection-list", OptionList)
            highlighted = option_list.highlighted
            if highlighted is not None and 0 <= highlighted < len(filtered_items):
                self.dismiss(filtered_items[highlighted])
            else:
                self.dismiss(filtered_items[0])
        elif filter_text:
            # No match but user typed something - use input as custom CL name
            self.dismiss(filter_text)
        else:
            # Empty input and no items - cancel
            self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (Enter or click)."""
        if event.option and event.option.id is not None:
            # Get the current filtered items
            filter_input = self.query_one("#filter-input", FilterInput)
            filtered_items = self._get_filtered_items(filter_input.value)
            idx = int(event.option.id)
            if 0 <= idx < len(filtered_items):
                self.dismiss(filtered_items[idx])

    def _get_highlighted_item(self) -> SelectionItem | None:
        """Get the currently highlighted SelectionItem."""
        option_list = self.query_one("#selection-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        filter_input = self.query_one("#filter-input", FilterInput)
        filtered_items = self._get_filtered_items(filter_input.value)
        if 0 <= highlighted < len(filtered_items):
            return filtered_items[highlighted]
        return None

    def action_delete_project(self) -> None:
        """Delete the project file for the highlighted item."""
        item = self._get_highlighted_item()
        if item is None:
            self.notify("No item selected", severity="error")
            return

        if item.item_type != "project":
            self.notify(
                "Can only delete project files, not ChangeSpecs/home",
                severity="error",
            )
            return

        # Check if project file contains any ChangeSpecs
        gp_path = (
            Path.home()
            / ".sase"
            / "projects"
            / item.project_name
            / f"{item.project_name}.gp"
        )
        changespecs = parse_project_file(str(gp_path))
        if changespecs:
            self.notify(
                f"Cannot delete project '{item.project_name}': file contains ChangeSpecs",
                severity="error",
            )
            return

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            # Delete the .gp file
            os.unlink(gp_path)
            # Remove parent directory if empty
            try:
                os.rmdir(gp_path.parent)
            except OSError:
                pass  # Directory not empty, that's fine
            # Remove from all_items and refresh display
            self.all_items.remove(item)
            filter_input = self.query_one("#filter-input", FilterInput)
            filtered_items = self._get_filtered_items(filter_input.value)
            option_list = self.query_one("#selection-list", OptionList)
            option_list.clear_options()
            for i, fi in enumerate(filtered_items):
                option_list.add_option(
                    Option(self._create_styled_label(fi.display_name), id=str(i))
                )
            self.notify(
                f"Deleted project '{item.project_name}'", severity="information"
            )

        self.app.push_screen(ConfirmDeleteModal(item.project_name), _on_confirm)
