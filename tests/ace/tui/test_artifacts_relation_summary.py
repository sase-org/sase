"""Unit tests for collapsed-rail relation summaries."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_model import PaneRelationDecl, RelationKind
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import (
    RelationEntryFact,
    RelationKeymap,
    RelationRole,
    RelationRow,
    RelationSection,
    RelationView,
    build_relation_summary,
    build_relation_view,
)
from sase.core.artifact_relations import RelationEdge, build_relation_index


def _decl(
    name: str,
    kind: RelationKind,
    *,
    inverse: str | None = None,
    target_pane: str | None = None,
) -> PaneRelationDecl:
    return PaneRelationDecl(
        name=name,
        kind=kind,
        label=name.title(),
        source="test",
        target_pane=target_pane,
        inverse=inverse,
        directed=kind is not RelationKind.FAMILY,
        transitive=kind is RelationKind.HIERARCHY,
    )


def _target(name: str, pane_id: str = "patches") -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id=pane_id, parts=("demo", name))


def _edge(
    relation: str,
    source: ArtifactEntryTarget,
    target: ArtifactEntryTarget,
    *,
    kind: RelationKind = RelationKind.HIERARCHY,
) -> RelationEdge:
    return RelationEdge(
        kind=kind,
        relation=relation,
        label=relation.title(),
        source=source,
        target=target,
    )


def _row(name: str, *children: RelationRow) -> RelationRow:
    return RelationRow(
        key="",
        target=_target(name),
        label=name,
        status="",
        description="",
        origin="",
        uses=0,
        depth=0,
        dangling=False,
        cross_pane=False,
        children=children,
    )


def test_summary_preserves_section_order_and_counts() -> None:
    origin = _target("current")
    parent = _target("parent")
    child = _target("child")
    sibling = _target("current__1")
    plan = _target("plan.md", "ref:plan")
    relations = (
        _decl("ancestors", RelationKind.HIERARCHY, inverse="children"),
        _decl("children", RelationKind.HIERARCHY, inverse="ancestors"),
        _decl("siblings", RelationKind.FAMILY),
        _decl("plans", RelationKind.LINK, target_pane="ref:plan"),
    )
    index = build_relation_index(
        pane_id="patches",
        relations=relations,
        edges=(
            _edge("ancestors", origin, parent),
            _edge("children", origin, child),
            _edge("siblings", origin, sibling, kind=RelationKind.FAMILY),
            _edge("plans", origin, plan, kind=RelationKind.LINK),
        ),
        known_targets={origin, parent, child, sibling, plan},
    )
    view = build_relation_view(index=index, origin=origin, relations=relations)
    summary = build_relation_summary(view)

    assert summary
    assert [entry.relation for entry in summary.entries] == [
        "ancestors",
        "children",
        "siblings",
        "plans",
    ]
    by_relation = {entry.relation: entry for entry in summary.entries}
    assert by_relation["ancestors"].role is RelationRole.ANCESTOR
    assert by_relation["ancestors"].count == 1
    assert by_relation["children"].role is RelationRole.DESCENDANT
    assert by_relation["children"].count == 1
    assert by_relation["siblings"].role is RelationRole.FAMILY
    assert by_relation["siblings"].count == 1
    assert by_relation["plans"].role is RelationRole.LINK
    assert by_relation["plans"].count == 1
    assert summary.hidden_total == 0


def test_summary_counts_nested_descendant_subtree() -> None:
    leaf_a = _row("leaf-a")
    leaf_b = _row("leaf-b")
    mid = _row("mid", leaf_a, leaf_b)
    root = _row("root", mid)
    view = RelationView(
        sections=(
            RelationSection(
                relation="children",
                label="Children",
                kind=RelationKind.HIERARCHY,
                role=RelationRole.DESCENDANT,
                rows=(root,),
                hidden_count=0,
            ),
        ),
        keymap=RelationKeymap(),
        roles={"children": RelationRole.DESCENDANT},
    )

    summary = build_relation_summary(view)

    assert len(summary.entries) == 1
    assert summary.entries[0].count == 4


def test_summary_carries_hidden_per_section_and_total() -> None:
    origin = _target("current")
    child = _target("child")
    hidden_child = _target("hidden-child")
    hidden_sibling = _target("hidden-sib")
    relations = (
        _decl("ancestors", RelationKind.HIERARCHY, inverse="children"),
        _decl("children", RelationKind.HIERARCHY, inverse="ancestors"),
        _decl("siblings", RelationKind.FAMILY),
    )
    index = build_relation_index(
        pane_id="patches",
        relations=relations,
        edges=(
            _edge("children", origin, child),
            _edge("children", origin, hidden_child),
            _edge("siblings", origin, hidden_sibling, kind=RelationKind.FAMILY),
        ),
        known_targets={origin, child, hidden_child, hidden_sibling},
    )
    view = build_relation_view(
        index=index,
        origin=origin,
        relations=relations,
        facts={
            hidden_child: RelationEntryFact("hidden-child", hidden=True),
            hidden_sibling: RelationEntryFact("hidden-sib", hidden=True),
        },
    )
    summary = build_relation_summary(view)

    by_relation = {entry.relation: entry for entry in summary.entries}
    assert "ancestors" not in by_relation
    assert by_relation["children"].count == 1
    assert by_relation["children"].hidden == 1
    assert by_relation["siblings"].count == 0
    assert by_relation["siblings"].hidden == 1
    assert summary.hidden_total == 2


def test_empty_view_summary_is_falsy() -> None:
    view = RelationView(sections=(), keymap=RelationKeymap(), roles={})
    summary = build_relation_summary(view)

    assert not summary
    assert summary.entries == ()
    assert summary.hidden_total == 0
