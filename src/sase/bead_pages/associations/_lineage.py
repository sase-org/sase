"""Cycle-safe bead lineage discovery for root association roll-up."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from sase.bead.model import Issue


def association_source_beads(
    issues: Iterable[Issue],
) -> dict[str, tuple[str, ...]]:
    """Return the direct source beads represented on every bead page.

    Every descendant page represents only itself. A true root bead additionally
    represents all descendants whose ``parent_id`` chain reaches it. Cycles and
    dangling parent chains have no root and therefore remain direct-only.
    """

    by_id = {issue.id: issue for issue in issues}
    descendants: defaultdict[str, list[str]] = defaultdict(list)
    for bead_id in sorted(by_id):
        root_id = _root_id(bead_id, by_id)
        if root_id is not None and root_id != bead_id:
            descendants[root_id].append(bead_id)
    return {
        bead_id: (bead_id, *descendants.get(bead_id, ())) for bead_id in sorted(by_id)
    }


def _root_id(bead_id: str, by_id: dict[str, Issue]) -> str | None:
    seen: set[str] = set()
    current = bead_id
    while True:
        if current in seen:
            return None
        seen.add(current)
        issue = by_id.get(current)
        if issue is None:
            return None
        if issue.parent_id is None:
            return issue.id
        current = issue.parent_id


__all__ = ["association_source_beads"]
