"""Refresh message for project-tag catalog warm-up (D5/D6)."""

from __future__ import annotations

from textual.message import Message


class ProjectTagCatalogWarmed(Message):
    """Posted when the tag catalog snapshot first warms in this process.

    Tagify and tag accents read only the in-memory snapshot, so surfaces
    that rendered while it was cold (agent panels, history, query
    accents, the prompt editor) repaint or rebuild on this message. Their
    caches already key on the catalog signature, so a refresh is enough.
    """


__all__ = ["ProjectTagCatalogWarmed"]
