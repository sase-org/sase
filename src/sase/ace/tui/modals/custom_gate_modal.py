"""Generic branch-driven notification-gate review modal."""

from __future__ import annotations

from dataclasses import dataclass

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from sase.notification_gates.debug import GateDebugContext

from ..keymaps import (
    GateModalKeymaps,
    build_gate_modal_bindings,
    key_display_name,
    load_builtin_gate_defaults,
)
from ..util.frontmatter_syntax import markdown_document_syntax
from .base import CopyModeForwardingMixin
from .gate_branch_controls import GateBranchControls, GateBranchData
from .gate_primary_footer import primary_action_badge


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

    HORIZONTAL_BREAKPOINTS = [
        (0, "-gate-review-narrow"),
        (100, "-gate-review-wide"),
    ]

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
        shell_classes = "gate-review-shell"
        if self._data.preview_text is None:
            shell_classes += " gate-review-shell--compact"
        with Container(id="custom-gate-container", classes=shell_classes):
            yield Static(
                self._title(),
                id="custom-gate-title",
                classes="gate-review-header",
            )
            if self._data.preview_text is None:
                with VerticalScroll(
                    id="custom-gate-review-scroll",
                    classes="gate-review-actions gate-review-actions--compact",
                ):
                    yield from self._compose_actions()
            else:
                with Container(classes="gate-review-body"):
                    with VerticalScroll(classes="gate-review-actions"):
                        yield from self._compose_actions()

                    preview_name = self._data.preview_name or "Preview"
                    review_scroll = VerticalScroll(
                        id="custom-gate-review-scroll",
                        classes="gate-review-document",
                    )
                    review_scroll.border_title = Text(preview_name)
                    with review_scroll:
                        yield Static(
                            markdown_document_syntax(self._data.preview_text),
                            id="custom-gate-preview",
                        )

            yield Static(
                self._footer_text(),
                id="custom-gate-footer",
                classes="gate-review-footer",
            )

    def _compose_actions(self) -> ComposeResult:
        yield Static("Context", classes="gate-review-section-title")
        yield Static(self._notes(), id="custom-gate-notes")
        if self._data.attachments:
            yield Static("Attachments", classes="gate-review-section-title")
            yield Static(
                self._attachment_summary(),
                id="custom-gate-attachments",
            )
        yield Static("Decision", classes="gate-review-section-title")
        yield GateBranchControls(
            self._data.gate,
            id="custom-gate-branches",
            classes="gate-branch-controls--stacked",
        )
        yield Button(
            "Cancel",
            id="custom-gate-cancel",
            classes="gate-review-cancel",
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
        text = Text()
        for attachment in self._data.attachments:
            text.append(f"• {attachment}\n", style="dim")
        return text

    def _footer_text(self) -> Text:
        keys = self._gate_keymaps
        text = Text()
        text.append(
            f"{key_display_name(keys.next_control)}/"
            f"{key_display_name(keys.previous_control)} navigate  "
        )
        text.append(f"{key_display_name(keys.toggle_option)} toggle  ")
        text.append_text(primary_action_badge(self._data.gate, keys.submit_primary))
        text.append("  ")
        text.append(f"{key_display_name(keys.submit_branch)} submit  d debug  q cancel")
        return text


__all__ = [
    "CustomGateModal",
    "CustomGateModalData",
    "CustomGateModalResult",
]
