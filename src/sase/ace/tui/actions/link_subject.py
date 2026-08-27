"""App-level link-graph subject resolution and O(1) edge lookup."""

from __future__ import annotations

from typing import Any

from ..relations.artifact_links import load_artifact_links_snapshot
from ..relations.link_index import LinkChip, LinkIndex, link_index_for_snapshot
from ..relations.link_subject import LinkSubject, selected_link_subject


class LinkSubjectMixin:
    """Resolve the selected entity's link-graph subject and its edges.

    One projection point shared by every tab (bead:sase-ug.5): the rail,
    ``$``, and the ``$0`` panel all read through :meth:`link_edges_for_selection`
    instead of resolving a subject or scanning the aggregate themselves.
    """

    current_tab: Any

    def link_edges_for_selection(self) -> tuple[LinkChip, ...]:
        """Return the ordered link chips for the currently selected entity.

        Empty when the current row cannot be resolved to a link-graph
        subject at all, or resolves to one with no recorded edges -- the
        same "nothing to show" state, by design (see the rail's
        invisibility contract).
        """

        subject: LinkSubject | None = selected_link_subject(self)
        if subject is None:
            return ()
        snapshot = load_artifact_links_snapshot(None)
        index: LinkIndex = link_index_for_snapshot(snapshot)
        return index.chips_for(subject.ref)


__all__ = ["LinkSubjectMixin"]
