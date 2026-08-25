"""Derivation and diagnostics for :func:`build_relation_index`.

Split out of :mod:`sase.core.artifact_relations` so that module stays a
record/API surface.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sase.ace.tui._artifact_tab_model import PaneRelationDecl
from sase.core.artifact_entry_target import ArtifactEntryTarget

if TYPE_CHECKING:
    from sase.core.artifact_relations import RelationDiagnostic, RelationEdge


def assemble_relation_graph(
    *,
    pane_id: str,
    relations: tuple[PaneRelationDecl, ...],
    edges: tuple[RelationEdge, ...],
    known_targets: frozenset[ArtifactEntryTarget],
) -> tuple[tuple[RelationEdge, ...], tuple[RelationDiagnostic, ...]]:
    """Drop undeclared edges, mark dangling, derive inverses, detect cycles."""
    from sase.core.artifact_relations import RelationDiagnostic, RelationEdge

    declared = {item.name: item for item in relations}
    kept: list[RelationEdge] = []
    diagnostics: list[RelationDiagnostic] = []
    for edge in edges:
        if edge.relation not in declared:
            diagnostics.append(
                RelationDiagnostic(
                    code="undeclared_relation",
                    relation=edge.relation,
                    message=f"dropped undeclared relation {edge.relation!r}",
                    target=edge.source,
                )
            )
            continue
        kept.append(edge)

    marked = _mark_dangling(
        pane_id=pane_id,
        edges=kept,
        known_targets=known_targets,
        diagnostics=diagnostics,
        emit_diagnostics=True,
    )
    derived = _derive_edges(
        relations=relations,
        declared=declared,
        edges=marked,
    )
    if derived:
        derived = _mark_dangling(
            pane_id=pane_id,
            edges=derived,
            known_targets=known_targets,
            diagnostics=diagnostics,
            emit_diagnostics=True,
        )
    assembled = (*marked, *derived)
    diagnostics.extend(_cycle_diagnostics(relations=relations, edges=assembled))
    return assembled, tuple(diagnostics)


def _mark_dangling(
    *,
    pane_id: str,
    edges: Iterable[RelationEdge],
    known_targets: frozenset[ArtifactEntryTarget],
    diagnostics: list[RelationDiagnostic],
    emit_diagnostics: bool,
) -> list[RelationEdge]:
    from sase.core.artifact_relations import RelationDiagnostic, RelationEdge

    marked: list[RelationEdge] = []
    seen: set[tuple[str, ArtifactEntryTarget]] = set()
    for edge in edges:
        same_pane = edge.target.pane_id == pane_id
        dangling = same_pane and edge.target not in known_targets
        if dangling != edge.dangling:
            edge = RelationEdge(
                kind=edge.kind,
                relation=edge.relation,
                label=edge.label,
                source=edge.source,
                target=edge.target,
                description=edge.description,
                origin=edge.origin,
                uses=edge.uses,
                dangling=dangling,
                derived=edge.derived,
            )
        marked.append(edge)
        key = (edge.relation, edge.target)
        if dangling and emit_diagnostics and key not in seen:
            seen.add(key)
            diagnostics.append(
                RelationDiagnostic(
                    code="dangling_target",
                    relation=edge.relation,
                    message=f"dangling target for relation {edge.relation!r}",
                    target=edge.target,
                )
            )
    return marked


def _derive_edges(
    *,
    relations: tuple[PaneRelationDecl, ...],
    declared: dict[str, PaneRelationDecl],
    edges: list[RelationEdge],
) -> list[RelationEdge]:
    from sase.core.artifact_relations import RelationEdge

    emitted = {edge.relation for edge in edges}
    derived: list[RelationEdge] = []
    for decl in relations:
        if decl.inverse and decl.inverse not in emitted:
            inverse = declared.get(decl.inverse)
            kind = inverse.kind if inverse is not None else decl.kind
            label = inverse.label if inverse is not None else decl.label
            for edge in edges:
                if edge.relation != decl.name:
                    continue
                derived.append(
                    RelationEdge(
                        kind=kind,
                        relation=decl.inverse,
                        label=label,
                        source=edge.target,
                        target=edge.source,
                        description=edge.description,
                        origin=edge.origin,
                        uses=edge.uses,
                        dangling=False,
                        derived=True,
                    )
                )
            emitted.add(decl.inverse)
        if decl.directed:
            continue
        existing = {
            (edge.source, edge.target) for edge in edges if edge.relation == decl.name
        }
        for extra in derived:
            if extra.relation == decl.name:
                existing.add((extra.source, extra.target))
        for edge in edges:
            if edge.relation != decl.name:
                continue
            key = (edge.target, edge.source)
            if key in existing:
                continue
            derived.append(
                RelationEdge(
                    kind=decl.kind,
                    relation=decl.name,
                    label=decl.label,
                    source=edge.target,
                    target=edge.source,
                    description=edge.description,
                    origin=edge.origin,
                    uses=edge.uses,
                    dangling=False,
                    derived=True,
                )
            )
            existing.add(key)
    return derived


def _cycle_diagnostics(
    *,
    relations: tuple[PaneRelationDecl, ...],
    edges: tuple[RelationEdge, ...],
) -> list[RelationDiagnostic]:
    from sase.core.artifact_relations import RelationDiagnostic

    adjacency: dict[str, dict[ArtifactEntryTarget, list[ArtifactEntryTarget]]] = {}
    for edge in edges:
        adjacency.setdefault(edge.relation, {}).setdefault(edge.source, []).append(
            edge.target
        )
    found: list[RelationDiagnostic] = []
    seen_cycles: set[tuple[str, tuple[str, ...]]] = set()
    for decl in relations:
        if not (decl.directed and decl.transitive):
            continue
        graph = adjacency.get(decl.name, {})
        for cycle in _distinct_cycles(graph):
            named = cycle[0]
            key = (decl.name, tuple(item.to_token() for item in cycle))
            if key in seen_cycles:
                continue
            seen_cycles.add(key)
            label = named.parts[-1] if named.parts else named.pane_id
            found.append(
                RelationDiagnostic(
                    code="relation_cycle",
                    relation=decl.name,
                    message=f"cycle in relation {decl.name!r} involving {label!r}",
                    target=named,
                )
            )
    return found


def _distinct_cycles(
    graph: dict[ArtifactEntryTarget, list[ArtifactEntryTarget]],
) -> list[tuple[ArtifactEntryTarget, ...]]:
    cycles: list[tuple[ArtifactEntryTarget, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for start in sorted(graph, key=lambda item: item.to_token()):
        for cycle in _cycles_from(start, graph):
            token_key = tuple(item.to_token() for item in cycle)
            if token_key in seen:
                continue
            seen.add(token_key)
            cycles.append(cycle)
    return cycles


def _cycles_from(
    start: ArtifactEntryTarget,
    graph: dict[ArtifactEntryTarget, list[ArtifactEntryTarget]],
) -> list[tuple[ArtifactEntryTarget, ...]]:
    cycles: list[tuple[ArtifactEntryTarget, ...]] = []
    stack: list[ArtifactEntryTarget] = []
    on_stack: set[ArtifactEntryTarget] = set()

    def visit(node: ArtifactEntryTarget) -> None:
        stack.append(node)
        on_stack.add(node)
        for nxt in graph.get(node, ()):
            if nxt in on_stack:
                idx = stack.index(nxt)
                cycles.append(_normalize_cycle(tuple(stack[idx:])))
                continue
            if nxt in stack:
                continue
            visit(nxt)
        stack.pop()
        on_stack.remove(node)

    visit(start)
    return cycles


def _normalize_cycle(
    nodes: tuple[ArtifactEntryTarget, ...],
) -> tuple[ArtifactEntryTarget, ...]:
    if not nodes:
        return nodes
    tokens = [item.to_token() for item in nodes]
    min_index = min(range(len(nodes)), key=tokens.__getitem__)
    return (*nodes[min_index:], *nodes[:min_index])


__all__ = ["assemble_relation_graph"]
