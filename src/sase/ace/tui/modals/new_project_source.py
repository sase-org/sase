"""Source-stage candidate list, filter, detail card, and provider probes."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable, Mapping
from typing import Any

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from sase import workspace_provider
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks, spawn_pump_free_task
from sase.project_accents import accent_among_keys, project_accent
from sase.project_onboarding import CandidateInputs

from .base import FilterInput
from .new_project_rendering import render_source_detail, render_source_row
from .new_project_source_model import (
    SourceRow,
    SourceView,
    build_source_view,
    hidden_footer,
)

_ROW_REGISTRY = "_new_project_source_tasks"


class _SourceFilterInput(FilterInput):
    """Input that routes navigation and selection keys to its Source widget."""

    def on_key(self, event: events.Key) -> None:
        source = self._source()
        if source is None:
            return
        actions = {
            "up": source.action_prev_row,
            "ctrl+p": source.action_prev_row,
            "down": source.action_next_row,
            "ctrl+n": source.action_next_row,
            "escape": source.focus_list,
            "enter": source.choose_highlighted,
        }
        action = actions.get(event.key)
        if action is not None:
            event.stop()
            event.prevent_default()
            action()

    def _source(self) -> NewProjectSource | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, NewProjectSource):
                return node
            node = getattr(node, "parent", None)
        return None


class NewProjectSource(Vertical):
    """Interactive Source-stage list fed by cache-first candidate inputs."""

    class RowChosen(Message):
        """A candidate row was selected by the user."""

        def __init__(self, row: SourceRow) -> None:
            super().__init__()
            self.row = row

    BINDINGS = [
        ("j", "next_row", "Next"),
        ("down", "next_row", "Next"),
        ("ctrl+n", "next_row", "Next"),
        ("k", "prev_row", "Previous"),
        ("up", "prev_row", "Previous"),
        ("ctrl+p", "prev_row", "Previous"),
        ("/", "focus_filter", "Filter"),
        ("f", "toggle_forks", "Forks"),
        (".", "toggle_all", "All"),
        ("R", "refresh", "Refresh"),
        ("t", "run_remedy", "Provider login"),
    ]

    def __init__(self, workflow_type: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.workflow_type = workflow_type
        self._inputs: CandidateInputs | None = None
        self._pending_owners: frozenset[str] = frozenset()
        self._filter_text = ""
        self._reveal_forks = False
        self._reveal_all = False
        self._rows: dict[str, SourceRow] = {}
        self._view = SourceView((), (), (), 0)
        self._selected_row_id: str | None = None
        self._probe_cache: dict[tuple[str, str], Any] = {}
        self._probe_errors: dict[tuple[str, str], str] = {}
        self._probing: set[tuple[str, str]] = set()
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._refresh_callback: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        yield _SourceFilterInput(
            placeholder="Filter — or paste owner/repo, a GitHub URL, or a local path",
            id="new-project-filter",
        )
        yield OptionList(id="new-project-source-list")
        yield Static("", id="new-project-hidden-footer")
        yield Static("", id="new-project-source-detail")

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._rebuild()

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        cancel_pump_free_tasks(self)

    def set_inputs(
        self,
        inputs: CandidateInputs | None,
        *,
        pending_owners: frozenset[str] = frozenset(),
    ) -> None:
        """Update rows when cached or revalidated provider data arrives."""
        self._inputs = inputs
        self._pending_owners = pending_owners
        self._rebuild()

    def set_refresh_callback(self, callback: Callable[[], None]) -> None:
        """Install the owner responsible for forcing a provider refresh."""
        self._refresh_callback = callback

    def cached_probe(self, workflow_type: str, ref: str) -> Any | None:
        """Return a previously observed provider probe, if Source already has one."""
        return self._probe_cache.get((workflow_type, ref))

    def remember_probe(self, workflow_type: str, ref: str, probe: Any) -> None:
        """Store an off-thread probe so later Configure previews can reuse it."""
        self._probe_cache[(workflow_type, ref)] = probe

    def focus_filter(self) -> None:
        """Focus the filter without changing the current highlight."""
        self.query_one("#new-project-filter", Input).focus()

    def focus_list(self) -> None:
        """Return focus to the candidate list."""
        self.query_one("#new-project-source-list", OptionList).focus()

    def paste_filter(self, text: str) -> None:
        """Focus the filter and replace it with bracketed-paste contents."""
        control = self.query_one("#new-project-filter", Input)
        control.value = text
        control.focus()

    def action_next_row(self) -> None:
        self.query_one("#new-project-source-list", OptionList).action_cursor_down()

    def action_prev_row(self) -> None:
        self.query_one("#new-project-source-list", OptionList).action_cursor_up()

    def action_focus_filter(self) -> None:
        self.focus_filter()

    def action_toggle_forks(self) -> None:
        self._reveal_forks = not self._reveal_forks
        self._rebuild()

    def action_toggle_all(self) -> None:
        self._reveal_all = not self._reveal_all
        if self._reveal_all:
            self._reveal_forks = True
        self._rebuild()

    def action_refresh(self) -> None:
        if self._refresh_callback is not None:
            self._refresh_callback()

    def action_run_remedy(self) -> None:
        row = self._highlighted_row()
        if row is None or not row.is_error:
            return
        argv = tuple(str(part) for part in row.data.get("remedy_argv", ()) if part)
        if not argv:
            return
        with self.app.suspend():
            subprocess.run(argv, check=False)
        self.action_refresh()

    def choose_highlighted(self) -> None:
        row = self._highlighted_row()
        if row is not None and not row.is_error:
            self.post_message(self.RowChosen(row))

    def selected_row(self) -> SourceRow | None:
        """Return the currently highlighted source row for async revalidation."""
        return self._highlighted_row()

    @on(Input.Changed, "#new-project-filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self._filter_text = event.value
        self._rebuild()

    @on(OptionList.OptionHighlighted, "#new-project-source-list")
    def _row_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        option_id = str(getattr(event.option, "id", "") or "")
        row = self._rows.get(option_id)
        if row is not None:
            self._select_detail(row)

    @on(OptionList.OptionSelected, "#new-project-source-list")
    def _row_selected(self, event: OptionList.OptionSelected) -> None:
        row = self._rows.get(str(getattr(event.option, "id", "") or ""))
        if row is not None and not row.is_error:
            self.post_message(self.RowChosen(row))

    def _highlighted_row(self) -> SourceRow | None:
        options = self.query_one("#new-project-source-list", OptionList)
        index = options.highlighted
        if index is None or index < 0:
            return None
        try:
            option = options.get_option_at_index(index)
        except Exception:
            return None
        return self._rows.get(str(getattr(option, "id", "") or ""))

    def _rebuild(self) -> None:
        if not self.is_mounted:
            return
        previous = self._selected_row_id
        if self._inputs is None:
            self._view = SourceView((), (), (), 0)
        else:
            self._view = build_source_view(
                self._inputs,
                filter_text=self._filter_text,
                reveal_forks=self._reveal_forks,
                reveal_all=self._reveal_all,
                pending_owners=self._pending_owners,
            )
        self._rows = {}
        option_rows: list[Option] = []
        for group in self._view.groups:
            option_rows.append(
                Option(Text(group.heading, style="dim bold"), disabled=True)
            )
            for row in group.rows:
                self._rows[row.row_id] = row
                option_rows.append(Option(render_source_row(row), id=row.row_id))
        if not option_rows:
            message = (
                "Loading repositories…"
                if self._inputs is None
                else "No repositories match this filter."
            )
            option_rows.append(Option(Text(message, style="dim"), disabled=True))
        options = self.query_one("#new-project-source-list", OptionList)
        options.set_options(option_rows)
        selected_index: int | None = None
        if previous in self._rows:
            for index in range(options.option_count):
                if options.get_option_at_index(index).id == previous:
                    selected_index = index
                    break
        if selected_index is None:
            for index in range(options.option_count):
                option = options.get_option_at_index(index)
                if option.id in self._rows:
                    selected_index = index
                    break
        options.highlighted = selected_index
        self.query_one("#new-project-hidden-footer", Static).update(
            hidden_footer(self._view)
        )
        self._select_detail(self._highlighted_row(), schedule_probe=False)

    def _select_detail(
        self, row: SourceRow | None, *, schedule_probe: bool = True
    ) -> None:
        self._selected_row_id = row.row_id if row is not None else None
        inputs = self._inputs
        parsed = None
        probe = None
        probe_error = ""
        checking = False
        accent_color = ""
        if row is not None and row.ref and not row.is_error:
            if (
                isinstance(row.data.get("parsed"), object)
                and row.data.get("parsed") is not None
            ):
                parsed = row.data.get("parsed")
            else:
                try:
                    parsed = workspace_provider.parse_repo_ref(
                        self.workflow_type, row.ref
                    )
                except Exception:
                    parsed = None
            if parsed is not None and inputs is not None:
                key = str(getattr(parsed, "project_key_base", "") or "")
                if key:
                    records = [
                        {"key": item.get("key"), "state": item.get("state")}
                        for item in inputs.projects
                    ]
                    accent_color = project_accent(key, among=accent_among_keys(records))
            probe_key = (self.workflow_type, row.ref)
            if probe_key in self._probe_cache:
                probe = self._probe_cache[probe_key]
            elif probe_key in self._probe_errors:
                probe_error = self._probe_errors[probe_key]
            elif probe_key in self._probing:
                checking = True
            elif schedule_probe and self._detail_debouncer is not None:

                def start_probe(
                    ref: str = row.ref,
                    key: tuple[str, str] = probe_key,
                ) -> None:
                    self._start_probe(ref, key)

                self._detail_debouncer.schedule(start_probe)
        self.query_one("#new-project-source-detail", Static).update(
            render_source_detail(
                row,
                workflow_type=self.workflow_type,
                parsed=parsed,
                probe=probe,
                checking=checking,
                probe_error=probe_error,
                project_accent_color=accent_color,
            )
        )

    def _start_probe(self, ref: str, probe_key: tuple[str, str]) -> None:
        if probe_key in self._probe_cache or probe_key in self._probing:
            return
        self._probing.add(probe_key)
        self._select_detail(self._highlighted_row(), schedule_probe=False)
        spawn_pump_free_task(
            self,
            self._load_probe(ref, probe_key),
            name=f"new-project-probe:{probe_key[0]}:{probe_key[1]}",
            registry_attr=_ROW_REGISTRY,
        )

    async def _load_probe(self, ref: str, probe_key: tuple[str, str]) -> None:
        try:
            probe = await asyncio.to_thread(workspace_provider.probe_repo, *probe_key)
            self._probe_cache[probe_key] = probe
        except Exception as error:  # Provider hooks degrade to an informative card.
            self._probe_errors[probe_key] = str(error) or type(error).__name__
        finally:
            self._probing.discard(probe_key)
        row = self._highlighted_row()
        if row is not None and (self.workflow_type, row.ref) == probe_key:
            self._select_detail(row, schedule_probe=False)

    def set_workflow_type(self, workflow_type: str) -> None:
        """Switch provider identity and refresh its currently selected detail."""
        self.workflow_type = workflow_type
        self._probe_cache.clear()
        self._probe_errors.clear()
        self._probing.clear()
        self._rebuild()


__all__ = ["NewProjectSource"]
