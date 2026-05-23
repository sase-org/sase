"""Interactive Textual app for reviewing memory proposals."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
import difflib
from pathlib import Path

from rich.console import Group
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static

from sase.core.clipboard import copy_to_system_clipboard
from sase.memory.cli_review import edit_memory_proposal_via_editor
from sase.memory.proposals import (
    EvidenceRecord,
    MemoryProposalError,
    MemoryProposalLedgerEvent,
    MemoryProposalReviewResult,
    MemoryProposalState,
    approve_memory_proposal,
    memory_proposal_ledger_path,
    read_memory_proposal_events,
    read_memory_proposals,
    reject_memory_proposal,
    validate_memory_proposal_target,
)

type ApproveCallback = Callable[
    [str, str | None, str | Path | None], MemoryProposalReviewResult
]
type RejectCallback = Callable[[str, str], MemoryProposalReviewResult]
type EditCallback = Callable[[str, str | None], MemoryProposalReviewResult]


def _default_approve(
    proposal_id: str,
    target: str | None,
    edited_file: str | Path | None,
) -> MemoryProposalReviewResult:
    return approve_memory_proposal(
        proposal_id,
        target=target,
        edited_file=edited_file,
    )


def _default_reject(
    proposal_id: str,
    reason: str,
) -> MemoryProposalReviewResult:
    return reject_memory_proposal(proposal_id, reason=reason)


def _default_edit(
    proposal_id: str,
    target: str | None,
) -> MemoryProposalReviewResult:
    return edit_memory_proposal_via_editor(proposal_id, target=target)


@dataclass(frozen=True)
class _TargetSummary:
    target_path: str
    canonical_path: Path
    exists: bool
    diff: tuple[str, ...]
    error: str | None = None


class _TextInputModal(ModalScreen[str | None]):
    """Small input modal used for filter, reject reason, and target edits."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        title: str,
        *,
        value: str = "",
        placeholder: str = "",
        submit_label: str = "Apply",
        validator: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._value = value
        self._placeholder = placeholder
        self._submit_label = submit_label
        self._validator = validator

    def compose(self) -> ComposeResult:
        with Container(id="memory-review-input-modal"):
            yield Label(self._title, id="memory-review-input-title")
            yield Input(
                value=self._value,
                placeholder=self._placeholder,
                id="memory-review-input",
            )
            error = Label("", id="memory-review-input-error")
            error.display = False
            yield error
            with Horizontal(id="memory-review-input-buttons"):
                yield Button(self._submit_label, id="apply", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    def on_mount(self) -> None:
        field = self.query_one("#memory-review-input", Input)
        field.focus()
        field.select_all()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            self._submit()
            return
        self.dismiss(None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        value = self.query_one("#memory-review-input", Input).value
        if self._validator is not None:
            error = self._validator(value)
            if error:
                self._show_error(error)
                return
        self.dismiss(value)

    def _show_error(self, message: str) -> None:
        error = self.query_one("#memory-review-input-error", Label)
        error.update(message)
        error.display = True


class MemoryReviewTuiApp(App[None]):
    """Textual app for reviewing pending long-term memory proposals."""

    ENABLE_COMMAND_PALETTE = False
    CSS = """
    #memory-review-root {
        layout: vertical;
        height: 1fr;
    }

    #memory-review-title {
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text;
        text-style: bold;
    }

    #memory-review-status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    #memory-review-content {
        height: 1fr;
    }

    #memory-review-list-pane {
        width: 58%;
        height: 1fr;
        border: solid $primary;
    }

    #memory-review-detail-pane {
        width: 42%;
        height: 1fr;
        border: solid $secondary;
    }

    #memory-review-list-title,
    #memory-review-detail,
    #memory-review-body,
    #memory-review-footer {
        padding: 0 1;
    }

    #memory-review-table {
        height: 1fr;
    }

    #memory-review-detail {
        height: 45%;
        overflow-y: auto;
    }

    #memory-review-body {
        height: 55%;
        overflow-y: auto;
    }

    #memory-review-footer {
        height: 1;
        color: $text-muted;
        background: $boost;
    }

    #memory-review-input-modal {
        width: 72;
        height: auto;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }

    #memory-review-input-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #memory-review-input-error {
        color: $error;
        margin-top: 1;
    }

    #memory-review-input-buttons {
        height: 3;
        margin-top: 1;
    }
    """

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
        cwd: Path | None = None,
    ) -> None:
        super().__init__()
        self._load_states = load_states or read_memory_proposals
        self._load_events = load_events or read_memory_proposal_events
        self._approve_callback = approve_callback or _default_approve
        self._reject_callback = reject_callback or _default_reject
        self._edit_callback = edit_callback or _default_edit
        self._cwd = (cwd or Path.cwd()).resolve(strict=False)
        self._all_states: tuple[MemoryProposalState, ...] = ()
        self._states: tuple[MemoryProposalState, ...] = ()
        self._events: tuple[MemoryProposalLedgerEvent, ...] = ()
        self._selected_id: str | None = None
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
            _TextInputModal(
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
            _TextInputModal(
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
            _TextInputModal(
                "Approval target",
                value=current,
                placeholder="long/<slug>.md; blank resets to proposal target",
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
                _format_time_or_age(state.created_at),
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

        body = _read_optional_text(Path(state.body_path)) or ""
        target = self._target_summary(state, body)
        if self._view_mode == "detail":
            detail.update(_detail_text(state, target, self._events))
        else:
            detail.update(_preview_text(state, target))
        body_preview.update(Group(Text("Memory\n", style="bold"), RichMarkdown(body)))

    def _target_summary(self, state: MemoryProposalState, body: str) -> _TargetSummary:
        target_path = self._target_overrides.get(state.proposal_id, state.target_path)
        canonical_path = self._cwd / "memory" / target_path
        try:
            existing = canonical_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _TargetSummary(
                target_path=target_path,
                canonical_path=canonical_path,
                exists=False,
                diff=(),
            )
        except (OSError, UnicodeError) as exc:
            return _TargetSummary(
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
                fromfile=f"memory/{target_path}",
                tofile=state.proposal_id,
                lineterm="",
            )
        )
        return _TargetSummary(
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
                " ".join(state.keywords),
            )
        ).casefold()
        return query in haystack

    def _footer_text(self) -> str:
        return (
            "j/k arrows navigate  g/G jump  / filter  enter/d details  "
            "a approve  e edit+approve  r reject  t target  y copy id  q quit"
        )


def _preview_text(state: MemoryProposalState, target: _TargetSummary) -> Text:
    text = Text()
    text.append(f"{state.title}\n", style="bold")
    text.append(f"id: {state.proposal_id}\n")
    text.append(f"author: {state.author_name} ({state.author_source})\n")
    text.append(f"target: {target.target_path} ")
    text.append("(exists)\n" if target.exists else "(available)\n")
    text.append(f"evidence: {len(state.evidence)} item(s)\n")
    if state.keywords:
        text.append(f"keywords: {', '.join(state.keywords)}\n")
    if state.warnings:
        text.append("\nwarnings:\n", style="bold yellow")
        for warning in state.warnings:
            text.append(f"- {warning.code}: {warning.message}\n")
    text.append(
        "\nPress enter or d for evidence, target, and audit details.\n", style="dim"
    )
    return text


def _detail_text(
    state: MemoryProposalState,
    target: _TargetSummary,
    events: Iterable[MemoryProposalLedgerEvent],
) -> Text:
    text = Text()
    text.append(f"{state.title}\n", style="bold")
    text.append(f"id: {state.proposal_id}\n")
    text.append(f"status: {state.status}\n")
    text.append(f"created: {state.created_at}\n")
    text.append(f"author: {state.author_name} ({state.author_source})\n")
    if state.keywords:
        text.append(f"keywords: {', '.join(state.keywords)}\n")

    text.append("\nEvidence\n", style="bold")
    for line in _evidence_lines(state.evidence):
        text.append(line + "\n")

    text.append("\nTarget\n", style="bold")
    text.append(f"path: {target.target_path}\n")
    text.append(f"canonical: {target.canonical_path}\n")
    if target.error:
        text.append(f"status: exists, failed to read: {target.error}\n", style="red")
    else:
        text.append("status: exists\n" if target.exists else "status: available\n")
    if target.diff:
        text.append("diff:\n", style="bold")
        for line in target.diff[:120]:
            style = (
                "green"
                if line.startswith("+")
                else "red"
                if line.startswith("-")
                else ""
            )
            text.append(line + "\n", style=style)
        if len(target.diff) > 120:
            text.append(f"... {len(target.diff) - 120} more diff lines\n", style="dim")

    if state.warnings:
        text.append("\nWarnings\n", style="bold yellow")
        for warning in state.warnings:
            text.append(f"- {warning.code}: {warning.message}\n")

    text.append("\nAudit\n", style="bold")
    audit_lines = _audit_lines(state.proposal_id, events)
    for line in audit_lines:
        text.append(line + "\n")
    return text


def _evidence_lines(evidence: Iterable[EvidenceRecord]) -> tuple[str, ...]:
    lines: list[str] = []
    for record in evidence:
        if record.kind == "path":
            status = "exists" if record.exists else "missing"
            detail = record.resolved_path or record.path or record.raw
            parts = [f"- path {status}: {detail}"]
            if record.byte_count is not None:
                parts.append(f"bytes={record.byte_count}")
            if record.sha256:
                parts.append(f"sha256={record.sha256[:12]}")
            lines.append("  ".join(parts))
            excerpt = _path_excerpt(record.resolved_path)
            if excerpt:
                lines.append(f"  excerpt: {excerpt}")
            continue
        if record.kind == "chat":
            lines.append(f"- chat: {record.chat_id}")
            continue
        if record.kind == "url":
            lines.append(f"- url: {record.url}")
            continue
        if record.kind == "note":
            lines.append(f"- note: {record.note}")
    return tuple(lines)


def _audit_lines(
    proposal_id: str,
    events: Iterable[MemoryProposalLedgerEvent],
) -> tuple[str, ...]:
    lines: list[str] = []
    for event in events:
        if event.proposal_id != proposal_id:
            continue
        event_type = event.event_type
        actor = getattr(event, "author_name", None)
        if actor is None:
            actor = (
                f"{getattr(event, 'reviewer_user', 'unknown')}@"
                f"{getattr(event, 'reviewer_hostname', 'unknown')}"
            )
        line = f"- {event.timestamp} {event_type} by {actor}"
        reason = getattr(event, "reason", None)
        if reason:
            line += f": {reason}"
        lines.append(line)
    return tuple(lines) or ("- no ledger events found",)


def _path_excerpt(path_value: str | None) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    line = next(
        (candidate.strip() for candidate in text.splitlines() if candidate.strip()), ""
    )
    if len(line) > 96:
        return line[:93] + "..."
    return line


def _read_optional_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _format_time_or_age(timestamp: str) -> str:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp
    now = datetime.now(tz=UTC)
    seconds = max(0, int((now - parsed.astimezone(UTC)).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return parsed.astimezone(UTC).strftime("%Y-%m-%d")
