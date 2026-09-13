"""Data model for one displayed pager visit and the retained trail snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.ace.tui.modals.trail_strip import entry_marker
from sase.pager._line_mark import LineMark
from sase.pager._trail_chrome_text import safe_label as _safe_label
from sase.pager._trail_chrome_text import safe_optional as _safe_optional

TrailEntryState = Literal["back", "current", "forward"]

CURRENT_MARKER = "●"
MUTED_STYLE = "#8A8A8A"
CURRENT_STYLE = "bold reverse"
SECONDARY_STYLE = "#8A8A8A"
STATE_STYLES: dict[TrailEntryState, str] = {
    "back": "",
    "current": CURRENT_STYLE,
    "forward": SECONDARY_STYLE,
}


@dataclass(frozen=True, slots=True)
class PagerTrailDisplayEntry:
    """One pager visit as it should be displayed, without restorable state."""

    document_identity: str
    document_title: str
    section_identity: str
    section_title: str
    section_kind: str
    state: TrailEntryState
    line_mark: LineMark | None = None

    @property
    def icon(self) -> str:
        icon, _accent = entry_marker(self.section_kind)
        return icon

    @property
    def accent(self) -> str:
        _icon, accent = entry_marker(self.section_kind)
        return accent

    @property
    def short_label(self) -> str:
        return _with_line_mark(_safe_label(self.section_title), self.line_mark)

    @property
    def full_label(self) -> str:
        document = _safe_label(self.document_title)
        section = _safe_label(self.section_title)
        base = section if section == document else f"{document} · {section}"
        return _with_line_mark(base, self.line_mark)

    @property
    def secondary_identity(self) -> str:
        values = tuple(
            _safe_optional(value)
            for value in (
                self.section_identity,
                self.document_identity,
            )
        )
        unique = tuple(value for index, value in enumerate(values) if value)
        if not unique:
            return ""
        if len(unique) == 1:
            return unique[0]
        if unique[0] == unique[1]:
            return unique[0]
        return " · ".join(unique)

    @property
    def signature(self) -> tuple[str, str, str, str, str, str, str]:
        mark = self.line_mark
        mark_key = (
            ""
            if mark is None
            else f"{mark.section_index}:{mark.start_line}:{mark.end_line}"
        )
        return (
            self.document_identity,
            self.document_title,
            self.section_identity,
            self.section_title,
            self.section_kind,
            self.state,
            mark_key,
        )


@dataclass(frozen=True, slots=True)
class PagerTrailSnapshot:
    """Immutable presentation snapshot for the retained pager visit trail."""

    entries: tuple[PagerTrailDisplayEntry, ...]
    current_index: int

    @property
    def visible(self) -> bool:
        return self.total > 1

    @property
    def current(self) -> PagerTrailDisplayEntry:
        return self.entries[self.current_index]

    @property
    def position(self) -> int:
        return self.current_index + 1

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def back_count(self) -> int:
        return self.current_index

    @property
    def forward_count(self) -> int:
        return self.total - self.current_index - 1

    @property
    def signature(
        self,
    ) -> tuple[int, tuple[tuple[str, str, str, str, str, str, str], ...]]:
        return (self.current_index, tuple(entry.signature for entry in self.entries))


def _with_line_mark(label: str, mark: LineMark | None) -> str:
    if mark is None:
        return label
    return f"{label}{mark.suffix}"
