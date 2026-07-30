"""Recursive fuzzy file finder modal (Ctrl+R) for the prompt input.

A Telescope/fzf-style overlay that filters a pre-enumerated set of recursive
file/directory candidates as the user types.  The typed text is a transient
fuzzy query that never touches the prompt; on accept the modal dismisses with
the selected :class:`CompletionCandidate` and the caller inserts its path.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.widgets._completion_match_highlight import append_highlighted
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.recursive_file_finder import FinderModel, FuzzyMatch

# Number of result rows shown in the finder window at once.
VISIBLE_ROWS = 18

# Highlight / accent styles (concrete colours keep PNG snapshots deterministic).
_MATCH_STYLE = "bold #FFD700"
_DIR_STYLE = "bold #87D7FF"
_FILE_BASENAME_STYLE = "bold"
_DIR_PORTION_STYLE = "dim"
_SELECTED_BG = "on #1c2433"


class RecursiveFileFinderModal(ModalScreen[CompletionCandidate | None]):
    """Modal that fuzzy-filters recursive path candidates and returns one."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        root_label: str,
        candidates: list[CompletionCandidate],
        *,
        truncated: bool = False,
        initial_query: str = "",
    ) -> None:
        super().__init__()
        self._root_label = root_label
        self._truncated = truncated
        self._model = FinderModel(candidates=list(candidates), query=initial_query)

    def compose(self) -> ComposeResult:
        with Container(id="finder-dialog"):
            yield Static("", id="finder-results")
            yield Static("", id="finder-query")

    def on_mount(self) -> None:
        dialog = self.query_one("#finder-dialog", Container)
        dialog.border_subtitle = "[^N/^P ↑↓] move    [Enter] insert    [Esc] cancel"
        self._refresh_view()

    # ── Key handling ──────────────────────────────────────────────────

    def on_key(self, event: Key) -> None:
        """Own all input: query edits, navigation, accept, cancel."""
        key = event.key
        if key == "escape":
            self._finish(event, None)
            return
        if key == "enter":
            self._finish(event, self._model.selected)
            return
        if key in ("ctrl+n", "down"):
            self._consume(event)
            self._model.move(1)
            self._refresh_view()
            return
        if key in ("ctrl+p", "up"):
            self._consume(event)
            self._model.move(-1)
            self._refresh_view()
            return
        if key == "ctrl+u":
            self._consume(event)
            self._model.set_query("")
            self._refresh_view()
            return
        if key == "backspace":
            self._consume(event)
            if self._model.query:
                self._model.set_query(self._model.query[:-1])
                self._refresh_view()
            return

        char = event.character
        if char is not None and char.isprintable():
            self._consume(event)
            self._model.set_query(self._model.query + char)
            self._refresh_view()
            return

        # Swallow any other key so it does not leak to the prompt underneath.
        self._consume(event)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _finish(self, event: Key, result: CompletionCandidate | None) -> None:
        self._consume(event)
        self.dismiss(result)

    @staticmethod
    def _consume(event: Key) -> None:
        event.stop()
        event.prevent_default()

    # ── Rendering ─────────────────────────────────────────────────────

    def _refresh_view(self) -> None:
        dialog = self.query_one("#finder-dialog", Container)
        dialog.border_title = self._build_title()
        self.query_one("#finder-results", Static).update(self._build_results())
        self.query_one("#finder-query", Static).update(self._build_query_line())

    def _build_title(self) -> Text:
        title = Text()
        title.append("🔍 Recursive Finder", style="bold")
        title.append("  ")
        title.append(self._root_label, style="#FFD700")
        title.append("  ")
        title.append(f"({self._model.match_count}/{self._model.total})", style="dim")
        return title

    def _build_query_line(self) -> Text:
        line = Text()
        line.append("🔎 ", style="bold")
        if self._model.query:
            line.append(self._model.query)
        else:
            line.append("(type to filter)", style="dim italic")
        line.append("▌", style="bold #FFD700")
        return line

    def _build_results(self) -> Text:
        matches = self._model.matches
        text = Text(no_wrap=True, overflow="ellipsis")

        if self._truncated:
            text.append(
                f"  ⚠ showing first {len(self._model.candidates)} — narrow the root\n",
                style="bold #FF8C00",
            )

        if not matches:
            if not self._model.candidates:
                text.append(f"  No files found under {self._root_label}", style="dim")
            else:
                text.append("  No matches", style="dim")
            return text

        offset = self._scroll_offset(len(matches))
        if offset > 0:
            text.append(f"  ↑ {offset} more…\n", style="dim")

        window = matches[offset : offset + VISIBLE_ROWS]
        for i, (candidate, match) in enumerate(window):
            actual_idx = offset + i
            self._append_row(
                text,
                candidate,
                match,
                selected=actual_idx == self._model.index,
            )
            if i < len(window) - 1:
                text.append("\n")

        remaining = len(matches) - (offset + len(window))
        if remaining > 0:
            text.append(f"\n  ↓ {remaining} more…", style="dim")

        return text

    def _scroll_offset(self, total: int) -> int:
        if total <= VISIBLE_ROWS:
            return 0
        half = VISIBLE_ROWS // 2
        return max(0, min(self._model.index - half, total - VISIBLE_ROWS))

    def _append_row(
        self,
        text: Text,
        candidate: CompletionCandidate,
        match: FuzzyMatch,
        *,
        selected: bool,
    ) -> None:
        row = Text(no_wrap=True, overflow="ellipsis")
        row.append("▸ " if selected else "  ", style="bold #FFD700")
        row.append("📁 " if candidate.is_dir else "📄 ")

        display = candidate.display
        core = display[:-1] if display.endswith("/") else display
        basename_start = core.rfind("/") + 1
        append_highlighted(
            row,
            display,
            match.runs,
            base_style=_DIR_STYLE if candidate.is_dir else _FILE_BASENAME_STYLE,
            match_style=_MATCH_STYLE,
            segment_split=basename_start,
            dim_style=_DIR_PORTION_STYLE,
            cellwise=True,
        )

        if selected:
            row.stylize(_SELECTED_BG)
        text.append_text(row)
