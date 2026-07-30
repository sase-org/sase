"""Immutable display state shared by the Copy as palette builder and modal."""

from __future__ import annotations

from dataclasses import dataclass

from ..copy_targets import CopyTargetCategory


@dataclass(frozen=True, slots=True)
class CopyAsRow:
    """One selectable copy representation."""

    key: str
    key_display: str
    target: str
    label: str
    category: CopyTargetCategory
    preview: str = ""

    @property
    def captures_snapshot(self) -> bool:
        """Whether dispatch must wait for the modal-free refresh."""

        return self.target in {"snapshot", "with_snapshot"}


@dataclass(frozen=True, slots=True)
class CopyAsContext:
    """Warm-only palette state captured before the modal opens."""

    group: str
    subtitle: str
    unknown_context: str
    rows: tuple[CopyAsRow, ...]

    @property
    def unknown_key_message(self) -> str:
        keys = ", ".join(row.key_display for row in self.rows)
        return f"Unknown copy key ({self.unknown_context}: {keys})"


__all__ = ["CopyAsContext", "CopyAsRow"]
