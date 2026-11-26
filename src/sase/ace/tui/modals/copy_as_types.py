"""Immutable display state shared by the Copy as palette builder and modal."""

from __future__ import annotations

from dataclasses import dataclass

from ..copy_targets import CopyTargetCategory


@dataclass(frozen=True, slots=True)
class CopyAsSection:
    """One headed group inside a section-based Copy as palette."""

    id: str
    title: str
    dim: bool = False


@dataclass(frozen=True, slots=True)
class CopyAsRow:
    """One selectable copy representation."""

    key: str
    key_display: str
    target: str
    label: str
    category: CopyTargetCategory | None = None
    preview: str = ""
    disabled_reason: str | None = None
    section: str | None = None
    marker: str | None = None
    badge: str | None = None
    value: str | None = None

    @property
    def captures_snapshot(self) -> bool:
        """Whether dispatch must wait for the modal-free refresh."""

        return self.target in {"snapshot", "with_snapshot"}


_DEFAULT_COPY_AS_FOOTER = "enter select  ·  j/k or ↑/↓ navigate  ·  q/esc cancel"


@dataclass(frozen=True, slots=True)
class CopyAsContext:
    """Warm-only palette state captured before the modal opens."""

    group: str
    subtitle: str
    unknown_context: str
    rows: tuple[CopyAsRow, ...]
    title: str = "Copy as…"
    sections: tuple[CopyAsSection, ...] = ()
    footer: str | None = None
    unknown_key_message: str | None = None
    initial_row_key: str | None = None
    key_width: int = 9
    label_width: int | None = None
    preview_pane: bool = False
    show_marker_gutter: bool = False

    @property
    def resolved_footer(self) -> str:
        """Footer text, falling back to today's palette footer."""

        return self.footer if self.footer is not None else _DEFAULT_COPY_AS_FOOTER

    @property
    def resolved_unknown_key_message(self) -> str:
        """Unknown-key toast, falling back to the row-key listing."""

        if self.unknown_key_message is not None:
            return self.unknown_key_message
        keys = ", ".join(row.key_display for row in self.rows)
        return f"Unknown copy key ({self.unknown_context}: {keys})"

    @property
    def wants_marker_gutter(self) -> bool:
        """Whether rows render the two-column marker gutter."""

        return self.show_marker_gutter or any(
            row.marker is not None for row in self.rows
        )


__all__ = ["CopyAsContext", "CopyAsRow", "CopyAsSection"]
