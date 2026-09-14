"""Dedicated ACE review modal for typed sudo requests."""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, SelectionList, Static

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.notification_gates.debug import GateDebugContext

from ..util.frontmatter_syntax import markdown_document_syntax
from .base import CopyModeForwardingMixin


@dataclass(frozen=True)
class SudoCommandReviewData:
    """One command row projected from a verified sudo manifest."""

    id: str
    argv: tuple[str, ...]
    executable_sha256: str


@dataclass(frozen=True)
class SudoRequestModalData:
    """Verified display data for one typed sudo request."""

    request_id: str
    title: str
    sender: str
    reason: str
    commands: tuple[SudoCommandReviewData, ...]
    run_as: str
    cwd: str
    env: tuple[tuple[str, str], ...]
    timeout_seconds: int
    stop_policy: str
    output_policy: str
    machine: str | None
    manifest_sha256: str
    risk_badges: tuple[str, ...]
    requester: str | None = None
    project: str | None = None
    expires_at: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class SudoRequestModalResult:
    """Reviewer decision from the sudo request modal."""

    action: Literal["run", "deny"]
    command_ids: tuple[str, ...] = ()
    feedback: str | None = None


class SudoRequestModal(
    CopyModeForwardingMixin, ModalScreen[SudoRequestModalResult | None]
):
    """Review and answer a typed sudo request without collecting credentials."""

    HORIZONTAL_BREAKPOINTS = [
        (0, "-gate-review-narrow"),
        (100, "-gate-review-wide"),
    ]

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("space", "toggle_command", "Toggle command"),
        ("v", "toggle_details", "Details"),
        ("d", "deny", "Deny"),
        ("enter", "run", "Run"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
    ]

    def __init__(
        self,
        data: SudoRequestModalData,
        *,
        debug_context: GateDebugContext | None = None,
    ) -> None:
        super().__init__()
        self._data = data
        self._debug_context = debug_context
        self._show_details = False

    def compose(self) -> ComposeResult:
        with Container(id="sudo-request-container", classes="gate-review-shell"):
            yield Static(
                self._title(),
                id="sudo-request-title",
                classes="gate-review-header",
            )
            with Container(classes="gate-review-body"):
                with VerticalScroll(
                    id="sudo-request-review-scroll",
                    classes="gate-review-actions",
                ):
                    yield from self._compose_review()
                detail_scroll = VerticalScroll(
                    id="sudo-request-detail-scroll",
                    classes="gate-review-document",
                )
                detail_scroll.border_title = "Details"
                with detail_scroll:
                    yield Static(
                        markdown_document_syntax(self._detail_markdown()),
                        id="sudo-request-detail",
                    )
            yield Static(
                self._footer_text(),
                id="sudo-request-footer",
                classes="gate-review-footer",
            )

    def _compose_review(self) -> ComposeResult:
        yield Static("Context", classes="gate-review-section-title")
        yield Static(self._context_text(), id="sudo-request-context")
        yield Static("Commands", classes="gate-review-section-title")
        yield SelectionList[str](
            *(
                (self._command_label(command), command.id, True)
                for command in self._data.commands
            ),
            id="sudo-command-list",
        )
        yield Static("Denial Feedback", classes="gate-review-section-title")
        yield SingleLineVimTextArea(
            placeholder="Optional note for the requesting agent",
            id="sudo-deny-feedback",
        )
        with Horizontal(id="sudo-request-buttons"):
            yield Button(
                "Authenticate & run",
                id="sudo-run",
                variant="primary",
            )
            yield Button("Deny", id="sudo-deny", variant="warning")
            yield Button("Cancel", id="sudo-cancel")

    def on_mount(self) -> None:
        self.query_one("#sudo-command-list", SelectionList).focus()
        self._sync_run_button()
        self._sync_details()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sudo-run":
            self.action_run()
        elif event.button.id == "sudo-deny":
            self.action_deny()
        elif event.button.id == "sudo-cancel":
            self.action_cancel()

    def on_selection_list_selection_toggled(
        self,
        _event: SelectionList.SelectionToggled,
    ) -> None:
        self._sync_run_button()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_debug_view(self) -> None:
        from .gate_debug_modal import show_gate_debug

        show_gate_debug(self, self._debug_context)

    def action_toggle_command(self) -> None:
        self.query_one("#sudo-command-list", SelectionList).action_select()
        self._sync_run_button()

    def action_toggle_details(self) -> None:
        self._show_details = not self._show_details
        self._sync_details()

    def action_deny(self) -> None:
        self.dismiss(
            SudoRequestModalResult(
                action="deny",
                feedback=self._feedback(),
            )
        )

    def action_run(self) -> None:
        command_ids = self._selected_command_ids()
        if not command_ids:
            self.notify(
                "Select at least one sudo command to run",
                severity="warning",
            )
            self._sync_run_button()
            return
        self.dismiss(
            SudoRequestModalResult(
                action="run",
                command_ids=command_ids,
                feedback=self._feedback(),
            )
        )

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#sudo-request-review-scroll", VerticalScroll)
        scroll.scroll_relative(y=scroll.scrollable_content_region.height // 2)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#sudo-request-review-scroll", VerticalScroll)
        scroll.scroll_relative(y=-(scroll.scrollable_content_region.height // 2))

    def action_scroll_to_top(self) -> None:
        self.query_one("#sudo-request-review-scroll", VerticalScroll).scroll_home(
            animate=False
        )

    def action_scroll_to_bottom(self) -> None:
        self.query_one("#sudo-request-review-scroll", VerticalScroll).scroll_end(
            animate=False
        )

    def _selected_command_ids(self) -> tuple[str, ...]:
        selected = self.query_one("#sudo-command-list", SelectionList).selected
        return tuple(str(command_id) for command_id in selected)

    def _feedback(self) -> str | None:
        value = self.query_one("#sudo-deny-feedback", SingleLineVimTextArea).text
        text = value.strip()
        return text or None

    def _sync_run_button(self) -> None:
        self.query_one("#sudo-run", Button).disabled = not bool(
            self._selected_command_ids()
        )

    def _sync_details(self) -> None:
        detail = self.query_one("#sudo-request-detail", Static)
        detail.update(markdown_document_syntax(self._detail_markdown()))

    def _title(self) -> str:
        return (
            f"[bold #FFAF5F]SUDO {escape(self._data.title)}[/bold #FFAF5F]  "
            f"[dim]{escape(self._data.sender)}[/dim]  "
            f"[dim]{escape(self._data.request_id)}[/dim]"
        )

    def _context_text(self) -> Text:
        rows = [
            ("Reason", self._data.reason),
            ("Host", self._data.machine or "local"),
            ("Run as", self._data.run_as),
            ("Cwd", self._data.cwd),
            ("Environment", self._env_policy()),
            ("Requester", self._data.requester or "unknown"),
            ("Project", self._data.project or "unknown"),
            ("Expires", self._data.expires_at or "unknown"),
            ("Risk", ", ".join(self._data.risk_badges) or "none"),
        ]
        text = Text()
        for label, value in rows:
            text.append(f"{label:<12}", style="dim")
            text.append(str(value))
            text.append("\n")
        return text

    def _env_policy(self) -> str:
        if not self._data.env:
            return "empty"
        keys = ", ".join(key for key, _value in self._data.env)
        return f"{len(self._data.env)} reviewed key(s): {keys}"

    def _command_label(self, command: SudoCommandReviewData) -> Text:
        command_text = shlex.join(command.argv)
        if len(command_text) > 92:
            command_text = command_text[:89] + "..."
        text = Text()
        text.append(f"{command.id:<14}", style="bold #FFAF5F")
        text.append(command_text)
        return text

    def _detail_markdown(self) -> str:
        if not self._show_details:
            return (
                "# Details\n\n"
                "Press `v` to show argv, reviewed environment, and snapshot hashes.\n"
            )
        payload = {
            "request_id": self._data.request_id,
            "created_at": self._data.created_at,
            "expires_at": self._data.expires_at,
            "run_as": self._data.run_as,
            "cwd": self._data.cwd,
            "env": dict(self._data.env),
            "timeout_seconds": self._data.timeout_seconds,
            "stop_policy": self._data.stop_policy,
            "output_policy": self._data.output_policy,
            "manifest_sha256": self._data.manifest_sha256,
            "commands": [
                {
                    "id": command.id,
                    "argv": list(command.argv),
                    "executable_sha256": command.executable_sha256,
                }
                for command in self._data.commands
            ],
        }
        return "# Details\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n"

    def _footer_text(self) -> Text:
        text = Text()
        text.append("<space> toggle  ")
        text.append("v details  ")
        text.append("<enter> authenticate & run  ")
        text.append("d deny  q cancel")
        return text


def sudo_request_expires_at(envelope: Mapping[str, object]) -> str | None:
    """Return the ISO deadline for a verified sudo envelope, if computable."""
    created_at = envelope.get("created_at")
    timeout = envelope.get("gate_timeout_seconds")
    if not isinstance(created_at, str):
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        return None
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    return datetime.fromtimestamp(
        created.timestamp() + float(timeout),
        created.tzinfo,
    ).isoformat()


__all__ = [
    "SudoCommandReviewData",
    "SudoRequestModal",
    "SudoRequestModalData",
    "SudoRequestModalResult",
    "sudo_request_expires_at",
]
