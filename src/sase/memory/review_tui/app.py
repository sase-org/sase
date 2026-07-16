"""Textual app for reviewing pending memory proposals."""

from __future__ import annotations

from collections.abc import Callable
import difflib
from pathlib import Path

from rich.console import Group
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Static

from sase.core.clipboard import copy_to_system_clipboard
from sase.memory.proposals import (
    MemoryProposalError,
    MemoryProposalLedgerEvent,
    MemoryProposalReviewResult,
    MemoryProposalState,
    memory_proposal_ledger_path,
    read_memory_proposal_events,
    read_memory_proposals,
    validate_memory_proposal_target,
)
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT, memory_write_root
from sase.memory.review_tui._callbacks import (
    ApproveCallback,
    EditCallback,
    RejectCallback,
    default_approve,
    default_edit,
    default_reject,
)
from sase.memory.review_tui._modals import TextInputModal
from sase.memory.review_tui._models import TargetSummary
from sase.memory.review_tui._render import (
    detail_text,
    format_time_or_age,
    preview_text,
    read_optional_text,
)
from sase.memory.review_tui._styles import MEMORY_REVIEW_CSS


class MemoryReviewTuiApp(App[None]):
    """Textual app for reviewing pending long-term memory proposals."""

    ENABLE_COMMAND_PALETTE = False
    CSS = MEMORY_REVIEW_CSS

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("j", "next_proposal", "Next"),
        ("down", "next_proposal", "Next"),
        ("k", "previous_proposal", "Previous"),
        ("up", "previous_proposal", "Previous"),
        ("g", "first_proposal", "First"),
        ("G", "last_proposal", "Last"),
        ("slash", "filter", "Filter"),
        ("enter", "drill_down", "Details"),
        ("d", "drill_down", "Details"),
        ("escape", "back_from_detail", "Back"),
        ("a", "approve", "Approve"),
        ("e", "edit_approve", "Edit"),
        ("r", "reject", "Reject"),
        ("t", "edit_target", "Target"),
        ("y", "copy_proposal_id", "Copy id"),
    ]

    def __init__(
        self,
        *,
        load_states: Callable[[], tuple[MemoryProposalState, ...]] | None = None,
        load_events: Callable[[], tuple[MemoryProposalLedgerEvent, ...]] | None = None,
        approve_callback: ApproveCallback | None = None,
        reject_callback: RejectCallback | None = None,
        edit_callback: EditCallback | None = None,
        initial_proposal_id: str | None = None,
        cwd: Path | None = None,
    ) -> None:
        super().__init__()
        self._load_states = load_states or read_memory_proposals
        self._load_events = load_events or read_memory_proposal_events
        self._approve_callback = approve_callback or default_approve
        self._reject_callback = reject_callback or default_reject
        self._edit_callback = edit_callback or default_edit
        self._cwd = (cwd or Path.cwd()).resolve(strict=False)
        self._memory_root = memory_write_root(self._cwd)
        self._all_states: tuple[MemoryProposalState, ...] = ()
        self._states: tuple[MemoryProposalState, ...] = ()
        self._events: tuple[MemoryProposalLedgerEvent, ...] = ()
        self._selected_id: str | None = initial_proposal_id
        self._filter_text = ""
        self._view_mode = "list"
        self._status_message = ""
        self._target_overrides: dict[str, str] = {}

    @property
    def view_mode(self) -> str:
        return self._view_mode

    @property
    def selected_proposal_id(self) -> str | None:
        return self._selected_id

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="memory-review-root"):
            yield Static("Memory Review", id="memory-review-title")
            yield Static("", id="memory-review-status")
            with Horizontal(id="memory-review-content"):
                with Vertical(id="memory-review-list-pane"):
                    yield Static("Pending proposals", id="memory-review-list-title")
                    yield DataTable(id="memory-review-table")
                with Vertical(id="memory-review-detail-pane"):
                    yield Static("", id="memory-review-detail")
                    yield Static("", id="memory-review-body")
            yield Static(self._footer_text(), id="memory-review-footer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#memory-review-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("Status", "Age", "Author", "Target", "Ev", "Title")
        table.focus()
        self._reload()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "memory-review-table":
            return
        self._selected_id = str(event.row_key.value)
        self._refresh_detail()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "memory-review-table":
            return
        self._selected_id = str(event.row_key.value)
        self.action_drill_down()

    def action_next_proposal(self) -> None:
        table = self.query_one("#memory-review-table", DataTable)
        if not self._states:
            return
        table.move_cursor(row=min(table.cursor_row + 1, len(self._states) - 1))
        self._sync_selected_from_table()

    def action_previous_proposal(self) -> None:
        table = self.query_one("#memory-review-table", DataTable)
        if not self._states:
            return
        table.move_cursor(row=max(table.cursor_row - 1, 0))
        self._sync_selected_from_table()

    def action_first_proposal(self) -> None:
        if not self._states:
            return
        self.query_one("#memory-review-table", DataTable).move_cursor(row=0)
        self._sync_selected_from_table()

    def action_last_proposal(self) -> None:
        if not self._states:
            return
        self.query_one("#memory-review-table", DataTable).move_cursor(
            row=len(self._states) - 1
        )
        self._sync_selected_from_table()

    def action_filter(self) -> None:
        def apply_filter(value: str | None) -> None:
            if value is None:
                return
            self._filter_text = value.strip()
            self._view_mode = "list"
            self._reload()

        self.push_screen(
            TextInputModal(
                "Filter proposals",
                value=self._filter_text,
                placeholder="id, title, author, target, or status",
            ),
            apply_filter,
        )

    def action_drill_down(self) -> None:
        if self._selected_state() is None:
            return
        self._view_mode = "detail"
        self._refresh_detail()

    def action_back_from_detail(self) -> None:
        if self._view_mode == "detail":
            self._view_mode = "list"
            self._refresh_detail()

    def action_approve(self) -> None:
        state = self._selected_state()
        if state is None:
            self._set_status("No proposal selected.")
            return
        target = self._target_overrides.get(state.proposal_id)
        self._run_review_action(
            lambda: self._approve_callback(state.proposal_id, target, None),
            success_prefix="Approved",
        )

    def action_edit_approve(self) -> None:
        state = self._selected_state()
        if state is None:
            self._set_status("No proposal selected.")
            return
        target = self._target_overrides.get(state.proposal_id)
        self._run_review_action(
            lambda: self._edit_callback(state.proposal_id, target),
            success_prefix="Approved edited",
        )

    def action_reject(self) -> None:
        state = self._selected_state()
        if state is None:
            self._set_status("No proposal selected.")
            return

        def validate_reason(value: str) -> str | None:
            if not value.strip():
                return "Rejection reason is required."
            return None

        def reject_with_reason(value: str | None) -> None:
            if value is None:
                return
            reason = value.strip()
            self._run_review_action(
                lambda: self._reject_callback(state.proposal_id, reason),
                success_prefix="Rejected",
            )

        self.push_screen(
            TextInputModal(
                "Reject memory proposal",
                placeholder="reason",
                submit_label="Reject",
                validator=validate_reason,
            ),
            reject_with_reason,
        )

    def action_edit_target(self) -> None:
        state = self._selected_state()
        if state is None:
            self._set_status("No proposal selected.")
            return
        current = self._target_overrides.get(state.proposal_id, state.target_path)

        def validate_target(value: str) -> str | None:
            raw = value.strip()
            if not raw:
                return None
            try:
                validate_memory_proposal_target(raw)
            except MemoryProposalError as exc:
                return str(exc)
            return None

        def apply_target(value: str | None) -> None:
            if value is None:
                return
            raw = value.strip()
            if raw:
                self._target_overrides[state.proposal_id] = (
                    validate_memory_proposal_target(raw)
                )
            else:
                self._target_overrides.pop(state.proposal_id, None)
            self._set_status(
                f"Target for {state.proposal_id} set to "
                f"{self._target_overrides.get(state.proposal_id, state.target_path)}"
            )
            self._refresh_detail()

        self.push_screen(
            TextInputModal(
                "Approval target",
                value=current,
                placeholder="<slug>.md; blank resets to proposal target",
                validator=validate_target,
            ),
            apply_target,
        )

    def action_copy_proposal_id(self) -> None:
        state = self._selected_state()
        if state is None:
            self._set_status("No proposal selected.")
            return
        if copy_to_system_clipboard(state.proposal_id):
            self._set_status(f"Copied {state.proposal_id}.")
            self.notify("Copied proposal id")
            return
        self._set_status("Clipboard command not available.")
        self.notify("Failed to copy proposal id", severity="error")

    def _run_review_action(
        self,
        action: Callable[[], MemoryProposalReviewResult],
        *,
        success_prefix: str,
    ) -> None:
        try:
            result = action()
        except (MemoryProposalError, OSError, UnicodeError) as exc:
            self._set_status(f"Error: {exc}")
            self.notify(str(exc), severity="error")
            return
        self._target_overrides.pop(result.state.proposal_id, None)
        self._selected_id = None
        self._view_mode = "list"
        self._set_status(f"{success_prefix} {result.state.proposal_id}.")
        self.notify(f"{success_prefix} {result.state.proposal_id}")
        self._reload()

    def _reload(self) -> None:
        self._all_states = self._load_states()
        self._events = self._load_events()
        self._states = tuple(
            state
            for state in self._all_states
            if state.status == "pending" and self._matches_filter(state)
        )
        if self._selected_id not in {state.proposal_id for state in self._states}:
            self._selected_id = self._states[0].proposal_id if self._states else None
        self._refresh_table()
        self._refresh_status()
        self._refresh_detail()

    def _refresh_table(self) -> None:
        table = self.query_one("#memory-review-table", DataTable)
        table.clear()
        for state in self._states:
            target = self._target_overrides.get(state.proposal_id, state.target_path)
            table.add_row(
                state.status,
                format_time_or_age(state.created_at),
                state.author_name,
                target,
                str(len(state.evidence)),
                state.title,
                key=state.proposal_id,
            )
        if self._selected_id is None:
            return
        for idx, state in enumerate(self._states):
            if state.proposal_id == self._selected_id:
                table.move_cursor(row=idx, column=0, animate=False)
                return

    def _refresh_status(self) -> None:
        status = self.query_one("#memory-review-status", Static)
        filter_suffix = f" filter={self._filter_text!r}" if self._filter_text else ""
        ledger = memory_proposal_ledger_path(cwd=self._cwd)
        message = self._status_message or f"{len(self._states)} pending proposals"
        status.update(f"{message}{filter_suffix}  ledger: {ledger}")

    def _refresh_detail(self) -> None:
        detail = self.query_one("#memory-review-detail", Static)
        body_preview = self.query_one("#memory-review-body", Static)
        state = self._selected_state()
        if state is None:
            detail.update(Text("No pending memory proposals.", style="dim"))
            body_preview.update(RichMarkdown(""))
            return

        body = read_optional_text(Path(state.body_path)) or ""
        target = self._target_summary(state, body)
        if self._view_mode == "detail":
            detail.update(detail_text(state, target, self._events))
        else:
            detail.update(preview_text(state, target))
        body_preview.update(Group(Text("Memory\n", style="bold"), RichMarkdown(body)))

    def _target_summary(self, state: MemoryProposalState, body: str) -> TargetSummary:
        target_path = self._target_overrides.get(state.proposal_id, state.target_path)
        canonical_path = self._memory_root / target_path
        try:
            existing = canonical_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return TargetSummary(
                target_path=target_path,
                canonical_path=canonical_path,
                exists=False,
                diff=(),
            )
        except (OSError, UnicodeError) as exc:
            return TargetSummary(
                target_path=target_path,
                canonical_path=canonical_path,
                exists=True,
                diff=(),
                error=str(exc),
            )
        diff = tuple(
            difflib.unified_diff(
                existing.splitlines(),
                body.splitlines(),
                fromfile=(CANONICAL_MEMORY_RELATIVE_ROOT / target_path).as_posix(),
                tofile=state.proposal_id,
                lineterm="",
            )
        )
        return TargetSummary(
            target_path=target_path,
            canonical_path=canonical_path,
            exists=True,
            diff=diff,
        )

    def _selected_state(self) -> MemoryProposalState | None:
        if self._selected_id is None:
            return None
        for state in self._states:
            if state.proposal_id == self._selected_id:
                return state
        return None

    def _sync_selected_from_table(self) -> None:
        if not self._states:
            self._selected_id = None
            self._refresh_detail()
            return
        table = self.query_one("#memory-review-table", DataTable)
        row = max(0, min(table.cursor_row, len(self._states) - 1))
        self._selected_id = self._states[row].proposal_id
        self._refresh_detail()

    def _set_status(self, message: str) -> None:
        self._status_message = message
        self._refresh_status()

    def _matches_filter(self, state: MemoryProposalState) -> bool:
        query = self._filter_text.casefold()
        if not query:
            return True
        haystack = " ".join(
            (
                state.proposal_id,
                state.status,
                state.title,
                state.target_path,
                state.author_name,
            )
        ).casefold()
        return query in haystack

    def _footer_text(self) -> str:
        return (
            "j/k arrows navigate  g/G jump  / filter  enter/d details  "
            "a approve  e edit+approve  r reject  t target  y copy id  q quit"
        )
