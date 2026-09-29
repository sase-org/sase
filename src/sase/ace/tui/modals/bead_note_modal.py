"""Append-only bead note modal with @-attachment authoring UX."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea

#: Left-context characters where ``@`` starts a reference. Mirrors the core
#: grammar's boundary set (whitespace, quotes, brackets, ``,``/``=``) plus
#: ``<``.
_ATTACHMENT_LEFT_CONTEXT = frozenset(" \t\r\n\"'([{,=<")

_COMPLETION_CANDIDATE_LIMIT = 50
_COMPLETION_SCAN_LIMIT = 500


def attachment_trigger_at(line_before_cursor: str) -> tuple[int, str, bool] | None:
    """Return ``(at_column, query, quoted)`` for an ``@``-path trigger.

    Scans the current line up to the cursor for the last significant ``@``.
    A ``@@`` escape is skipped (the next character is never a boundary), a
    ``@attachment:`` reuse token and ``@kind:arg`` citations stay literal,
    and unquoted queries must not contain whitespace. Returns ``None`` when
    no trigger is present.
    """
    text = line_before_cursor
    index = len(text)
    while True:
        at = text.rfind("@", 0, index)
        if at < 0:
            return None
        # ``@@`` collapses to a literal ``@``: the escaped char is not a
        # boundary, so keep scanning left past the pair.
        if at > 0 and text[at - 1] == "@":
            index = at - 1
            continue
        if at > 0 and text[at - 1] not in _ATTACHMENT_LEFT_CONTEXT:
            index = at
            continue
        rest = text[at + 1 :]
        quoted = rest.startswith('"')
        query = rest[1:] if quoted else rest
        if query.startswith("@") or query.startswith("attachment:"):
            return None
        if ":" in query:
            head, _, _tail = query.partition(":")
            if "/" not in head and not head.startswith("~"):
                return None
        if not quoted and any(char in query for char in (" ", "\t", "\r")):
            return None
        return at, query, quoted


def complete_attachment_prefix(
    query: str,
    cwd: Path | str,
    *,
    limit: int = _COMPLETION_CANDIDATE_LIMIT,
) -> list[str]:
    """List filesystem completions for an ``@``-path *query*.

    Read-only keystroke path: one bounded directory listing, no subprocess,
    no provider resolution, no locks. Directories carry a trailing ``/``.
    """
    base_dir = Path(cwd) if not isinstance(cwd, Path) else cwd
    expanded = os.path.expanduser(query) if query.startswith("~") else query
    if "/" in expanded:
        dir_part, _, base = expanded.rpartition("/")
        search: Path = (
            base_dir / dir_part if not os.path.isabs(dir_part) else Path(dir_part)
        )
    else:
        base = expanded
        search = base_dir
    try:
        entries = list(os.scandir(search))[:_COMPLETION_SCAN_LIMIT]
    except OSError:
        return []
    candidates: list[str] = []
    for entry in entries:
        name = entry.name
        if not name.startswith(base):
            continue
        if name.startswith(".") and not base.startswith("."):
            continue
        try:
            suffix = "/" if entry.is_dir(follow_symlinks=True) else ""
        except OSError:
            suffix = ""
        candidates.append(f"{name}{suffix}")
    candidates.sort(key=lambda value: (not value.endswith("/"), value.lower()))
    return candidates[:limit]


def longest_common_prefix(candidates: list[str]) -> str:
    """Return the longest common prefix of *candidates* ("" when empty)."""
    if not candidates:
        return ""
    return os.path.commonprefix(candidates)


def _quote_attachment_path(path: str) -> str:
    """Quote *path* for an ``@`` reference, escaping ``\\`` and ``"``."""
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'@"{escaped}"'


def format_pasted_path_for_note(
    pasted: str,
    cwd: Path | str | None = None,
) -> str | None:
    """Format a pasted drag-and-drop path as an ``@"<path>"`` reference.

    Returns the quoted reference when *pasted* is a single line naming an
    existing regular file (resolved against *cwd*), else ``None`` so the
    paste lands verbatim.
    """
    stripped = pasted.strip()
    if not stripped or "\n" in stripped or "\r" in stripped:
        return None
    candidate = stripped
    if (
        len(candidate) >= 2
        and candidate[0] == candidate[-1]
        and candidate[0] in {"'", '"'}
    ):
        candidate = candidate[1:-1]
    if not candidate:
        return None
    path = Path(os.path.expanduser(candidate))
    if not path.is_absolute() and cwd is not None:
        path = Path(cwd) / path
    try:
        if not path.is_file():
            return None
    except OSError:
        return None
    return _quote_attachment_path(candidate)


class BeadNoteTextArea(TextArea):
    """Note editor with ``@``-path completion and paste-to-attach."""

    def __init__(
        self,
        *args: Any,
        cwd: Path | str | None = None,
        hint: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._attachment_cwd = Path(cwd) if cwd is not None else Path.cwd()
        self._attachment_hint = hint

    def _current_line_before_cursor(self) -> tuple[int, int, str]:
        row, col = self.cursor_location
        try:
            line = self.text.split("\n")[row]
        except IndexError:
            return row, col, ""
        return row, col, line[: max(0, col)]

    async def _on_paste(self, event: events.Paste) -> None:
        formatted = format_pasted_path_for_note(event.text, self._attachment_cwd)
        if formatted is not None:
            if result := self._replace_via_keyboard(formatted, *self.selection):
                self.move_cursor(result.end_location)
                self.focus()
            return
        await super()._on_paste(event)

    def action_paste(self) -> None:
        clipboard = self.app.clipboard
        formatted = format_pasted_path_for_note(clipboard, self._attachment_cwd)
        if formatted is not None:
            if result := self._replace_via_keyboard(formatted, *self.selection):
                self.move_cursor(result.end_location)
            return
        super().action_paste()

    async def on_key(self, event: events.Key) -> None:
        if event.key == "tab" and self._try_complete_attachment():
            event.prevent_default()
            event.stop()
            return
        # Anything else (including a Tab with no trigger) keeps TextArea's
        # default behavior such as indentation.

    def _try_complete_attachment(self) -> bool:
        row, col, before = self._current_line_before_cursor()
        trigger = attachment_trigger_at(before)
        if trigger is None:
            return False
        at, query, quoted = trigger
        candidates = complete_attachment_prefix(query, self._attachment_cwd)
        if not candidates:
            self._show_hint("No matching paths")
            return True
        if len(candidates) == 1:
            self._apply_completion(row, at, col, query, quoted, candidates[0])
            return True
        common = longest_common_prefix(candidates)
        base_len = len(query.rpartition("/")[2] if "/" in query else query)
        if len(common) > base_len:
            self._apply_completion(row, at, col, query, quoted, common)
            return True
        self._show_hint(f"{len(candidates)} matches — keep typing")
        return True

    def _apply_completion(
        self,
        row: int,
        at: int,
        col: int,
        query: str,
        quoted: bool,
        completion: str,
    ) -> None:
        start_col = at + 1 + (1 if quoted else 0)
        if "/" in query:
            _dir_part, _, _base = query.rpartition("/")
            start_col += len(query) - len(_base)
        is_dir = completion.endswith("/")
        if quoted:
            replacement = completion + ("" if is_dir else '"')
        elif " " in completion or "\t" in completion:
            replacement = f'"{completion.rstrip("/")}"'
            if is_dir:
                replacement = f'"{completion}"'
        else:
            replacement = completion
        if result := self._replace_via_keyboard(
            replacement, (row, start_col), (row, col)
        ):
            self.move_cursor(result.end_location)
        self._show_hint("")

    def _show_hint(self, message: str) -> None:
        if self._attachment_hint is not None:
            self._attachment_hint(message)


class BeadNoteModal(ModalScreen[str | None]):
    """Collect one non-empty note without exposing replacement semantics."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Add note")]

    def __init__(
        self,
        bead_id: str,
        initial_value: str = "",
        error: str | None = None,
        cwd: Path | str | None = None,
    ) -> None:
        super().__init__()
        self.bead_id = bead_id
        self.initial_value = initial_value
        self.initial_error = error
        self.cwd = cwd

    def compose(self) -> ComposeResult:
        with Container(id="bead-note-container", classes="bead-modal-container small"):
            yield Label(f"Add note · {self.bead_id}", classes="bead-modal-title")
            yield BeadNoteTextArea(
                self.initial_value,
                id="bead-note-text",
                cwd=self.cwd,
                hint=self._on_completion_hint,
            )
            yield Label(
                "@<path> attaches a file snapshot · Tab completes paths · "
                "paste a file path to attach it · @@ for a literal @",
                id="bead-note-hint",
                classes="bead-modal-hint",
            )
            yield Label(
                self.initial_error or "",
                id="bead-note-error",
                classes="bead-modal-error",
            )
            with Horizontal(classes="bead-modal-buttons"):
                yield Button("Add note  Ctrl+S", id="bead-note-save", variant="primary")
                yield Button("Cancel  Esc", id="bead-note-cancel")

    def on_mount(self) -> None:
        error_label = self.query_one("#bead-note-error", Label)
        error_label.display = bool(self.initial_error)
        self.query_one("#bead-note-text", BeadNoteTextArea).focus()

    def _on_completion_hint(self, message: str) -> None:
        try:
            hint = self.query_one("#bead-note-hint", Label)
        except Exception:
            return
        if message:
            hint.update(message)
        else:
            hint.update(
                "@<path> attaches a file snapshot · Tab completes paths · "
                "paste a file path to attach it · @@ for a literal @"
            )

    def show_error(self, message: str) -> None:
        """Show an inline authoring diagnostic; the typed text is kept."""
        self.initial_error = message
        try:
            error_label = self.query_one("#bead-note-error", Label)
        except Exception:
            return
        error_label.update(message)
        error_label.display = True

    @on(Button.Pressed)
    def _on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bead-note-save":
            self.action_save()
        else:
            self.action_cancel()

    def action_save(self) -> None:
        note = self.query_one("#bead-note-text", BeadNoteTextArea).text.strip()
        if not note:
            self.notify("Note cannot be empty", severity="error")
            return
        self.dismiss(note)

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "BeadNoteModal",
    "BeadNoteTextArea",
    "attachment_trigger_at",
    "complete_attachment_prefix",
    "format_pasted_path_for_note",
    "longest_common_prefix",
]
