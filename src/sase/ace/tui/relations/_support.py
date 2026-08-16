"""Shared helpers for built-in Artifacts relation sources."""

from __future__ import annotations

from collections.abc import Callable

from sase.ace.tui._artifact_tab_model import (
    ArtifactsPaneContract,
    PaneCapability,
    PaneRelationDecl,
)
from sase.ace.tui.util.trace import tui_trace
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import RelationEdge, RelationIndex


def decls_by_name(
    contract: ArtifactsPaneContract,
) -> dict[str, PaneRelationDecl]:
    """Return declared relations keyed by name."""
    return {item.name: item for item in contract.relations}


def emit_edge(
    decl: PaneRelationDecl,
    source: ArtifactEntryTarget,
    target: ArtifactEntryTarget,
) -> RelationEdge:
    """Build one undeclared-flag raw edge for *decl*."""
    return RelationEdge(
        kind=decl.kind,
        relation=decl.name,
        label=decl.label,
        source=source,
        target=target,
    )


def relation_index_if_enabled(
    contract: ArtifactsPaneContract | None,
    factory: Callable[[ArtifactsPaneContract], RelationIndex],
) -> RelationIndex | None:
    """Build an index only when the pane contract enables RELATIONS."""
    if contract is None or not contract.has(PaneCapability.RELATIONS):
        return None
    with tui_trace(f"relations.index.{contract.id}") as extra:
        index = factory(contract)
        extra["count"] = len(index.edges)
        return index
