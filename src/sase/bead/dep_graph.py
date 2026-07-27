"""Pure read-side dependency graph over bead issue models.

The event-sourced store remains the authority for dependency behavior.  This
module deliberately builds a small Python read adapter from an issue list a
caller already fetched; it can move behind the Rust boundary later without
changing the CLI consumers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from sase.bead.model import Issue, Status

DepDirection = Literal["in", "out"]


@dataclass(frozen=True)
class DepEdge:
    """One directed dependency edge and its recorded provenance."""

    issue_id: str
    depends_on_id: str
    created_at: str
    created_by: str
    satisfied: bool


@dataclass(frozen=True)
class DepTraversalNode:
    """One node in a terminating, depth-bounded dependency walk."""

    issue_id: str
    edge: DepEdge | None
    repeat: bool
    cycle: bool
    truncated: bool
    children: tuple[DepTraversalNode, ...]


@dataclass(frozen=True)
class DepGraph:
    """An immutable, deterministically ordered dependency graph."""

    issues: Mapping[str, Issue]
    forward: Mapping[str, tuple[DepEdge, ...]]
    reverse: Mapping[str, tuple[DepEdge, ...]]
    edges: tuple[DepEdge, ...]

    @classmethod
    def build(cls, issues: Iterable[Issue]) -> DepGraph:
        """Build one graph from an already-fetched issue collection."""
        issue_index = {issue.id: issue for issue in issues}
        ordered_issues = {
            issue_id: issue_index[issue_id] for issue_id in sorted(issue_index)
        }

        edges = tuple(
            sorted(
                (
                    DepEdge(
                        issue_id=issue.id,
                        depends_on_id=dependency.depends_on_id,
                        created_at=dependency.created_at,
                        created_by=dependency.created_by,
                        satisfied=(
                            dependency.depends_on_id in issue_index
                            and issue_index[dependency.depends_on_id].status
                            == Status.CLOSED
                        ),
                    )
                    for issue in ordered_issues.values()
                    for dependency in issue.dependencies
                ),
                key=lambda edge: (edge.issue_id, edge.depends_on_id),
            )
        )

        adjacency_ids = sorted(
            set(ordered_issues)
            | {edge.issue_id for edge in edges}
            | {edge.depends_on_id for edge in edges}
        )
        forward_lists: dict[str, list[DepEdge]] = {
            issue_id: [] for issue_id in adjacency_ids
        }
        reverse_lists: dict[str, list[DepEdge]] = {
            issue_id: [] for issue_id in adjacency_ids
        }
        for edge in edges:
            forward_lists[edge.issue_id].append(edge)
            reverse_lists[edge.depends_on_id].append(edge)
        forward = {
            issue_id: tuple(forward_lists[issue_id]) for issue_id in adjacency_ids
        }
        reverse = {
            issue_id: tuple(reverse_lists[issue_id]) for issue_id in adjacency_ids
        }
        return cls(
            issues=MappingProxyType(ordered_issues),
            forward=MappingProxyType(forward),
            reverse=MappingProxyType(reverse),
            edges=edges,
        )

    def resolve(self, issue_id: str) -> Issue | None:
        """Resolve an ID, retaining ``None`` for dangling dependency targets."""
        return self.issues.get(issue_id)

    def outgoing(self, issue_id: str) -> tuple[DepEdge, ...]:
        """Return edges from *issue_id* to the beads it depends on."""
        return self.forward.get(issue_id, ())

    def incoming(self, issue_id: str) -> tuple[DepEdge, ...]:
        """Return edges from beads blocked by *issue_id*."""
        return self.reverse.get(issue_id, ())

    def walk(
        self,
        issue_id: str,
        *,
        direction: DepDirection,
        levels: int = 0,
    ) -> DepTraversalNode:
        """Walk from *issue_id*, marking cycles, repeats, and truncation.

        ``levels=0`` is unlimited.  Cycle detection is local to the current
        path, while repeat detection is shared across the whole walk.
        """
        if levels < 0:
            raise ValueError("levels must be non-negative")
        expanded: set[str] = set()
        return self._walk_node(
            issue_id,
            edge=None,
            direction=direction,
            depth=0,
            levels=levels,
            path=frozenset(),
            expanded=expanded,
        )

    def _walk_node(
        self,
        issue_id: str,
        *,
        edge: DepEdge | None,
        direction: DepDirection,
        depth: int,
        levels: int,
        path: frozenset[str],
        expanded: set[str],
    ) -> DepTraversalNode:
        if issue_id in path:
            return DepTraversalNode(
                issue_id=issue_id,
                edge=edge,
                repeat=False,
                cycle=True,
                truncated=False,
                children=(),
            )
        if issue_id in expanded:
            return DepTraversalNode(
                issue_id=issue_id,
                edge=edge,
                repeat=True,
                cycle=False,
                truncated=False,
                children=(),
            )

        adjacent = (
            self.outgoing(issue_id) if direction == "out" else self.incoming(issue_id)
        )
        unresolved = self.resolve(issue_id) is None
        truncated = bool(adjacent) and levels != 0 and depth >= levels
        if unresolved or truncated:
            return DepTraversalNode(
                issue_id=issue_id,
                edge=edge,
                repeat=False,
                cycle=False,
                truncated=truncated,
                children=(),
            )

        expanded.add(issue_id)
        child_path = path | {issue_id}
        children = tuple(
            self._walk_node(
                (
                    adjacent_edge.depends_on_id
                    if direction == "out"
                    else adjacent_edge.issue_id
                ),
                edge=adjacent_edge,
                direction=direction,
                depth=depth + 1,
                levels=levels,
                path=child_path,
                expanded=expanded,
            )
            for adjacent_edge in adjacent
        )
        return DepTraversalNode(
            issue_id=issue_id,
            edge=edge,
            repeat=False,
            cycle=False,
            truncated=False,
            children=children,
        )
