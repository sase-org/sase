"""Textual-free identity for one selectable Artifacts row.

Moved out of the Artifacts widget package so relation-index construction
can import the target record without pulling Textual.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bump when the token encoding changes shape; old tokens become invalid.
_TOKEN_VERSION = "v1"
#: ASCII Unit Separator: safe against arbitrary identifier content
#: (shas, paths, titles, Unicode) since it cannot appear in a valid part.
_TOKEN_DELIMITER = "\x1f"

#: Legacy leading-tuple kinds mapped to their owning pane, for staged
#: migration and tests. Any other kind is treated as a document-provider
#: pane (``ref:<kind>``).
_LEGACY_KIND_TO_PANE_ID: dict[str, str] = {
    "commit": "stitches",
    "bead": "beads",
    "file": "files",
    "patch": "patches",
}


@dataclass(frozen=True, slots=True)
class ArtifactEntryTarget:
    """Immutable, serializable identity for one selectable Artifacts row.

    ``pane_id`` names the owning pane (``"stitches"``, ``"beads"``,
    ``"files"``, ``"patches"``, or ``"ref:<kind>"`` for a document-provider
    pane) so identical ``parts`` in two different panes never collide and a
    cross-pane request can resolve its destination from the target alone.
    """

    pane_id: str
    parts: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.pane_id:
            raise ValueError("ArtifactEntryTarget requires a non-empty pane_id")
        if _TOKEN_DELIMITER in self.pane_id:
            raise ValueError(
                "ArtifactEntryTarget pane_id must not contain the token delimiter"
            )
        for part in self.parts:
            if not isinstance(part, str):
                raise TypeError(
                    f"ArtifactEntryTarget parts must be strings, got {part!r}"
                )
            if _TOKEN_DELIMITER in part:
                raise ValueError(
                    "ArtifactEntryTarget part must not contain the token delimiter"
                )

    def to_token(self) -> str:
        """Return the canonical, versioned, delimiter-safe token encoding."""
        return _TOKEN_DELIMITER.join((_TOKEN_VERSION, self.pane_id, *self.parts))

    @classmethod
    def from_token(cls, token: str) -> ArtifactEntryTarget:
        """Parse a token produced by :meth:`to_token`.

        Raises ``ValueError`` for malformed tokens: wrong/missing version
        marker or a missing pane id.
        """
        segments = token.split(_TOKEN_DELIMITER)
        if len(segments) < 2 or segments[0] != _TOKEN_VERSION or not segments[1]:
            raise ValueError(f"malformed artifact entry token: {token!r}")
        return cls(pane_id=segments[1], parts=tuple(segments[2:]))

    @classmethod
    def from_legacy(cls, value: tuple[str, ...]) -> ArtifactEntryTarget:
        """Convert a pre-typed ``(kind, *parts)`` tuple.

        Kept narrow and explicit for staged migration and tests — every
        checked-in production row-target helper constructs
        :class:`ArtifactEntryTarget` directly instead.
        """
        if not value:
            raise ValueError("empty legacy artifact entry target")
        kind, *rest = value
        pane_id = _LEGACY_KIND_TO_PANE_ID.get(kind, f"ref:{kind}")
        return cls(pane_id=pane_id, parts=tuple(rest))


__all__ = ["ArtifactEntryTarget"]
