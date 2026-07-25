"""Three-channel badge presentation for chat transcript provenance.

Every provenance state is encoded by glyph *shape*, a literal *word*, and a
*color* so the distinction survives colorblindness, dim terminals, and
screenshots.  These constants are frontend-agnostic: both the CLI table and
the ACE Chats pane render from them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CHAT_PROVENANCE_VALUES, ChatProvenance


@dataclass(frozen=True, slots=True)
class ChatProvenanceBadge:
    """Glyph, label, and color for one provenance state."""

    glyph: str
    label: str
    color: str


CHAT_PROVENANCE_BADGES: dict[ChatProvenance, ChatProvenanceBadge] = {
    "local": ChatProvenanceBadge(glyph="◇", label="local", color="#767676"),
    "shared": ChatProvenanceBadge(glyph="◆", label="shared", color="#5FD75F"),
    "remote": ChatProvenanceBadge(glyph="⇣", label="remote", color="#FFAF5F"),
    "unknown": ChatProvenanceBadge(glyph="◌", label="?", color="#585858"),
}


def chat_provenance_badge(provenance: str) -> ChatProvenanceBadge:
    """Return the badge for ``provenance``, falling back to ``unknown``.

    Unrecognized values render as ``unknown`` rather than raising: "I could
    not check" is always a truthful rendering, while guessing is not.
    """
    for value in CHAT_PROVENANCE_VALUES:
        if value == provenance:
            return CHAT_PROVENANCE_BADGES[value]
    return CHAT_PROVENANCE_BADGES["unknown"]


__all__ = [
    "CHAT_PROVENANCE_BADGES",
    "ChatProvenanceBadge",
    "chat_provenance_badge",
]
