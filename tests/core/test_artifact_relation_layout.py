"""Tests for Textual-free Artifacts relation layout."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_model import PaneRelationDecl, RelationKind
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import (
    RelationEntryFact,
    RelationRole,
    assign_relation_roles,
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


def test_assign_relation_roles_uses_first_hierarchy_inverse_and_kind() -> None:
    relations = (
        _decl("parent", RelationKind.HIERARCHY, inverse="children"),
        _decl("children", RelationKind.HIERARCHY, inverse="parent"),
        _decl("versions", RelationKind.FAMILY),
        _decl("plans", RelationKind.LINK, target_pane="ref:plan"),
    )

    assert assign_relation_roles(relations) == {
        "parent": RelationRole.ANCESTOR,
        "children": RelationRole.DESCENDANT,
        "versions": RelationRole.FAMILY,
        "plans": RelationRole.LINK,
    }


def test_build_relation_view_keys_hidden_counts_and_flags() -> None:
    origin = _target("current")
    parent = _target("parent")
    grandparent = _target("grandparent")
    child = _target("child")
    hidden_child = _target("hidden-child")
    sibling = _target("current__1")
    missing = _target("missing")
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
            _edge("ancestors", parent, grandparent),
            _edge("children", origin, child),
            _edge("children", origin, hidden_child),
            _edge("siblings", origin, sibling, kind=RelationKind.FAMILY),
            _edge("ancestors", child, missing),
            _edge("plans", origin, plan, kind=RelationKind.LINK),
        ),
        known_targets={origin, parent, grandparent, child, hidden_child, sibling},
    )
    view = build_relation_view(
        index=index,
        origin=origin,
        relations=relations,
        facts={
            hidden_child: RelationEntryFact("hidden-child", hidden=True),
            child: RelationEntryFact("child", status="Ready"),
        },
    )

    assert view
    assert view.keymap.ancestors == (("<<", parent), ("<a", grandparent))
    assert view.keymap.children == ((">", child),)
    assert view.keymap.siblings == (("~", sibling),)
    assert view.keymap.first_link_target("plans") == plan

    children = next(
        section for section in view.sections if section.relation == "children"
    )
    assert children.hidden_count == 1
    assert children.rows[0].status == "Ready"

    links = next(section for section in view.sections if section.relation == "plans")
    assert links.rows[0].cross_pane is True

    child_view = build_relation_view(
        index=index,
        origin=child,
        relations=relations,
    )
    child_ancestors = next(
        section for section in child_view.sections if section.relation == "ancestors"
    )
    assert child_ancestors.rows[0].target == missing
    assert child_ancestors.rows[0].dangling is True
