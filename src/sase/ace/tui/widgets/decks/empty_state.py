"""Empty-state renderable for deck panels."""

from __future__ import annotations

from typing import Literal

from rich.align import Align
from rich.console import RenderableType
from rich.text import Text

from .model import DeckId

SubjectKind = Literal["agent", "tribe", "node", "attempt", "none"]


_MESSAGES: dict[tuple[str, str], str] = {
    ("main", "none"): "No agent selected",
    ("files", "agent"): "No files for this agent",
    ("files", "node"): "No files for this node",
    ("files", "tribe"): "No files for this tribe",
    ("files", "attempt"): "Files are not shown for attempt views",
    ("files", "none"): "No agent selected",
    ("tools", "agent"): "No LLM calls for this agent",
    ("tools", "node"): "No LLM calls for this node",
    ("tools", "tribe"): "No LLM calls for this tribe",
    ("tools", "attempt"): "LLM calls are not shown for attempt views",
    ("tools", "none"): "No agent selected",
}


def deck_empty_state(
    deck: DeckId,
    *,
    subject_kind: SubjectKind,
    hint: str | None,
) -> RenderableType:
    """Render a centered empty-state card for ``deck``."""
    if deck is DeckId.MAIN and subject_kind != "none":
        message = "No agent selected"
    else:
        message = _MESSAGES.get((deck.value, subject_kind), "No agent selected")
    body = Text()
    body.append(message, style="dim")
    if hint:
        body.append("\n", style="")
        body.append(hint, style="dim")
    return Align.center(body, vertical="middle")
