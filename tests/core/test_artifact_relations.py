"""Unit coverage for host-owned relation-index construction."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_model import PaneRelationDecl, RelationKind
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import (
    RelationEdge,
    RelationIndex,
    build_relation_index,
)


def _target(pane: str, *parts: str) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id=pane, parts=parts)


def _decl(
    name: str,
    *,
    kind: RelationKind = RelationKind.HIERARCHY,
    inverse: str | None = None,
    directed: bool = True,
    transitive: bool = True,
    target_pane: str | None = None,
    label: str | None = None,
) -> PaneRelationDecl:
    return PaneRelationDecl(
        name=name,
        kind=kind,
        label=label or name.title(),
        source="test",
        target_pane=target_pane,
        inverse=inverse,
        directed=directed,
        transitive=transitive,
    )


def _edge(
    decl: PaneRelationDecl,
    source: ArtifactEntryTarget,
    target: ArtifactEntryTarget,
) -> RelationEdge:
    return RelationEdge(
        kind=decl.kind,
        relation=decl.name,
        label=decl.label,
        source=source,
        target=target,
    )


def test_inverse_derivation_uses_inverse_declaration() -> None:
    parent = _decl("parent", inverse="children")
    children = _decl("children", inverse="parent")
    a = _target("beads", "p", "task", "a")
    b = _target("beads", "p", "epic", "b")
    index = build_relation_index(
        pane_id="beads",
        relations=(parent, children),
        edges=(_edge(parent, a, b),),
        known_targets=(a, b),
    )
    derived = index.edges_for_relation(b, "children")
    assert len(derived) == 1
    assert derived[0].derived is True
    assert derived[0].source == b
    assert derived[0].target == a
    assert derived[0].label == "Children"


def test_symmetric_undirected_materializes_reverse_under_same_name() -> None:
    versions = _decl(
        "versions",
        kind=RelationKind.FAMILY,
        directed=False,
        transitive=False,
    )
    row = _target("files", "doc")
    version = _target("files", "doc", "v1")
    index = build_relation_index(
        pane_id="files",
        relations=(versions,),
        edges=(_edge(versions, row, version),),
        known_targets=(row, version),
    )
    reverse = index.edges_for_relation(version, "versions")
    assert len(reverse) == 1
    assert reverse[0].derived is True
    assert reverse[0].target == row
    assert reverse[0].relation == "versions"


def test_undeclared_relation_is_dropped_with_diagnostic() -> None:
    parent = _decl("parent", inverse="children")
    a = _target("beads", "p", "task", "a")
    b = _target("beads", "p", "epic", "b")
    ghost = RelationEdge(
        kind=RelationKind.LINK,
        relation="mystery",
        label="Mystery",
        source=a,
        target=b,
    )
    index = build_relation_index(
        pane_id="beads",
        relations=(parent,),
        edges=(ghost, _edge(parent, a, b)),
        known_targets=(a, b),
    )
    assert all(edge.relation != "mystery" for edge in index.edges)
    assert any(item.code == "undeclared_relation" for item in index.diagnostics)
    assert index.edges_for_relation(a, "parent")


def test_same_pane_unknown_target_is_dangling_with_diagnostic() -> None:
    parent = _decl("parent", inverse="children", transitive=False)
    a = _target("beads", "p", "task", "a")
    missing = _target("beads", "p", "epic", "ghost")
    index = build_relation_index(
        pane_id="beads",
        relations=(parent,),
        edges=(_edge(parent, a, missing),),
        known_targets=(a,),
    )
    hop = index.edges_for_relation(a, "parent")[0]
    assert hop.dangling is True
    assert any(item.code == "dangling_target" for item in index.diagnostics)
    assert any(item.target == missing for item in index.diagnostics)


def test_cross_pane_target_is_never_dangling() -> None:
    plans = _decl(
        "plans",
        kind=RelationKind.LINK,
        inverse="beads",
        directed=True,
        transitive=False,
        target_pane="ref:plan",
    )
    a = _target("beads", "p", "epic", "e1")
    plan = _target("ref:plan", "p", "active", "/plan.md")
    index = build_relation_index(
        pane_id="beads",
        relations=(plans,),
        edges=(_edge(plans, a, plan),),
        known_targets=(a,),
    )
    hop = index.edges_for_relation(a, "plans")[0]
    assert hop.dangling is False
    assert not any(item.code == "dangling_target" for item in index.diagnostics)


def test_cycle_diagnostic_keeps_edges() -> None:
    ancestors = _decl("ancestors", inverse="children")
    a = _target("patches", "p", "a")
    b = _target("patches", "p", "b")
    index = build_relation_index(
        pane_id="patches",
        relations=(ancestors,),
        edges=(_edge(ancestors, a, b), _edge(ancestors, b, a)),
        known_targets=(a, b),
    )
    assert len(index.edges_for_relation(a, "ancestors")) == 1
    assert len(index.edges_for_relation(b, "ancestors")) == 1
    cycles = [item for item in index.diagnostics if item.code == "relation_cycle"]
    assert len(cycles) == 1
    assert cycles[0].relation == "ancestors"


def test_chain_includes_cycle_close_then_stops() -> None:
    ancestors = _decl("ancestors", inverse="children")
    a = _target("patches", "p", "a")
    b = _target("patches", "p", "b")
    index = build_relation_index(
        pane_id="patches",
        relations=(ancestors,),
        edges=(_edge(ancestors, a, b), _edge(ancestors, b, a)),
        known_targets=(a, b),
    )
    names = [edge.target.parts[-1] for edge in index.chain(a, "ancestors")]
    assert names == ["b", "a"]


def test_chain_stops_after_dangling_hop() -> None:
    ancestors = _decl("ancestors", inverse="children")
    orphan = _target("patches", "p", "orphan")
    ghost = _target("patches", "p", "ghost")
    index = build_relation_index(
        pane_id="patches",
        relations=(ancestors,),
        edges=(_edge(ancestors, orphan, ghost),),
        known_targets=(orphan,),
    )
    hops = index.chain(orphan, "ancestors")
    assert len(hops) == 1
    assert hops[0].target == ghost
    assert hops[0].dangling is True


def test_built_index_is_not_mutated_by_later_calls() -> None:
    parent = _decl("parent", inverse="children", transitive=False)
    a = _target("beads", "p", "task", "a")
    b = _target("beads", "p", "epic", "b")
    index = build_relation_index(
        pane_id="beads",
        relations=(parent,),
        edges=(_edge(parent, a, b),),
        known_targets=(a, b),
    )
    first = index.edges_for(a)
    second = index.edges_for(a)
    assert first is second or first == second
    assert isinstance(index, RelationIndex)
    chain = index.chain(a, "parent")
    assert index.chain(a, "parent") == chain
    assert index.edges_for_relation(a, "parent") == index.edges_for_relation(
        a, "parent"
    )
