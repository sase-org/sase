"""Generic branch-driven notification-gate review modal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from sase.notification_gates.debug import GateDebugContext
from sase.notification_gates.models import GateError, validate_color
from sase.notification_gates.presentation import GateChip

from ..keymaps import (
    GateModalKeymaps,
    build_gate_modal_bindings,
    build_gate_numbered_branch_bindings,
    key_display_name,
    load_builtin_gate_defaults,
)
from ..util.frontmatter_syntax import markdown_document_syntax
from .base import CopyModeForwardingMixin
from .gate_action_controls import GateActionsData
from .gate_action_runner import (
    GateActionRunner,
    GateActionsMixin,
    gate_modal_taken_keys,
)
from .gate_branch_controls import (
    DEFAULT_HOST_COLLECTED_PROPERTIES,
    GateBranchControls,
    GateBranchData,
    gate_declares_inputs,
)
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
    title: str
    sender: str
    icon: str
    notes: tuple[str, ...]
    attachments: tuple[str, ...]
    preview_name: str | None
    preview_text: str | None
    gate: GateBranchData
    origin_agent: str | None = None
    gate_title: str | None = None
    actions: GateActionsData = GateActionsData()
    chip: GateChip | None = None


@dataclass(frozen=True)
class CustomGateModalResult:
    """The selected v2 option set and its optional feedback."""

    selected_option_ids: tuple[str, ...]
    feedback: str | None
    option_inputs: Mapping[str, dict[str, Any]] = field(default_factory=dict)


class CustomGateModal(
    GateActionsMixin, CopyModeForwardingMixin, ModalScreen[CustomGateModalResult | None]
):
    """Review and answer a custom notification gate from its branch model."""

    HORIZONTAL_BREAKPOINTS = [
        (0, "-gate-review-narrow"),
        (100, "-gate-review-wide"),
    ]

    BINDINGS = [
        *_CUSTOM_GATE_STATIC_BINDINGS,
        *build_gate_modal_bindings(_DEFAULT_GATE_KEYMAPS),
        *build_gate_numbered_branch_bindings(),
    ]

    def __init__(
        self,
        data: CustomGateModalData,
        *,
        debug_context: GateDebugContext | None = None,
        gate_keymaps: GateModalKeymaps | None = None,
        action_runner: GateActionRunner | None = None,
    ) -> None:
        super().__init__()
        self._data = data
        self._debug_context = debug_context
        self._gate_keymaps = gate_keymaps or _DEFAULT_GATE_KEYMAPS
        self._init_gate_actions(
            data.actions,
            action_runner,
            taken_keys=gate_modal_taken_keys(
                _CUSTOM_GATE_STATIC_BINDINGS, self._gate_keymaps
            ),
        )
        self._bindings = BindingsMap(
            [
                *_CUSTOM_GATE_STATIC_BINDINGS,
                *build_gate_modal_bindings(self._gate_keymaps),
                *build_gate_numbered_branch_bindings(),
                *self._gate_action_bindings(),
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
        if self._data.origin_agent:
            yield Static(
                self._origin_text(self._data.origin_agent),
                id="custom-gate-origin",
                classes="gate-review-origin",
            )
        yield Static("Context", classes="gate-review-section-title")
        yield Static(self._notes(), id="custom-gate-notes")
        if self._data.attachments:
            yield Static("Attachments", classes="gate-review-section-title")
            yield Static(
                self._attachment_summary(),
                id="custom-gate-attachments",
            )
        yield from self._compose_gate_actions()
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
        self._sync_submission_block()
        self.focus_gate_control(1)

    def render_reviewed_content(self, content: str) -> None:
        """Re-render the preview pane after an accepted edit action."""
        if self._data.preview_text is None:
            return
        self.query_one("#custom-gate-preview", Static).update(
            markdown_document_syntax(content)
        )

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
                option_inputs=event.option_inputs,
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_debug_view(self) -> None:
        from .gate_debug_modal import show_gate_debug

        show_gate_debug(self, self._debug_context)

    def action_next_control(self) -> None:
        self.focus_gate_control(1)

    def action_previous_control(self) -> None:
        self.focus_gate_control(-1)

    def action_toggle_option(self) -> None:
        self.query_one(GateBranchControls).toggle_focused_option()

    def action_submit_primary(self) -> None:
        self.query_one(GateBranchControls).submit_primary_branch()

    def action_submit_branch(self) -> None:
        self.query_one(GateBranchControls).submit_active_branch()

    def action_submit_numbered_branch(self, branch_index: int) -> None:
        self.query_one(GateBranchControls).submit_numbered_branch(branch_index)

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
        headline = self._data.gate_title or self._data.title
        return (
            f"[bold cyan]{escape(self._data.icon)} "
            f"{escape(headline)}[/bold cyan]  "
            f"{_chip_markup(self._data.chip)}"
            f"[dim]{escape(self._data.title)}[/dim]  "
            f"[bold]{escape(self._data.sender)}[/bold]  "
            f"[dim]{escape(self._data.request_id)}[/dim]"
        )

    def _origin_text(self, origin_agent: str) -> Text:
        from sase.core.agent_identity_facade import present_agent_name

        try:
            presented = present_agent_name(origin_agent)
        except Exception:
            presented = origin_agent
        text = Text()
        text.append("Filed by ", style="dim")
        text.append(f"@{presented}", style="bold #87D7FF")
        return text

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
        text.append(f"{key_display_name(keys.submit_branch)} submit  ")
        _has_inputs, has_path = gate_declares_inputs(
            self._data.gate.options, DEFAULT_HOST_COLLECTED_PROPERTIES
        )
        if has_path:
            text.append("^t complete path  ")
        text.append_text(self.gate_action_hints())
        text.append("d debug  q cancel")
        return text


def _chip_style(color: str | None) -> str:
    """Foreground-only style; a malformed colour degrades to uncoloured bold."""
    try:
        validated = validate_color(color, "presentation.chip")
    except (AttributeError, GateError, TypeError):
        validated = None
    if validated is None:
        return "bold"
    return f"bold {validated}"


def _chip_markup(chip: GateChip | None) -> str:
    """Return the title-segment markup for a chip, or ``""`` when absent."""
    if chip is None:
        return ""
    style = _chip_style(chip.color)
    return f"[{style}]{escape(chip.glyph)} {escape(chip.label)}[/]  "


__all__ = [
    "CustomGateModal",
    "CustomGateModalData",
    "CustomGateModalResult",
]
