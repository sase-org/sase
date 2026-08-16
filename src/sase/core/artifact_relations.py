"""Host-owned relation index for one Artifacts pane snapshot.

Textual-free. A :class:`RelationIndex` is built once per snapshot from the
pane's declared relations plus raw source edges. Inverse and symmetric
edges are derived here. Nothing in this module performs I/O.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from sase.ace.tui._artifact_tab_model import PaneRelationDecl, RelationKind
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations_build import assemble_relation_graph

_EMPTY_EDGES: RelationEdges


@dataclass(frozen=True, slots=True)
class RelationEdge:
    """One directed hop in a pane relation graph."""

    kind: RelationKind
    relation: str
    label: str
    source: ArtifactEntryTarget
    target: ArtifactEntryTarget
    dangling: bool = False
    derived: bool = False


@dataclass(frozen=True, slots=True)
class RelationDiagnostic:
    """One construction-time relation-graph finding."""

    code: str
    relation: str
    message: str
    target: ArtifactEntryTarget | None = None


@dataclass(frozen=True, slots=True)
class RelationEdges:
    """The three host primitives grouped for one source row."""

    hierarchy: tuple[RelationEdge, ...] = ()
    family: tuple[RelationEdge, ...] = ()
    link: tuple[RelationEdge, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.hierarchy or self.family or self.link)


_EMPTY_EDGES = RelationEdges()


@dataclass(frozen=True, slots=True)
class RelationIndex:
    """Immutable per-snapshot relation graph for one pane."""

    pane_id: str
    relations: tuple[PaneRelationDecl, ...]
    known_targets: frozenset[ArtifactEntryTarget]
    edges: tuple[RelationEdge, ...]
    diagnostics: tuple[RelationDiagnostic, ...]
    _by_source: Mapping[ArtifactEntryTarget, RelationEdges] = field(
        init=False, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_source", _index_edges(self.edges))

    def edges_for(self, target: ArtifactEntryTarget) -> RelationEdges:
        """Return edges leaving *target*, or an empty triple if unknown."""
        return self._by_source.get(target, _EMPTY_EDGES)

    def edges_for_relation(
        self, target: ArtifactEntryTarget, name: str
    ) -> tuple[RelationEdge, ...]:
        """Return edges of *name* leaving *target*, in index order."""
        grouped = self.edges_for(target)
        return tuple(
            edge
            for edge in (*grouped.hierarchy, *grouped.family, *grouped.link)
            if edge.relation == name
        )

    def chain(self, target: ArtifactEntryTarget, name: str) -> tuple[RelationEdge, ...]:
        """Walk the first edge of *name* until a repeat hop or a dangling hop.

        The start node is not marked visited. A hop whose target was already
        seen ends the walk without appending that hop. A dangling hop is
        appended and then terminates the walk. This matches the Patch
        ancestor walk: include the missing parent, and include the node that
        closes a cycle.
        """
        walked: list[RelationEdge] = []
        visited: set[ArtifactEntryTarget] = set()
        current = target
        while True:
            hops = self.edges_for_relation(current, name)
            if not hops:
                break
            nxt = hops[0]
            if nxt.target in visited:
                break
            walked.append(nxt)
            visited.add(nxt.target)
            if nxt.dangling:
                break
            current = nxt.target
        return tuple(walked)


class RelationSource(ABC):
    """Pure snapshot-to-edge projection.

    Implementations perform no I/O, no globbing, no provider code, and no
    Git. They read an already-loaded snapshot and emit declared edges.
    """

    @property
    @abstractmethod
    def pane_id(self) -> str:
        """Owning Artifacts pane id."""

    @abstractmethod
    def relations(self) -> tuple[PaneRelationDecl, ...]:
        """Declared relations for this pane."""

    @abstractmethod
    def known_targets(self) -> frozenset[ArtifactEntryTarget]:
        """Identities this snapshot actually contains."""

    @abstractmethod
    def raw_edges(self) -> tuple[RelationEdge, ...]:
        """Forward edges this source owns, before inverse derivation."""

    def build_index(self) -> RelationIndex:
        """Assemble the immutable index for this snapshot."""
        return build_relation_index(
            pane_id=self.pane_id,
            relations=self.relations(),
            edges=self.raw_edges(),
            known_targets=self.known_targets(),
        )


def build_relation_index(
    *,
    pane_id: str,
    relations: tuple[PaneRelationDecl, ...],
    edges: Iterable[RelationEdge],
    known_targets: Iterable[ArtifactEntryTarget],
) -> RelationIndex:
    """Build one pane index. Never raises on bad source edges."""
    known = frozenset(known_targets)
    assembled_edges, diagnostics = assemble_relation_graph(
        pane_id=pane_id,
        relations=relations,
        edges=tuple(edges),
        known_targets=known,
    )
    return RelationIndex(
        pane_id=pane_id,
        relations=relations,
        known_targets=known,
        edges=assembled_edges,
        diagnostics=diagnostics,
    )


def _index_edges(
    edges: tuple[RelationEdge, ...],
) -> dict[ArtifactEntryTarget, RelationEdges]:
    grouped: dict[ArtifactEntryTarget, list[RelationEdge]] = {}
    for edge in edges:
        grouped.setdefault(edge.source, []).append(edge)
    return {
        source: RelationEdges(
            hierarchy=tuple(
                edge for edge in items if edge.kind is RelationKind.HIERARCHY
            ),
            family=tuple(edge for edge in items if edge.kind is RelationKind.FAMILY),
            link=tuple(edge for edge in items if edge.kind is RelationKind.LINK),
        )
        for source, items in grouped.items()
    }


__all__ = [
    "RelationDiagnostic",
    "RelationEdge",
    "RelationEdges",
    "RelationIndex",
    "RelationSource",
    "build_relation_index",
]
