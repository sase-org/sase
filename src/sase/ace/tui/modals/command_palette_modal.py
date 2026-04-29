"""Context-aware command palette modal for the ace TUI.

Phase 2 of the command palette plan (see
``plans/202604/tui_command_palette.md``). Renders a filterable list of
applicable :class:`CommandSpec` entries supplied by the caller, and
returns a :class:`CommandPaletteResult` carrying the chosen command id
(or ``None`` when the user cancels).

Phase 3 wires this modal into ``AceApp`` and dispatches the selected
command back through existing app actions / mode handlers; this module
intentionally has no knowledge of how commands execute.
"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.commands import (
    CommandPaletteResult,
    CommandSpec,
    CommandTab,
    sort_specs_by_category,
)

from .base import FilterInput

# Per-tab context badge label + accent.
_TAB_BADGE: dict[CommandTab, tuple[str, str]] = {
    "changespecs": ("CLs", "#00D7AF"),
    "agents": ("Agents", "#87D7FF"),
    "axe": ("AXE", "#FFD700"),
}

# Visual layout constants.
_KEY_COL_WIDTH = 10
_LABEL_COL_WIDTH = 36
_CATEGORY_COL_WIDTH = 18


def _score_match(spec: CommandSpec, query: str) -> int:
    """Score a spec against a filter query.

    Returns a positive score for matches, ``0`` for non-matches.
    Higher scores rank better. The relative ordering is what matters
    here, not the absolute numbers — the caller uses Python's stable
    sort to keep catalog order for ties.

    Ranking (high to low):
        1. Label exact match
        2. Label prefix match
        3. Label substring match
        4. Key display exact match (e.g. ``%n``, ``Ctrl+D``)
        5. Key display substring match
        6. Raw textual key name substring match (e.g. ``ctrl+d``)
        7. Alias / action name match
        8. Category match
        9. Command id substring match
    """
    if not query:
        return 1

    q = query.lower()
    label = spec.label.lower()

    if label == q:
        return 100
    if label.startswith(q):
        return 90
    if q in label:
        return 80

    key_disp = spec.key_display.lower()
    if key_disp == q:
        return 70
    if q in key_disp:
        return 60

    for raw in spec.key_sequence:
        if q in raw.lower():
            return 50

    for alias in spec.aliases:
        al = alias.lower()
        if al == q:
            return 45
        if al.startswith(q):
            return 40
        if q in al:
            return 30

    if q in spec.category.lower():
        return 20

    if q in spec.id.lower():
        return 10

    return 0


def _filter_specs(specs: list[CommandSpec], query: str) -> list[CommandSpec]:
    """Return *specs* filtered + ranked against *query*.

    Stable for ties (preserves catalog order).
    """
    if not query:
        return list(specs)
    scored: list[tuple[int, int, CommandSpec]] = []
    for idx, spec in enumerate(specs):
        score = _score_match(spec, query)
        if score > 0:
            scored.append((score, idx, spec))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [s for _, _, s in scored]


def _format_label(category: str) -> str:
    """Compact category badge for the row (no markup)."""
    return f"[{category}]"


def _build_row_text(spec: CommandSpec) -> Text:
    """Build a styled row for one CommandSpec."""
    text = Text()

    key = spec.key_display
    if len(key) > _KEY_COL_WIDTH:
        key = key[: _KEY_COL_WIDTH - 1] + "…"
    text.append(f"{key:<{_KEY_COL_WIDTH}}", style="bold #00D7AF")
    text.append("  ")

    label = spec.label
    if len(label) > _LABEL_COL_WIDTH:
        label = label[: _LABEL_COL_WIDTH - 1] + "…"
    text.append(f"{label:<{_LABEL_COL_WIDTH}}", style="")
    text.append("  ")

    badge = _format_label(spec.category)
    if len(badge) > _CATEGORY_COL_WIDTH:
        badge = badge[: _CATEGORY_COL_WIDTH - 1] + "…"
    text.append(f"{badge:<{_CATEGORY_COL_WIDTH}}", style="dim #87D7FF")

    return text


class CommandPaletteModal(ModalScreen[CommandPaletteResult]):
    """Filterable, context-aware palette of runnable TUI commands.

    Args:
        specs: Pre-filtered list of applicable :class:`CommandSpec`
            entries for the current tab and selection. The caller
            (Phase 3 wiring) is responsible for producing this list
            from the catalog + ``is_command_available``.
        tab: The current tab (``"changespecs"``, ``"agents"``, or
            ``"axe"``); used only for the context badge in the title.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("up", "prev_option", "Up"),
        ("down", "next_option", "Down"),
        ("ctrl+p", "prev_option", "Up"),
        ("ctrl+n", "next_option", "Down"),
    ]

    DEFAULT_CSS = ""

    def __init__(
        self,
        specs: list[CommandSpec],
        tab: CommandTab = "changespecs",
    ) -> None:
        super().__init__()
        ordered = sort_specs_by_category(specs)
        self._all_specs: list[CommandSpec] = ordered
        self._tab: CommandTab = tab
        self._filtered_specs: list[CommandSpec] = list(ordered)

    # -------- compose / mount --------

    def compose(self) -> ComposeResult:
        with Container(id="command-palette-container"):
            yield Static(self._build_title(), id="command-palette-title")
            yield FilterInput(
                placeholder="Type a command...",
                id="command-palette-filter-input",
            )
            yield OptionList(
                *self._build_options(self._filtered_specs),
                id="command-palette-list",
            )
            yield Static(
                self._build_empty_state(),
                id="command-palette-empty",
            )
            yield Static(
                "Enter run · Esc close · ↑/↓ move",
                id="command-palette-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#command-palette-filter-input", FilterInput).focus()
        self._refresh_empty_visibility()

    # -------- rendering helpers --------

    def _build_title(self) -> Text:
        text = Text()
        text.append("✦ ", style="bold #FFD700")
        text.append("Command Palette", style="bold white")
        label, color = _TAB_BADGE.get(self._tab, ("", "#87D7FF"))
        if label:
            text.append("   ")
            text.append(f"[{label}]", style=f"bold {color}")
        return text

    def _build_empty_state(self) -> Text:
        text = Text()
        text.append("No matching commands", style="dim italic")
        return text

    def _build_options(self, specs: list[CommandSpec]) -> list[Option]:
        return [Option(_build_row_text(s), id=s.id) for s in specs]

    # -------- filter handling --------

    def _apply_filter(self, query: str) -> None:
        self._filtered_specs = _filter_specs(self._all_specs, query)
        option_list = self.query_one("#command-palette-list", OptionList)
        option_list.clear_options()
        for option in self._build_options(self._filtered_specs):
            option_list.add_option(option)
        if self._filtered_specs:
            option_list.highlighted = 0
        self._refresh_empty_visibility()

    def _refresh_empty_visibility(self) -> None:
        empty = self.query_one("#command-palette-empty", Static)
        option_list = self.query_one("#command-palette-list", OptionList)
        is_empty = not self._filtered_specs
        empty.display = is_empty
        option_list.display = not is_empty

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "command-palette-filter-input":
            return
        self._apply_filter(event.value)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._submit_highlighted()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option and event.option.id is not None:
            self.dismiss(CommandPaletteResult(selected_id=str(event.option.id)))

    # -------- key navigation (forwarded from focused Input) --------

    def on_key(self, event: events.Key) -> None:
        # Up/Down/Ctrl+P/Ctrl+N work even while the Input has focus.
        if event.key == "down" or event.key == "ctrl+n":
            event.prevent_default()
            event.stop()
            self.action_next_option()
        elif event.key == "up" or event.key == "ctrl+p":
            event.prevent_default()
            event.stop()
            self.action_prev_option()

    # -------- actions --------

    def action_cancel(self) -> None:
        self.dismiss(CommandPaletteResult(selected_id=None))

    def action_next_option(self) -> None:
        if not self._filtered_specs:
            return
        self.query_one("#command-palette-list", OptionList).action_cursor_down()

    def action_prev_option(self) -> None:
        if not self._filtered_specs:
            return
        self.query_one("#command-palette-list", OptionList).action_cursor_up()

    # -------- internal --------

    def _submit_highlighted(self) -> None:
        if not self._filtered_specs:
            return
        option_list = self.query_one("#command-palette-list", OptionList)
        idx = option_list.highlighted
        if idx is None or idx < 0 or idx >= len(self._filtered_specs):
            idx = 0
        spec = self._filtered_specs[idx]
        self.dismiss(CommandPaletteResult(selected_id=spec.id))
