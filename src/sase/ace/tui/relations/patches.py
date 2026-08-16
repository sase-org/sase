"""Patch relation source: ancestors, children, and revert-family siblings."""

from __future__ import annotations

from collections.abc import Sequence

from sase.ace.patch import Patch
from sase.ace.tui._artifact_tab_model import ArtifactsPaneContract
from sase.ace.tui.models.patch_graph_index import PatchGraphIndex
from sase.ace.tui.relations._support import decls_by_name, emit_edge
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import (
    RelationEdge,
    RelationIndex,
    RelationSource,
    build_relation_index,
)


def build_patches_relation_index(
    patches: Sequence[Patch],
    graph_index: PatchGraphIndex,
    *,
    contract: ArtifactsPaneContract,
) -> RelationIndex:
    """Build the host-owned Patch relation index for *patches*."""
    source = _PatchesRelationSource(patches, graph_index, contract)
    return build_relation_index(
        pane_id=source.pane_id,
        relations=source.relations(),
        edges=source.raw_edges(),
        known_targets=source.known_targets(),
    )


def _patch_target(patch: Patch) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(
        pane_id="patches",
        parts=(patch.project_name, patch.name),
    )


class _PatchesRelationSource(RelationSource):
    def __init__(
        self,
        patches: Sequence[Patch],
        graph_index: PatchGraphIndex,
        contract: ArtifactsPaneContract,
    ) -> None:
        self._patches = tuple(patches)
        self._graph = graph_index
        self._contract = contract
        self._decls = decls_by_name(contract)

    @property
    def pane_id(self) -> str:
        return self._contract.id

    def relations(self) -> tuple:
        return self._contract.relations

    def known_targets(self) -> frozenset[ArtifactEntryTarget]:
        return frozenset(_patch_target(patch) for patch in self._patches)

    def raw_edges(self) -> tuple[RelationEdge, ...]:
        edges: list[RelationEdge] = []
        ancestors = self._decls.get("ancestors")
        children = self._decls.get("children")
        siblings = self._decls.get("siblings")
        for patch in self._patches:
            source = _patch_target(patch)
            if ancestors is not None and patch.parent:
                parent_cs = self._graph.name_map.get(patch.parent.lower())
                if parent_cs is not None:
                    target = _patch_target(parent_cs)
                else:
                    target = ArtifactEntryTarget(
                        pane_id="patches",
                        parts=(patch.project_name, patch.parent),
                    )
                edges.append(emit_edge(ancestors, source, target))
            if children is not None:
                for child in self._graph.get_children(patch.name):
                    edges.append(emit_edge(children, source, _patch_target(child)))
            if siblings is not None:
                for sibling in self._graph.get_siblings_of(patch):
                    edges.append(emit_edge(siblings, source, _patch_target(sibling)))
        return tuple(edges)
