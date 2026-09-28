"""Launch Tab picker for the prompt bar (``gb`` / ``Ctrl+G b``).

Lists existing named tabs, the ``main`` default, and a "new tab…" path
through the search input. Choosing a tab edits the active prompt through
``set_agent_tab_directive`` (insert or replace); choosing the default
strips ``%tab``. Validation errors keep the picker open with a notice.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from sase.ace.tui.models.agent_tab_index import AgentTabCatalogEntry


@dataclass(frozen=True)
class LaunchTabPickerResult:
    """Outcome of the Launch Tab picker.

    ``action`` is ``"tab"`` (``tab`` holds the canonical name),
    ``"default"`` (strip ``%tab``), or ``"cancel"`` (leave the prompt).
    """

    action: str
    tab: str | None = None


def _named_entries(
    entries: tuple[AgentTabCatalogEntry, ...],
) -> tuple[AgentTabCatalogEntry, ...]:
    """Return catalog entries that a launch can target by name."""
    return tuple(entry for entry in entries if entry.kind == "named")


def _filter_positions(
    labels: tuple[str, ...],
    query: str,
) -> tuple[int, ...]:
    """Return label positions matching *query* (case-insensitive)."""
    needle = (query or "").casefold().strip()
    if not needle:
        return tuple(range(len(labels)))
    return tuple(pos for pos, label in enumerate(labels) if needle in label.casefold())


def _coerce_new_tab_name(raw: str) -> str:
    """Return the canonical name for typed input, or raise ValueError."""
    from sase.core.agent_tab import canonicalize_agent_tab

    stored = canonicalize_agent_tab(raw)
    if stored is None:
        raise ValueError("'%tab:main' is the default; pick it from the list.")
    return stored


class LaunchTabPickerModal(ModalScreen[LaunchTabPickerResult]):
    """Pick the launch tab for the active prompt pane."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        entries: tuple[AgentTabCatalogEntry, ...],
        *,
        current: str | None = None,
    ) -> None:
        super().__init__()
        self._named = _named_entries(entries)
        self._current = (current or "").casefold()
        self._visible: tuple[int, ...] = ()

    def compose(self) -> ComposeResult:
        """Yield the heading, search input, and one option per choice."""
        yield Label("Launch Tab…", id="launch-tab-picker-heading")
        yield Input(
            placeholder="Search or type a new tab name…",
            id="launch-tab-picker-search",
        )
        yield OptionList(*self._options(), id="launch-tab-picker-list")
        yield Label(
            "enter select · type a name + enter for a new tab · esc cancel",
            id="launch-tab-picker-hints",
        )

    def on_mount(self) -> None:
        """Focus search and preselect the prompt's current tab."""
        labels = self._row_labels()
        self._visible = tuple(range(len(labels)))
        try:
            options = self.query_one("#launch-tab-picker-list", OptionList)
            for index, label in enumerate(labels):
                if label.casefold() == self._current and self._current:
                    options.highlighted = index
                    break
        except Exception:  # noqa: BLE001 - preselect is best-effort.
            pass
        try:
            self.query_one("#launch-tab-picker-search", Input).focus()
        except Exception:  # noqa: BLE001 - focus is best-effort.
            pass

    def _row_labels(self) -> tuple[str, ...]:
        """Return row labels: the default, then one per named tab."""
        return ("main (default)", *(entry.label or "tab" for entry in self._named))

    def _options(self) -> tuple[Option, ...]:
        """Return one option per row label."""
        rows: list[Option] = [
            Option(Text("main (default)", style="#AFAFAF"), id="launch-tab-default")
        ]
        for pos, entry in enumerate(self._named):
            text = Text()
            text.append(entry.label or "tab", style="bold #AF87FF")
            text.append(f"  {entry.root_count}", style="#AFAFAF")
            rows.append(Option(text, id=f"launch-tab-{pos}"))
        return tuple(rows)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter rows to the search text, keeping selection reachable."""
        try:
            if event.input.id != "launch-tab-picker-search":
                return
            query = event.value
        except Exception:  # noqa: BLE001 - filtering is best-effort.
            return
        labels = self._row_labels()
        self._visible = _filter_positions(labels, query)
        try:
            option_list = self.query_one("#launch-tab-picker-list", OptionList)
        except Exception:  # noqa: BLE001 - filtering is best-effort.
            return
        try:
            option_list.clear_options()
            for pos in self._visible:
                label = labels[pos]
                if pos == 0:
                    option_list.add_option(
                        Option(Text(label, style="#AFAFAF"), id="launch-tab-default")
                    )
                else:
                    entry = self._named[pos - 1]
                    text = Text()
                    text.append(entry.label or "tab", style="bold #AF87FF")
                    text.append(f"  {entry.root_count}", style="#AFAFAF")
                    option_list.add_option(Option(text, id=f"launch-tab-{pos - 1}"))
            if self._visible:
                option_list.highlighted = 0
        except Exception:  # noqa: BLE001 - filtering is best-effort.
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Resolve an Enter in search: exact match, valid new tab, or error."""
        try:
            if event.input.id != "launch-tab-picker-search":
                return
            raw = event.value.strip()
        except Exception:  # noqa: BLE001 - submission is best-effort.
            return
        if not raw:
            self._dismiss_visible_or_default()
            return
        labels = self._row_labels()
        for pos in self._visible or ():
            if labels[pos].casefold() == raw.casefold():
                self._dismiss_position(pos)
                return
        if raw.casefold() in ("main", "main (default)"):
            self.dismiss(LaunchTabPickerResult(action="default"))
            return
        try:
            name = _coerce_new_tab_name(raw)
        except (ValueError, TypeError) as exc:
            self.notify(str(exc), severity="error")
            return
        self.dismiss(LaunchTabPickerResult(action="tab", tab=name))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Dismiss with the clicked row."""
        del event
        try:
            highlighted = self.query_one(
                "#launch-tab-picker-list", OptionList
            ).highlighted
        except Exception:  # noqa: BLE001 - selection is best-effort.
            highlighted = None
        positions = self._visible or ()
        if highlighted is not None and 0 <= highlighted < len(positions):
            self._dismiss_position(positions[highlighted])
        else:
            self.dismiss(LaunchTabPickerResult(action="cancel"))

    def _dismiss_visible_or_default(self) -> None:
        """Dismiss with the highlighted visible row, defaulting to main."""
        try:
            highlighted = self.query_one(
                "#launch-tab-picker-list", OptionList
            ).highlighted
        except Exception:  # noqa: BLE001 - selection is best-effort.
            highlighted = None
        positions = self._visible or ()
        if highlighted is not None and 0 <= highlighted < len(positions):
            self._dismiss_position(positions[highlighted])
        else:
            self.dismiss(LaunchTabPickerResult(action="default"))

    def _dismiss_position(self, pos: int) -> None:
        """Dismiss with the choice at row position *pos*."""
        if pos == 0:
            self.dismiss(LaunchTabPickerResult(action="default"))
            return
        index = pos - 1
        if 0 <= index < len(self._named):
            label = self._named[index].label or ""
            try:
                name = _coerce_new_tab_name(label)
            except (ValueError, TypeError) as exc:
                self.notify(str(exc), severity="error")
                return
            self.dismiss(LaunchTabPickerResult(action="tab", tab=name))
        else:
            self.dismiss(LaunchTabPickerResult(action="cancel"))

    def action_cancel(self) -> None:
        """Dismiss without changing the prompt."""
        self.dismiss(LaunchTabPickerResult(action="cancel"))


__all__ = [
    "LaunchTabPickerModal",
    "LaunchTabPickerResult",
]
