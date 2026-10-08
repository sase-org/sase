"""Accordion widget for Plan Decisions.

Pure row-text builders are testable without a Textual pilot; the
``PlanDecisionRows`` widget renders those builders and owns the focused
row index.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Button, Static

from sase.sdd._plan_display_decisions import (
    DECISION_DEFAULT_MARK,
    DECISION_MODIFIED_MARK,
    DECISION_SELECTED_MARK,
    DECISION_UNSELECTED_MARK,
    format_decision_value,
    memory_note_names,
    provenance_chip,
)


def _memory_type_chips(memory: dict[str, Any]) -> list[str]:
    resolved = memory.get("resolved")
    if not isinstance(resolved, list):
        return []
    chips: list[str] = []
    for record in resolved:
        if not isinstance(record, dict):
            continue
        kind = str(record.get("type") or record.get("kind") or "").strip()
        if kind == "strand":
            kind = "web"
        if kind and kind not in chips:
            chips.append(kind)
    return chips


def is_unverified_row(
    row: dict[str, Any], definition: dict[str, Any] | None = None
) -> bool:
    memory = row.get("memory")
    if not isinstance(memory, dict):
        return False
    if str(memory.get("provenance") or "") == "quote_not_found":
        return True
    if definition is not None:
        authored = definition.get("default")
        effective = definition.get("effective_default", authored)
        if authored is True and effective is False and row.get("value") is False:
            return True
    return False


def collapsed_row_text(
    row: dict[str, Any], *, definition: dict[str, Any] | None = None
) -> Text:
    text = Text()
    decision_id = str(row.get("id", ""))
    kind = str(row.get("kind", ""))
    value = row.get("value")
    changed = bool(row.get("changed"))
    if kind == "toggle":
        glyph = "☑️" if value is True else "⬜"
        shown = format_decision_value(value)
    else:
        glyph = DECISION_SELECTED_MARK
        shown = str(value)
    mark = f" {DECISION_MODIFIED_MARK}" if changed else ""
    text.append(f"{glyph} {decision_id}  {shown}{mark}", style="bold")
    if changed:
        # Gold marker is also a span so colour is not the only cue;
        # detail text names the default separately.
        try:
            start = len(f"{glyph} {decision_id}  {shown}")
            text.stylize("#FFD700", start, start + 2)
        except Exception:
            pass
    text.append("\n")
    memory = row.get("memory")
    ask = str(row.get("ask", ""))
    if isinstance(memory, dict):
        names = memory_note_names(memory)
        chips = _memory_type_chips(memory)
        provenance = provenance_chip(str(memory.get("provenance") or ""))
        second = f"🧠 {', '.join(names) if names else decision_id}"
        if chips:
            second += f" · {', '.join(chips)}"
        if provenance:
            second += f" · {provenance}"
        text.append(second, style="dim")
        if ask.strip() and not is_unverified_row(row, definition):
            truncated = ask.strip()
            if len(truncated) > 60:
                truncated = truncated[:57] + "..."
            text.append(f"  {truncated}", style="dim")
    else:
        truncated = ask.strip()
        if len(truncated) > 80:
            truncated = truncated[:77] + "..."
        text.append(truncated, style="dim")
    return text


def expanded_row_text(
    row: dict[str, Any], *, definition: dict[str, Any] | None = None
) -> Text:
    text = Text()
    decision_id = str(row.get("id", ""))
    kind = str(row.get("kind", ""))
    value = row.get("value")
    default = row.get("default")
    changed = bool(row.get("changed"))
    ask = str(row.get("ask", ""))
    if kind == "toggle":
        glyph = "☑️" if value is True else "⬜"
        shown = format_decision_value(value)
        mark = f" {DECISION_MODIFIED_MARK}" if changed else ""
        text.append(f"{glyph} {decision_id}  {shown}{mark}", style="bold")
        if changed:
            try:
                start = len(f"{glyph} {decision_id}  {shown}")
                text.stylize("#FFD700", start, start + 2)
            except Exception:
                pass
        text.append("\n")
    else:
        text.append(f"{DECISION_SELECTED_MARK} {decision_id}", style="bold")
        text.append("\n")
    if ask.strip():
        text.append(ask.strip())
        text.append("\n")
    choices = row.get("choices")
    if kind == "choice" and isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            key = str(choice.get("key", ""))
            label = str(choice.get("label", ""))
            selected = str(value) == key
            mark = DECISION_SELECTED_MARK if selected else DECISION_UNSELECTED_MARK
            star = f" {DECISION_DEFAULT_MARK}" if str(default) == key else ""
            text.append(f"  {mark} {key}{star}", style="bold" if selected else "")
            if label:
                text.append(f"  {label}", style="dim")
            text.append("\n")
    elif kind == "toggle":
        for option_value, label in ((True, "yes"), (False, "no")):
            selected = value is option_value
            mark = (
                "☑️"
                if (option_value and selected) or (not option_value and selected)
                else "⬜"
            )
            star = f" {DECISION_DEFAULT_MARK}" if default is option_value else ""
            text.append(f"  {mark} {label}{star}")
            text.append("\n")
    why = row.get("why")
    if isinstance(why, str) and why.strip():
        text.append(f"  {DECISION_DEFAULT_MARK} {why.strip()}", style="dim")
        text.append("\n")
    if default is not None:
        text.append(f"  default: {format_decision_value(default)}", style="dim")
        text.append("\n")
    memory = row.get("memory")
    if isinstance(memory, dict):
        names = memory_note_names(memory)
        chips = _memory_type_chips(memory)
        provenance = provenance_chip(str(memory.get("provenance") or ""))
        quote = memory.get("quote")
        if is_unverified_row(row, definition) and value is not True:
            quote_text = str(quote).strip() if isinstance(quote, str) else ""
            text.append(
                f'  ⚠ "{quote_text}" — not in your messages · off until you turn it on',
                style="yellow",
            )
            text.append("\n")
        else:
            text.append("  🧠 ", style="bold")
            text.append(", ".join(names) if names else decision_id, style="bold")
            if chips:
                text.append(f" · {', '.join(chips)}", style="dim")
            if provenance:
                text.append(f" · {provenance}", style="dim")
            text.append("\n")
            if isinstance(quote, str) and quote.strip():
                text.append(f'  you asked: "{quote.strip()}"', style="dim")
                text.append("\n")
    return text


class PlanDecisionRows(VerticalScroll):
    """Accordion of decision rows; the modal owns the draft."""

    def __init__(
        self,
        sheet_rows: list[dict[str, Any]],
        definitions: list[dict[str, Any]] | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._rows = list(sheet_rows)
        self._definitions = list(definitions or [])
        self._by_id = {
            str(d.get("id", "")): d for d in self._definitions if str(d.get("id", ""))
        }
        self._focused_index = 0 if self._rows else -1

    @property
    def focused_index(self) -> int:
        return self._focused_index

    @property
    def focused_id(self) -> str | None:
        if 0 <= self._focused_index < len(self._rows):
            return str(self._rows[self._focused_index].get("id", ""))
        return None

    def update_rows(self, sheet_rows: list[dict[str, Any]]) -> None:
        self._rows = list(sheet_rows)
        if self._focused_index >= len(self._rows):
            self._focused_index = len(self._rows) - 1
        if self._rows and self._focused_index < 0:
            self._focused_index = 0
        if self.is_mounted:
            self.refresh_rows()

    def set_focused_index(self, index: int) -> None:
        if not self._rows:
            self._focused_index = -1
            return
        self._focused_index = max(0, min(index, len(self._rows) - 1))
        if self.is_mounted:
            self.refresh_rows()

    def compose(self):  # type: ignore[no-untyped-def]
        for index, row in enumerate(self._rows):
            yield Button(
                self._row_label(index, row),
                id=f"plan-decision-{index}",
                classes="plan-decision-row",
            )
            yield Static(
                "",
                id=f"plan-decision-detail-{index}",
                classes="plan-decision-detail",
            )

    def on_mount(self) -> None:
        self.refresh_rows()

    def _row_label(self, index: int, row: dict[str, Any]) -> Text:
        definition = self._by_id.get(str(row.get("id", "")))
        if index == self._focused_index:
            return expanded_row_text(row, definition=definition)
        return collapsed_row_text(row, definition=definition)

    def refresh_rows(self) -> None:
        for index, row in enumerate(self._rows):
            try:
                button = self.query_one(f"#plan-decision-{index}", Button)
            except Exception:
                continue
            button.label = self._row_label(index, row)
            try:
                detail = self.query_one(f"#plan-decision-detail-{index}", Static)
                if index == self._focused_index:
                    detail.update("")
                    detail.add_class("hidden")
                else:
                    detail.update("")
                    detail.add_class("hidden")
            except Exception:
                pass

    def visible_control_ids(self) -> list[str]:
        return [f"plan-decision-{index}" for index in range(len(self._rows))]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if not button_id.startswith("plan-decision-"):
            return
        try:
            index = int(button_id.rsplit("-", 1)[1])
        except ValueError:
            return
        self.set_focused_index(index)


__all__ = [
    "PlanDecisionRows",
    "collapsed_row_text",
    "expanded_row_text",
    "is_unverified_row",
]
