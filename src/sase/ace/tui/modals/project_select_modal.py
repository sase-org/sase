"""Project/PR selection modal with filtering for the ace TUI."""

import asyncio
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rich.text import Text
from sase.status_state_machine import remove_workspace_suffix
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from sase.core.paths import sase_projects_dir
from sase.project_display_names import (
    ProjectDisplayProjection,
    ProjectDisplaySnapshot,
    humanize_cl_name,
)

from ...changespec import ChangeSpec, find_all_changespecs, parse_project_file
from ...changespec.project_spec_path import (
    archive_project_spec_filename,
    preferred_project_spec_path,
)
from .base import FilterInput, OptionListNavigationMixin
from .confirm_delete_modal import ConfirmDeleteModal
from .project_discovery import load_launchable_project_snapshot


@dataclass(frozen=True)
class _ProjectSelectData:
    """Worker-loaded identity and presentation snapshot for the picker."""

    projects: tuple[ProjectDisplayProjection, ...]
    changespecs: tuple[ChangeSpec, ...]
    project_display_snapshot: ProjectDisplaySnapshot


def _load_project_select_data() -> _ProjectSelectData:
    """Load all picker inputs off the Textual UI thread."""
    project_display_snapshot, projects = load_launchable_project_snapshot()
    return _ProjectSelectData(
        projects=projects,
        changespecs=tuple(find_all_changespecs()),
        project_display_snapshot=project_display_snapshot,
    )


def show_project_select_modal(
    owner: object,
    callback: object,
    *,
    include_all: bool = False,
    exclude_project_names: Iterable[str] = (),
) -> None:
    """Worker-load picker data, then mount the pure presentation modal."""
    exclusions = tuple(exclude_project_names)

    async def _load_and_show() -> None:
        data = await asyncio.to_thread(_load_project_select_data)
        owner.push_screen(  # type: ignore[attr-defined]
            ProjectSelectModal(
                data,
                include_all=include_all,
                exclude_project_names=exclusions,
            ),
            callback,
        )

    from sase.ace.tui.util.pump_tasks import spawn_pump_free_task

    task = spawn_pump_free_task(
        owner,
        _load_and_show(),
        name="project-select-load",
        registry_attr="_project_select_tasks",
    )
    if task is None:
        # Narrow non-running-loop callers (primarily unit-test adapters) still
        # get deterministic behavior. Real Textual actions always take the
        # worker path above.
        owner.push_screen(  # type: ignore[attr-defined]
            ProjectSelectModal(
                _load_project_select_data(),
                include_all=include_all,
                exclude_project_names=exclusions,
            ),
            callback,
        )


@dataclass
class SelectionItem:
    """An item that can be selected in the modal."""

    display_name: str  # What to show in the list (e.g., "[P] myproject")
    item_type: Literal["project", "cl", "home", "all"]  # Type for processing
    project_name: str  # Project name
    cl_name: str | None  # ChangeSpec name if type is "cl", None for projects/home
    project_label: str | None = None
    selection_label: str | None = None

    @property
    def option_id(self) -> str:
        """Return a canonical identity for the interactive option row."""
        if self.item_type == "cl":
            return f"cl:{self.project_name}:{self.cl_name or ''}"
        return f"{self.item_type}:{self.project_name}"


@dataclass
class ProjectSelectResult:
    """Result from the project selection modal."""

    selection: SelectionItem | str
    open_in_editor: bool = False


class ProjectSelectModal(
    OptionListNavigationMixin, ModalScreen[ProjectSelectResult | None]
):
    """Modal for selecting project or PR with filtering."""

    _option_list_id = "selection-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("ctrl+d", "delete_project", "Delete Project", priority=True),
        Binding("ctrl+g", "select_and_edit", "Select & Edit", priority=True),
    ]

    def __init__(
        self,
        data: _ProjectSelectData,
        *,
        include_all: bool = False,
        exclude_project_names: Iterable[str] = (),
    ) -> None:
        """Initialize the project selection modal.

        Args:
            include_all: If True, insert an "ALL" item at position 0.
            exclude_project_names: Exact project names to omit from project rows.
        """
        super().__init__()
        self.all_items: list[SelectionItem] = []
        self._include_all = include_all
        self._exclude_project_names = frozenset(exclude_project_names)
        self._data = data
        self._load_items()

    def _load_items(self) -> None:
        """Load all projects and PRs."""
        # Add "ALL" option first when requested
        if self._include_all:
            self.all_items.append(
                SelectionItem(
                    display_name="[*] ALL",
                    item_type="all",
                    project_name="",
                    cl_name=None,
                )
            )

        for project in sorted(self._data.projects, key=lambda item: item.sort_key):
            if project.project_key in self._exclude_project_names:
                continue
            self.all_items.append(
                SelectionItem(
                    display_name=f"[P] {project.project_label}",
                    item_type="project",
                    project_name=project.project_key,
                    cl_name=None,
                    project_label=project.project_label,
                    selection_label=project.project_label,
                )
            )

        # Load PRs with WIP, Draft, Ready, or Mailed status
        changespec_items: list[SelectionItem] = []
        for cs in self._data.changespecs:
            base_status = remove_workspace_suffix(cs.status)
            if base_status in ("WIP", "Draft", "Ready", "Mailed"):
                display_cl_name = humanize_cl_name(
                    cs.name,
                    snapshot=self._data.project_display_snapshot,
                )
                changespec_items.append(
                    SelectionItem(
                        display_name=(f"[PR] {display_cl_name} [{base_status}]"),
                        item_type="cl",
                        project_name=cs.project_basename,
                        cl_name=cs.name,
                        project_label=self._data.project_display_snapshot.label_for(
                            cs.project_basename
                        ),
                        selection_label=display_cl_name,
                    )
                )
        changespec_items.sort(
            key=lambda item: (
                item.display_name.casefold(),
                item.project_name,
                item.cl_name or "",
            )
        )
        self.all_items.extend(changespec_items)

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="project-select-container"):
            yield Static(
                self._build_title(len(self.all_items)),
                id="project-select-title",
            )
            yield FilterInput(
                placeholder="Type to filter projects & PRs…",
                id="filter-input",
            )
            yield Static(
                "Enter launch · ↑/↓ move · type a name to create a PR",
                id="project-select-hint",
            )
            yield OptionList(
                *self._create_options(self.all_items),
                id="selection-list",
            )
            yield Static(
                self._build_empty_state(""),
                id="project-select-empty",
            )
            yield Static(
                "Enter launch · ^G edit · ^D delete · Esc close",
                id="project-select-footer",
            )

    def _create_styled_label(self, display_name: str) -> Text:
        """Create styled text for an option label."""
        text = Text()
        if display_name.startswith("[*]"):
            text.append("[*]", style="bold #D787FF")  # Magenta for ALL
            text.append(display_name[3:])
        elif display_name.startswith("[H]"):
            text.append("[H]", style="bold #FFD700")  # Gold for home
            text.append(display_name[3:])
        elif display_name.startswith("[P]"):
            text.append("[P]", style="bold #87D7FF")  # Cyan for projects
            text.append(display_name[3:])
        elif display_name.startswith("[PR]"):
            text.append("[PR]", style="bold #00D7AF")  # Green for PRs
            text.append(display_name[4:])
        else:
            text.append(display_name)
        return text

    def _create_options(self, items: list[SelectionItem]) -> list[Option]:
        """Create options from items."""
        return [
            Option(self._create_styled_label(item.display_name), id=item.option_id)
            for item in items
        ]

    def _build_title(self, count: int) -> Text:
        """Build the icon'd title with a live match count."""
        text = Text()
        text.append("✦ ", style="bold #FFD700")
        text.append("Select Project or PR", style="bold white")
        text.append("  ·  ", style="dim")
        plural = "match" if count == 1 else "matches"
        text.append(f"{count} {plural}", style="dim #87D7FF")
        return text

    def _build_empty_state(self, query: str) -> Text:
        """Build the empty-state hint shown when nothing matches."""
        text = Text()
        text.append("No matching projects", style="dim italic")
        if query:
            text.append(" — press ", style="dim italic")
            text.append("Enter", style="bold #FFD700")
            text.append(" to use ", style="dim italic")
            text.append(f"“{query}”", style="italic #00D7AF")
            text.append(" as a custom name", style="dim italic")
        return text

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
        self._refresh_empty_visibility()

    def _apply_filter(self, query: str) -> None:
        """Rebuild the option list and chrome for the current filter query."""
        filtered_items = self._get_filtered_items(query)
        option_list = self.query_one("#selection-list", OptionList)
        option_list.clear_options()
        for item in filtered_items:
            option_list.add_option(
                Option(self._create_styled_label(item.display_name), id=item.option_id)
            )
        if filtered_items:
            option_list.highlighted = 0
        self.query_one("#project-select-title", Static).update(
            self._build_title(len(filtered_items))
        )
        self.query_one("#project-select-empty", Static).update(
            self._build_empty_state(query.strip())
        )
        self._refresh_empty_visibility()

    def _refresh_empty_visibility(self) -> None:
        """Toggle the option list and empty-state against each other."""
        option_list = self.query_one("#selection-list", OptionList)
        empty = self.query_one("#project-select-empty", Static)
        is_empty = option_list.option_count == 0
        empty.display = is_empty
        option_list.display = not is_empty

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input change - update the option list."""
        if event.input.id != "filter-input":
            return
        self._apply_filter(event.value)

    def on_key(self, event: events.Key) -> None:
        """Forward list navigation keys while the filter input has focus."""
        if event.key in ("down", "ctrl+n"):
            event.prevent_default()
            event.stop()
            self.action_next_option()
        elif event.key in ("up", "ctrl+p"):
            event.prevent_default()
            event.stop()
            self.action_prev_option()

    def _dismiss_selection(
        self, item: SelectionItem | str, *, open_in_editor: bool = False
    ) -> None:
        """Dismiss the modal with a ProjectSelectResult.

        Args:
            item: The selected item or custom string.
            open_in_editor: Whether to open the prompt in an editor.
        """
        self.dismiss(ProjectSelectResult(selection=item, open_in_editor=open_in_editor))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input - select highlighted item or use as custom ChangeSpec."""
        filter_text = event.value.strip()
        filtered_items = self._get_filtered_items(filter_text)

        if filtered_items:
            # Select the highlighted option or first match
            option_list = self.query_one("#selection-list", OptionList)
            highlighted = option_list.highlighted
            if highlighted is not None and 0 <= highlighted < len(filtered_items):
                self._dismiss_selection(filtered_items[highlighted])
            else:
                self._dismiss_selection(filtered_items[0])
        elif filter_text:
            # No match but user typed something - use input as custom ChangeSpec name
            self._dismiss_selection(filter_text)
        else:
            # Empty input and no items - cancel
            self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (Enter or click)."""
        if event.option and event.option.id is not None:
            # Get the current filtered items
            filter_input = self.query_one("#filter-input", FilterInput)
            filtered_items = self._get_filtered_items(filter_input.value)
            selected = next(
                (item for item in filtered_items if item.option_id == event.option.id),
                None,
            )
            if selected is not None:
                self._dismiss_selection(selected)

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

    def action_select_and_edit(self) -> None:
        """Select the highlighted item and open the prompt in an editor."""
        filter_text = self.query_one("#filter-input", FilterInput).value.strip()
        filtered_items = self._get_filtered_items(filter_text)

        if filtered_items:
            option_list = self.query_one("#selection-list", OptionList)
            highlighted = option_list.highlighted
            if highlighted is not None and 0 <= highlighted < len(filtered_items):
                self._dismiss_selection(
                    filtered_items[highlighted], open_in_editor=True
                )
            else:
                self._dismiss_selection(filtered_items[0], open_in_editor=True)
        elif filter_text:
            self._dismiss_selection(filter_text, open_in_editor=True)
        else:
            self.dismiss(None)

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

        # Check if project file or archive file contains any ChangeSpecs
        project_label = self._data.project_display_snapshot.label_for(item.project_name)
        # File paths and deletion targets stay canonical.
        project_dir = sase_projects_dir() / item.project_name
        active_path = Path(
            preferred_project_spec_path(str(project_dir), item.project_name)
        )
        archive_path = Path(
            preferred_project_spec_path(
                str(project_dir), item.project_name, archive=True
            )
        )
        if not archive_path.exists():
            archive_path = project_dir / archive_project_spec_filename(
                item.project_name
            )
        changespecs = parse_project_file(str(active_path))
        if archive_path.exists():
            changespecs.extend(parse_project_file(str(archive_path)))
        if changespecs:
            self.notify(
                f"Cannot delete project '{project_label}': file contains ChangeSpecs",
                severity="error",
            )
            return

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            # Delete the project spec file and archive file
            os.unlink(active_path)
            if archive_path.exists():
                os.unlink(archive_path)
            # Remove parent directory if empty
            try:
                os.rmdir(active_path.parent)
            except OSError:
                pass  # Directory not empty, that's fine
            # Remove from all_items and refresh display
            self.all_items.remove(item)
            filter_input = self.query_one("#filter-input", FilterInput)
            self._apply_filter(filter_input.value)
            self.notify(f"Deleted project '{project_label}'", severity="information")

        self.app.push_screen(ConfirmDeleteModal(project_label), _on_confirm)
