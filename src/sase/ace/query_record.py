"""Shared pane-scoped query record for saved queries and history entries.

A :class:`QueryRecord` is what one saved-query slot or one history-stack
entry actually persists: the text the user typed (``source``), its
normalized form (``canonical``), and the digest of the pane dialect that
produced it (``profile_digest``) so a later dialect change can be detected
instead of silently reinterpreted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .query_profile.pane_registry import compiled_profile_for_builtin_pane


@dataclass(frozen=True, slots=True)
class QueryRecord:
    """One remembered query: source text, canonical text, and its digest."""

    source: str
    canonical: str
    profile_digest: str | None = None

    def to_wire(self) -> dict[str, Any]:
        """Return the deterministic, JSON-safe payload for persistence."""
        return {
            "source": self.source,
            "canonical": self.canonical,
            "profile_digest": self.profile_digest,
        }

    @classmethod
    def from_wire(cls, data: Any) -> QueryRecord | None:
        """Parse one persisted record, tolerating the pre-namespacing shape.

        The legacy stores kept a bare canonical string with no separate
        source text or profile digest; that shape degrades to a record
        whose source equals its canonical form and carries no digest.
        Returns ``None`` for anything else unrecognizable so a malformed
        entry degrades per-entry instead of poisoning the whole load.
        """
        if isinstance(data, str):
            return cls(source=data, canonical=data, profile_digest=None)
        if not isinstance(data, dict):
            return None
        canonical = data.get("canonical")
        if not isinstance(canonical, str):
            return None
        source = data.get("source")
        source = source if isinstance(source, str) else canonical
        digest = data.get("profile_digest")
        digest = digest if isinstance(digest, str) else None
        return cls(source=source, canonical=canonical, profile_digest=digest)

    def is_stale(self, pane_id: str) -> bool:
        """Return whether this record disagrees with *pane_id*'s dialect.

        A record with no stored digest (legacy, or a document-provider
        pane that never had one) is never considered stale. A pane id
        without a resolvable built-in profile is likewise never flagged --
        wiring live profile resolution for document providers into
        persistence is later epic work.
        """
        if self.profile_digest is None:
            return False
        current = compiled_profile_for_builtin_pane(pane_id)
        if current is None:
            return False
        return current.digest != self.profile_digest


def current_profile_digest(pane_id: str) -> str | None:
    """Return the current compiled-profile digest for *pane_id*, if known."""
    profile = compiled_profile_for_builtin_pane(pane_id)
    return profile.digest if profile is not None else None


__all__ = ["QueryRecord", "current_profile_digest"]
