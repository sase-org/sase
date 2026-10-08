"""Shared decision display builders (sase-1hi.4 handoff).

One canonical Rich rendering of a Decision Sheet, shared by every surface.
Plain-text surfaces (``sase bead read``, the ``%auto`` receipt) export
:func:`pending_decisions_text` / :func:`accepted_decisions_text` through
:func:`decision_text_lines`; Rich surfaces (``sase plan show``, the ACE PLAN
lane) use the ``Text`` objects directly.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

DECISION_MODIFIED_MARK = "\u25cf"
DECISION_DEFAULT_MARK = "\u2605"
DECISION_SELECTED_MARK = "\u25c9"
DECISION_UNSELECTED_MARK = "\u25cb"
DECISION_MEMORY_MARK = "\U0001f9e0"

_PROVENANCE_CHIPS = {
    "asked": "you asked",
    "not_asked": "not asked",
    "quote_not_found": "\u26a0 quote not found \u00b7 off",
    "inherited": "approved in epic",
}


def format_decision_value(value: Any) -> str:
    """Display one decision value: toggles as ``yes``/``no`` (plan 1.6)."""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def provenance_chip(provenance: str) -> str:
    """Return the human provenance chip for a memory row."""
    return _PROVENANCE_CHIPS.get(provenance.strip(), provenance.strip())


def memory_note_names(memory: dict[str, Any]) -> list[str]:
    """Return the display note names for a memory row's selectors."""
    selectors = memory.get("selectors")
    if not isinstance(selectors, list):
        return []
    return [str(item) for item in selectors if str(item).strip()]


def _memory_type_chips(memory: dict[str, Any]) -> list[str]:
    """Return the note-kind chips (core/reference/web/new) for a memory row."""
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
    if any(
        isinstance(record, dict) and record.get("exists") is False
        for record in resolved
        if isinstance(record, dict)
    ):
        if "new" not in chips:
            chips.append("new")
    return chips


def _sheet_rows(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the sheet's rows in author order, tolerating malformed input."""
    rows = sheet.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def pending_decisions_text(sheet: dict[str, Any]) -> Text:
    """Render the pending sheet: each ask, choices, ``★`` default, memory chips."""
    text = Text()
    rows = _sheet_rows(sheet)
    for index, row in enumerate(rows):
        if index:
            text.append("\n")
        _append_pending_row(text, row)
    return text


def _append_pending_row(text: Text, row: dict[str, Any]) -> None:
    decision_id = str(row.get("id", ""))
    kind = str(row.get("kind", ""))
    ask = str(row.get("ask", ""))
    default = row.get("default")
    memory = row.get("memory")
    if kind == "choice":
        text.append(f"{DECISION_UNSELECTED_MARK} {decision_id}", style="bold")
    else:
        marker = "\u2611\ufe0f" if default is True else "\u2b1c"
        text.append(f"{marker} {decision_id}", style="bold")
    if ask:
        text.append(f"  {ask}", style="dim")
    text.append("\n")
    choices = row.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            key = str(choice.get("key", ""))
            label = str(choice.get("label", ""))
            selected = key == str(default)
            mark = (
                f"{DECISION_SELECTED_MARK}"
                if selected
                else f"{DECISION_UNSELECTED_MARK}"
            )
            star = f" {DECISION_DEFAULT_MARK}" if selected else ""
            text.append(f"  {mark} {key}{star}", style="bold" if selected else "")
            if label:
                text.append(f"  {label}", style="dim")
            text.append("\n")
    why = row.get("why")
    if isinstance(why, str) and why.strip():
        text.append(f"  {DECISION_DEFAULT_MARK} {why.strip()}", style="dim")
        text.append("\n")
    if isinstance(memory, dict):
        text.append(f"  {DECISION_MEMORY_MARK} ", style="bold")
        names = memory_note_names(memory)
        text.append(", ".join(names) if names else decision_id, style="bold")
        chips = _memory_type_chips(memory)
        if chips:
            text.append(f" \u00b7 {', '.join(chips)}", style="dim")
        provenance = str(memory.get("provenance") or "").strip()
        chip = provenance_chip(provenance)
        quote_raw = memory.get("quote")
        quote = (
            quote_raw.strip()
            if isinstance(quote_raw, str) and quote_raw.strip()
            else ""
        )
        if provenance == "quote_not_found":
            if chip:
                text.append(f" \u00b7 {chip}", style="dim")
        elif provenance == "asked" and quote:
            text.append(f" \u00b7 you asked: {quote!r}", style="dim")
        elif chip:
            # Exactly one provenance chip: a stale quote never reappears
            # next to a chip that already says otherwise (``not asked · you
            # asked: '…'``).
            text.append(f" \u00b7 {chip}", style="dim")


def accepted_decisions_text(
    sheet: dict[str, Any],
    decided_by: str | None,
    decided_via: str | None,
) -> Text:
    """Render the accepted sheet: header, ``◉`` answer, ``●`` changes."""
    text = Text()
    by = (decided_by or "reviewer").strip() or "reviewer"
    via = (decided_via or "").strip().upper()
    header = f"decided by {by}" + (f" \u00b7 {via}" if via else "")
    text.append(header, style="bold")
    for row in _sheet_rows(sheet):
        text.append("\n")
        _append_accepted_row(text, row)
    return text


def _append_accepted_row(text: Text, row: dict[str, Any]) -> None:
    decision_id = str(row.get("id", ""))
    kind = str(row.get("kind", ""))
    value = format_decision_value(row.get("value"))
    changed = bool(row.get("changed"))
    mark = f"{DECISION_MODIFIED_MARK}" if changed else ""
    default_note = "" if changed else f" {DECISION_DEFAULT_MARK}"
    text.append(
        f"{DECISION_SELECTED_MARK} {decision_id} = {value}{mark}{default_note}",
        style="bold",
    )
    memory = row.get("memory")
    if isinstance(memory, dict):
        names = memory_note_names(memory)
        if names:
            text.append(f"  {DECISION_MEMORY_MARK} {', '.join(names)}", style="dim")
    if kind == "choice":
        choices = row.get("choices")
        if isinstance(choices, list):
            others = [
                str(choice.get("key", ""))
                for choice in choices
                if isinstance(choice, dict)
                and str(choice.get("key", "")) != str(row.get("value"))
            ]
            if others:
                text.append(f"  (not: {', '.join(others)})", style="dim")


def decision_text_lines(text: Text) -> list[str]:
    """Export a builder ``Text`` as plain lines for non-Rich surfaces."""
    return text.plain.splitlines()


__all__ = [
    "accepted_decisions_text",
    "decision_text_lines",
    "format_decision_value",
    "memory_note_names",
    "pending_decisions_text",
    "provenance_chip",
]
