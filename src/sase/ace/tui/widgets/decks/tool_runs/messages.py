"""``⚒ Runs`` deck load result types (epic sase-1bt)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.message import Message

from ..main_document import MainDeckDocument


@dataclass
class ToolRunsDeckLoadResult:
    """One loaded ``⚒ Runs`` document for the current subject."""

    subject_identity: object | None
    generation: int
    signature: str
    document: MainDeckDocument
    runs: tuple[Any, ...]
    total_runs: int
    truncated: bool
    live_count: int
    silent_count: int


class ToolRunsDeckLoaded(Message):
    """A ToolRuns worker finished painting for the current subject."""

    def __init__(
        self,
        document: MainDeckDocument,
        *,
        status: str,
        glyph: str,
        signature: str,
        active_card: str | None,
        n_runs: int,
        live: bool,
        silent: bool,
    ) -> None:
        """Initialize the loaded notification."""
        super().__init__()
        self.document = document
        self.status = status
        self.glyph = glyph
        self.signature = signature
        self.active_card = active_card
        self.n_runs = n_runs
        self.live = live
        self.silent = silent


__all__ = [
    "ToolRunsDeckLoaded",
    "ToolRunsDeckLoadResult",
]
