"""Single-keypress chooser for acting on an Agents-tab node."""

from __future__ import annotations

from collections.abc import Mapping
import time
from dataclasses import dataclass
from typing import Final, Literal

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

AgentActionSection = Literal[
    "gate",
    "patch",
    "archive",
    "read",
    "stranded",
    "hijack_keep",
    "hijack_fresh",
    "hijack_other",
]

#: Guidance footer shared by the chooser modal.
_AGENT_ACTION_FOOTER: Final = "Up/Down or j/k move - Enter select - Esc cancel"


@dataclass(frozen=True)
class AgentActionChoice:
    """One visible agent-action chooser choice."""

    result: str
    section: AgentActionSection
    label: str
    detail: str | None
    glyph: str
    glyph_style: str
    badge: str | None
    badge_style: str | None
    age: str | None
    hotkey: str | None = None
    disabled_reason: str | None = None
    pending: bool = False
    inline_detail: bool = False
    action_target: str | None = None


def _badge_text(choice: AgentActionChoice) -> str:
    if choice.badge and choice.age:
        return f"{choice.badge} · {choice.age}"
    return choice.badge or choice.age or ""


class AgentActionChooserModal(ModalScreen[str | None]):
    """Pick one action for an agent node, returning ``None`` when cancelled.

    The modal takes a generic view model and knows nothing about ``Agent``
    rows or notifications: callers pass ordered choices (gates first, the
    Patch last) plus a title such as ``"Act on foo.bar"``. Direct keys are
    assigned deterministically: a lone gate row gets ``g``; several gate
    rows get ``1``-``9`` in display order with ``g`` kept as a hidden alias
    for the first gate; the Patch row gets ``p``.
    """

    BINDINGS = [
        Binding("enter", "select_current", "Select", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
        Binding("j", "cursor_down", "Next", show=False),
        Binding("k", "cursor_up", "Previous", show=False),
        Binding("down", "cursor_down", "Next", show=False),
        Binding("up", "cursor_up", "Previous", show=False),
    ]

    def __init__(
        self,
        choices: tuple[AgentActionChoice, ...] | list[AgentActionChoice],
        *,
        title: str,
        initial_index: int | None = None,
        primary_result: str | None = None,
        header: RenderableType | None = None,
        title_badge: str | None = None,
        section_subtitles: Mapping[str, str] | None = None,
        arm_delay_seconds: float = 0.0,
        footer_text: str = _AGENT_ACTION_FOOTER,
    ) -> None:
        super().__init__()
        normalized = tuple(choices)
        if not normalized:
            raise ValueError("AgentActionChooserModal needs at least one choice")
        self._choices = normalized
        self._title_text = title
        selected_index = 0 if initial_index is None else initial_index
        self._selected = max(0, min(selected_index, len(normalized) - 1))
        self._primary_result = primary_result
        self._header = header
        self._title_badge = title_badge
        self._section_subtitles = dict(section_subtitles or {})
        self._arm_delay_seconds = max(0.0, float(arm_delay_seconds))
        self._footer_text = footer_text
        self._mounted_at: float | None = None
        self._key_to_index = self._assign_keys(normalized)
        self._dismissed = False
        if title_badge or header is not None or section_subtitles:
            self._hijack_recovery_layout = True
            self.add_class("hijack-recovery")
        else:
            self._hijack_recovery_layout = False

    @staticmethod
    def _assign_keys(choices: tuple[AgentActionChoice, ...]) -> dict[str, int]:
        gate_indexes = [
            index for index, choice in enumerate(choices) if choice.section == "gate"
        ]
        keys: dict[str, int] = {}
        for index, choice in enumerate(choices):
            if choice.hotkey and choice.hotkey not in keys:
                keys[choice.hotkey] = index
        if len(gate_indexes) == 1:
            keys.setdefault("g", gate_indexes[0])
        else:
            for position, index in enumerate(gate_indexes):
                if position < 9:
                    keys.setdefault(str(position + 1), index)
            if gate_indexes:
                keys.setdefault("g", gate_indexes[0])
        for index, choice in enumerate(choices):
            if choice.section == "patch":
                keys.setdefault("p", index)
            if choice.section == "stranded":
                keys.setdefault("s", index)
        return keys

    @property
    def choices(self) -> tuple[AgentActionChoice, ...]:
        """Return the stable visible choices in display order."""
        return self._choices

    @property
    def key_to_index(self) -> dict[str, int]:
        """Return the assigned direct key for each row index."""
        return dict(self._key_to_index)

    @property
    def primary_label(self) -> str:
        """Return the label of the primary (first) action."""
        index = self._primary_index()
        return self._choices[index].label if index is not None else "decide later"

    @property
    def guidance_text(self) -> str:
        """Return the guidance line naming the primary action."""
        if self._primary_index() is None:
            return "Esc decide later · or press a key"
        return f"⏎ again → {self.primary_label} · or press a key"

    @property
    def selected_index(self) -> int:
        """Return the currently highlighted row index."""
        return self._selected

    def display_key(self, index: int) -> str:
        """Return the keycap shown for one row."""
        choice = self._choices[index]
        if choice.hotkey:
            return choice.hotkey
        if choice.section == "patch":
            return "p"
        if choice.section == "stranded":
            return "s"
        gate_indexes = [
            i for i, item in enumerate(self._choices) if item.section == "gate"
        ]
        if len(gate_indexes) == 1:
            return "g"
        position = gate_indexes.index(index)
        if position < 9:
            return str(position + 1)
        return ""

    def compose(self) -> ComposeResult:
        with Container(id="agent-action-container"):
            yield Static(self._title_renderable(), id="agent-action-title")
            if self._header is not None:
                yield Static(self._header, id="agent-action-header")
            yield Static(self.guidance_text, id="agent-action-guidance")
            with VerticalScroll(id="agent-action-list"):
                archive_indexes = [
                    index
                    for index, choice in enumerate(self._choices)
                    if choice.section == "archive"
                ]
                read_indexes = [
                    index
                    for index, choice in enumerate(self._choices)
                    if choice.section == "read"
                ]
                gate_indexes = [
                    index
                    for index, choice in enumerate(self._choices)
                    if choice.section == "gate"
                ]
                patch_indexes = [
                    index
                    for index, choice in enumerate(self._choices)
                    if choice.section == "patch"
                ]
                stranded_indexes = [
                    index
                    for index, choice in enumerate(self._choices)
                    if choice.section == "stranded"
                ]
                hijack_keep_indexes = [
                    index
                    for index, choice in enumerate(self._choices)
                    if choice.section == "hijack_keep"
                ]
                hijack_fresh_indexes = [
                    index
                    for index, choice in enumerate(self._choices)
                    if choice.section == "hijack_fresh"
                ]
                hijack_other_indexes = [
                    index
                    for index, choice in enumerate(self._choices)
                    if choice.section == "hijack_other"
                ]
                if archive_indexes:
                    yield Static("ARCHIVE", classes="agent-action-section")
                    for index in archive_indexes:
                        yield Static(
                            self._row_renderable(
                                index, focused=index == self._selected
                            ),
                            id=f"agent-action-row-{index}",
                            classes=self._row_classes(index),
                        )
                if read_indexes:
                    yield Static("READ", classes="agent-action-section")
                    for index in read_indexes:
                        yield Static(
                            self._row_renderable(
                                index, focused=index == self._selected
                            ),
                            id=f"agent-action-row-{index}",
                            classes=self._row_classes(index),
                        )
                if gate_indexes:
                    header = "GATE" if len(gate_indexes) == 1 else "GATES"
                    yield Static(header, classes="agent-action-section")
                    for index in gate_indexes:
                        yield Static(
                            self._row_renderable(
                                index, focused=index == self._selected
                            ),
                            id=f"agent-action-row-{index}",
                            classes=self._row_classes(index),
                        )
                if stranded_indexes:
                    yield Static(
                        self._section_heading("stranded", "STRANDED"),
                        classes="agent-action-section",
                    )
                    for index in stranded_indexes:
                        yield Static(
                            self._row_renderable(
                                index, focused=index == self._selected
                            ),
                            id=f"agent-action-row-{index}",
                            classes=self._row_classes(index),
                        )
                if hijack_keep_indexes:
                    yield Static(
                        self._section_heading("hijack_keep", "KEEP THE WORK"),
                        classes="agent-action-section hijack-section",
                    )
                    for index in hijack_keep_indexes:
                        yield Static(
                            self._row_renderable(
                                index, focused=index == self._selected
                            ),
                            id=f"agent-action-row-{index}",
                            classes=self._row_classes(index),
                        )
                if hijack_fresh_indexes:
                    yield Static(
                        self._section_heading("hijack_fresh", "START OVER"),
                        classes="agent-action-section hijack-section",
                    )
                    for index in hijack_fresh_indexes:
                        yield Static(
                            self._row_renderable(
                                index, focused=index == self._selected
                            ),
                            id=f"agent-action-row-{index}",
                            classes=self._row_classes(index),
                        )
                if hijack_other_indexes:
                    yield Static(
                        self._section_heading("hijack_other", "INSPECT OR LEAVE"),
                        classes="agent-action-section hijack-section",
                    )
                    for index in hijack_other_indexes:
                        yield Static(
                            self._row_renderable(
                                index, focused=index == self._selected
                            ),
                            id=f"agent-action-row-{index}",
                            classes=self._row_classes(index),
                        )
                if patch_indexes:
                    yield Static(
                        self._section_heading("patch", "PATCH"),
                        classes=(
                            "agent-action-section hijack-section"
                            if self._hijack_recovery_layout
                            else "agent-action-section"
                        ),
                    )
                    for index in patch_indexes:
                        yield Static(
                            self._row_renderable(
                                index, focused=index == self._selected
                            ),
                            id=f"agent-action-row-{index}",
                            classes=self._row_classes(index),
                        )
            yield Static(self._footer_text, id="agent-action-footer")

    def on_mount(self) -> None:
        self._mounted_at = time.monotonic()
        self._refresh()

    def on_key(self, event: events.Key) -> None:
        """Handle direct choices and contain unused printable keys."""
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            if self._enter_is_disarmed():
                return
            self.action_select_current()
            return
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return
        if event.key in {"j", "down"}:
            event.prevent_default()
            event.stop()
            self.action_cursor_down()
            return
        if event.key in {"k", "up"}:
            event.prevent_default()
            event.stop()
            self.action_cursor_up()
            return
        if event.key == "q":
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return

        character = event.character if event.character else ""
        if character in self._key_to_index:
            event.prevent_default()
            event.stop()
            self._select_index(self._key_to_index[character])
            return
        if event.character and event.character.isprintable():
            event.prevent_default()
            event.stop()

    def on_click(self, event: events.Click) -> None:
        """Select a choice when any part of its row is clicked."""
        widget = event.widget
        while widget is not None:
            widget_id = getattr(widget, "id", None)
            prefix = "agent-action-row-"
            if isinstance(widget_id, str) and widget_id.startswith(prefix):
                try:
                    index = int(widget_id.removeprefix(prefix))
                except ValueError:
                    return
                if 0 <= index < len(self._choices):
                    event.prevent_default()
                    event.stop()
                    self._select_index(index)
                return
            widget = getattr(widget, "parent", None)

    def action_cancel(self) -> None:
        self._dismiss_once(None)

    def action_select_current(self) -> None:
        self._select_index(self._selected)

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def _move(self, delta: int) -> None:
        self._selected = (self._selected + delta) % len(self._choices)
        self._refresh()

    def _select_index(self, index: int) -> None:
        choice = self._choices[index]
        if choice.pending:
            return
        if choice.disabled_reason:
            notify = getattr(self.app, "notify", None)
            if callable(notify):
                notify(choice.disabled_reason, severity="warning")
            return
        self._dismiss_once(choice.result)

    def _dismiss_once(self, result: str | None) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(result)

    def _refresh(self) -> None:
        if not self.is_mounted:
            return
        for index in range(len(self._choices)):
            focused = index == self._selected
            row = self.query_one(f"#agent-action-row-{index}", Static)
            row.update(self._row_renderable(index, focused=focused))
            row.set_class(focused, "focused")
            if focused:
                row.scroll_visible(animate=False)
        self.query_one("#agent-action-guidance", Static).update(self.guidance_text)

    def update_choices(
        self,
        choices: tuple[AgentActionChoice, ...] | list[AgentActionChoice],
        *,
        primary_result: str | None = None,
        selected_result: str | None = None,
    ) -> None:
        """Update row content in place while preserving the focused action."""
        normalized = tuple(choices)
        if len(normalized) != len(self._choices) or any(
            old.result != new.result or old.section != new.section
            for old, new in zip(self._choices, normalized, strict=True)
        ):
            raise ValueError("updated chooser choices must preserve result order")
        previous_selected_result = self._choices[self._selected].result
        self._choices = normalized
        self._key_to_index = self._assign_keys(normalized)
        if primary_result is not None or self._primary_result is not None:
            self._primary_result = primary_result
        self._selected = next(
            (
                index
                for index, choice in enumerate(normalized)
                if choice.result == (selected_result or previous_selected_result)
            ),
            self._selected,
        )
        self._refresh()

    def update_header(self, header: RenderableType | None) -> None:
        """Replace the optional header renderable in place."""
        self._header = header
        if not self.is_mounted:
            return
        widget = self.query("#agent-action-header")
        if header is None:
            if widget:
                widget.first().remove()
            return
        if widget:
            widget.first().update(header)  # type: ignore[attr-defined]
        else:
            title = self.query_one("#agent-action-title", Static)
            container = self.query_one("#agent-action-container", Container)
            container.mount(Static(header, id="agent-action-header"), after=title)

    def update_title_badge(self, badge: str | None) -> None:
        """Replace the optional right-aligned title badge in place."""
        self._title_badge = badge
        if self.is_mounted:
            self.query_one("#agent-action-title", Static).update(
                self._title_renderable()
            )

    def _primary_index(self) -> int | None:
        if self._primary_result is not None:
            index = next(
                (
                    i
                    for i, choice in enumerate(self._choices)
                    if choice.result == self._primary_result
                ),
                None,
            )
            if index is None:
                return None
            choice = self._choices[index]
            return index if choice.disabled_reason is None else None
        return next(
            (
                index
                for index, choice in enumerate(self._choices)
                if not choice.pending and choice.disabled_reason is None
            ),
            None,
        )

    def _enter_is_disarmed(self) -> bool:
        return (
            self._mounted_at is not None
            and time.monotonic() - self._mounted_at < self._arm_delay_seconds
        )

    def _title_renderable(self) -> RenderableType:
        if not self._title_badge:
            return self._title_text
        title = Text(self._title_text, style="bold")
        badge = Text(self._title_badge, style="bold #FF5FAF")
        table = Table.grid(expand=True)
        table.add_column(ratio=1, overflow="ellipsis")
        table.add_column(justify="right", no_wrap=True)
        table.add_row(title, badge)
        return table

    def _section_heading(self, section: str, title: str) -> RenderableType:
        subtitle = self._section_subtitles.get(section)
        if not subtitle:
            return title
        heading = Text(title)
        heading.append(" · ", style="dim")
        heading.append(subtitle, style="dim")
        return heading

    def _row_renderable(self, index: int, *, focused: bool) -> Table:
        choice = self._choices[index]
        disabled = choice.pending or choice.disabled_reason is not None
        pointer_style = "dim" if disabled else ("bold #87D7FF" if focused else "dim")
        key_style = (
            "dim"
            if disabled
            else ("bold black on #87D7FF" if focused else "bold #87D7FF")
        )
        label_style = "dim" if disabled else "bold #F8F8F2"

        first = Text(no_wrap=True, overflow="ellipsis")
        first.append("› " if focused else "  ", style=pointer_style)
        display_key = self.display_key(index)
        if display_key:
            first.append("[", style="dim")
            first.append(display_key, style=key_style)
            first.append("] ", style="dim")
        if choice.glyph:
            first.append(choice.glyph, style="dim" if disabled else choice.glyph_style)
            first.append(" ", style="dim")
        first.append(choice.label, style=label_style)

        inline_detail = choice.disabled_reason or choice.detail
        if choice.pending:
            inline_detail = inline_detail or "computing…"
        if choice.inline_detail and inline_detail:
            first.append(" · ", style="dim")
            first.append(inline_detail, style="dim")

        badge = Text(no_wrap=True, overflow="ellipsis")
        badge_text = _badge_text(choice)
        if badge_text:
            badge.append(badge_text, style=choice.badge_style or "")

        table = Table.grid(expand=True)
        table.add_column(ratio=1, overflow="ellipsis")
        table.add_column(justify="right", no_wrap=True)
        table.add_row(first, badge)

        if choice.detail and not choice.inline_detail:
            second = Text(no_wrap=True, overflow="ellipsis")
            second.append("      ", style="dim")
            second.append(choice.disabled_reason or choice.detail, style="dim")
            table.add_row(second, Text())
        return table

    def _row_classes(self, index: int) -> str:
        classes = ["agent-action-row"]
        if self._choices[index].inline_detail:
            classes.append("inline")
        if index == self._selected:
            classes.append("focused")
        return " ".join(classes)


__all__ = [
    "AgentActionChoice",
    "AgentActionChooserModal",
]
