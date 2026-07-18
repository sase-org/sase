"""Generic branch-driven notification-gate review modal."""

from __future__ import annotations

from dataclasses import dataclass

from rich.markup import escape
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from sase.notification_gates.debug import GateDebugContext

from ..keymaps import (
    GateModalKeymaps,
    build_gate_modal_bindings,
    key_display_name,
    load_builtin_gate_defaults,
)
from .base import CopyModeForwardingMixin
from .gate_branch_controls import GateBranchControls, GateBranchData


_CUSTOM_GATE_STATIC_BINDINGS = [
    ("escape", "cancel", "Cancel"),
    ("q", "cancel", "Cancel"),
    ("d", "debug_view", "Debug"),
    ("ctrl+d", "scroll_down", "Scroll down"),
    ("ctrl+u", "scroll_up", "Scroll up"),
    ("g", "scroll_to_top", "Top"),
    ("G", "scroll_to_bottom", "Bottom"),
]
_DEFAULT_GATE_KEYMAPS = GateModalKeymaps(**load_builtin_gate_defaults())


@dataclass(frozen=True)
class CustomGateModalData:
    """Verified display data loaded from one custom gate bundle."""

    request_id: str
    sender: str
    icon: str
    notes: tuple[str, ...]
    attachments: tuple[str, ...]
    preview_name: str | None
    preview_text: str | None
    gate: GateBranchData


@dataclass(frozen=True)
class CustomGateModalResult:
    """The selected v2 option set and its optional feedback."""

    selected_option_ids: tuple[str, ...]
    feedback: str | None


class CustomGateModal(
    CopyModeForwardingMixin, ModalScreen[CustomGateModalResult | None]
):
    """Review and answer a custom notification gate from its branch model."""

    BINDINGS = [
        *_CUSTOM_GATE_STATIC_BINDINGS,
        *build_gate_modal_bindings(_DEFAULT_GATE_KEYMAPS),
    ]

    def __init__(
        self,
        data: CustomGateModalData,
        *,
        debug_context: GateDebugContext | None = None,
        gate_keymaps: GateModalKeymaps | None = None,
    ) -> None:
        super().__init__()
        self._data = data
        self._debug_context = debug_context
        self._gate_keymaps = gate_keymaps or _DEFAULT_GATE_KEYMAPS
        self._bindings = BindingsMap(
            [
                *_CUSTOM_GATE_STATIC_BINDINGS,
                *build_gate_modal_bindings(self._gate_keymaps),
            ]
        )

    def compose(self) -> ComposeResult:
        with Container(id="custom-gate-container"):
            yield Static(self._title(), id="custom-gate-title")
            with VerticalScroll(id="custom-gate-review-scroll"):
                yield Static(self._notes(), id="custom-gate-notes")
                if self._data.preview_text is not None:
                    preview_name = self._data.preview_name or "Preview"
                    yield Static(
                        f"[bold #87D7FF]{escape(preview_name)}[/bold #87D7FF]",
                        classes="custom-gate-section-title",
                    )
                    yield Static(
                        Syntax(
                            self._data.preview_text,
                            "markdown",
                            theme="monokai",
                            word_wrap=True,
                        ),
                        id="custom-gate-preview",
                    )
                if self._data.attachments:
                    yield Static(
                        self._attachment_summary(),
                        id="custom-gate-attachments",
                    )

            yield Static(
                "[bold]Choose one resolution branch[/bold]",
                id="custom-gate-choice-label",
            )
            yield GateBranchControls(self._data.gate, id="custom-gate-branches")
            with Horizontal(id="custom-gate-cancel-row"):
                yield Button("Cancel", id="custom-gate-cancel")
            yield Static(
                self._footer_text(),
                id="custom-gate-footer",
            )

    def on_mount(self) -> None:
        self.query_one(GateBranchControls).focus_next_control()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "custom-gate-cancel":
            self.action_cancel()

    def on_gate_branch_controls_resolved(
        self, event: GateBranchControls.Resolved
    ) -> None:
        event.stop()
        self.dismiss(
            CustomGateModalResult(
                selected_option_ids=event.selected_option_ids,
                feedback=event.feedback,
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_debug_view(self) -> None:
        from .gate_debug_modal import show_gate_debug

        show_gate_debug(self, self._debug_context)

    def action_next_control(self) -> None:
        self.query_one(GateBranchControls).focus_next_control()

    def action_previous_control(self) -> None:
        self.query_one(GateBranchControls).focus_previous_control()

    def action_toggle_option(self) -> None:
        self.query_one(GateBranchControls).toggle_focused_option()

    def action_submit_primary(self) -> None:
        self.query_one(GateBranchControls).submit_primary_branch()

    def action_submit_branch(self) -> None:
        self.query_one(GateBranchControls).submit_active_branch()

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#custom-gate-review-scroll", VerticalScroll)
        scroll.scroll_relative(y=scroll.scrollable_content_region.height // 2)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#custom-gate-review-scroll", VerticalScroll)
        scroll.scroll_relative(y=-(scroll.scrollable_content_region.height // 2))

    def action_scroll_to_top(self) -> None:
        self.query_one("#custom-gate-review-scroll", VerticalScroll).scroll_home(
            animate=False
        )

    def action_scroll_to_bottom(self) -> None:
        self.query_one("#custom-gate-review-scroll", VerticalScroll).scroll_end(
            animate=False
        )

    def _title(self) -> str:
        return (
            f"[bold cyan]{escape(self._data.icon)} Custom Gate[/bold cyan]  "
            f"[bold]{escape(self._data.sender)}[/bold]  "
            f"[dim]{escape(self._data.request_id)}[/dim]"
        )

    def _notes(self) -> Text:
        text = Text()
        if not self._data.notes:
            text.append("No notes were provided.", style="dim italic")
            return text
        for index, note in enumerate(self._data.notes):
            if index:
                text.append("\n")
            text.append(note)
        return text

    def _attachment_summary(self) -> Text:
        text = Text("Attachments\n", style="bold #87D7FF")
        for attachment in self._data.attachments:
            text.append(f"• {attachment}\n", style="dim")
        return text

    def _footer_text(self) -> str:
        keys = self._gate_keymaps
        return (
            f"{key_display_name(keys.next_control)}/"
            f"{key_display_name(keys.previous_control)} navigate  "
            f"{key_display_name(keys.toggle_option)} toggle  "
            f"{key_display_name(keys.submit_primary)} submit primary  "
            f"{key_display_name(keys.submit_branch)} submit  d debug  q cancel"
        )


__all__ = [
    "CustomGateModal",
    "CustomGateModalData",
    "CustomGateModalResult",
]
