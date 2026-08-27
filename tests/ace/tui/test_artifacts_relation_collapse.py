"""Artifacts relation collapse rail rendering and configuration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sase.ace.testing.fixtures import make_patch
from sase.ace.tui._artifact_tab_model import PaneRelationDecl, RelationKind
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from sase.ace.tui.widgets.artifacts.relation_panel import _build_collapsed_rail
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter
from sase.core.artifact_relation_layout import (
    RelationEntryFact,
    RelationKeymap,
    RelationRole,
    build_relation_view,
)
from sase.core.artifact_relations import RelationEdge, build_relation_index


def _decl(
    name: str,
    kind: RelationKind,
    *,
    inverse: str | None = None,
    label: str | None = None,
) -> PaneRelationDecl:
    return PaneRelationDecl(
        name=name,
        kind=kind,
        label=label or name.title(),
        source="test",
        target_pane=None,
        inverse=inverse,
        directed=kind is not RelationKind.FAMILY,
        transitive=kind is RelationKind.HIERARCHY,
    )


def _target(name: str) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id="patches", parts=("demo", name))


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


def _relation_index() -> tuple[Any, ArtifactEntryTarget, tuple[PaneRelationDecl, ...]]:
    origin = _target("current")
    parent = _target("parent")
    child = _target("child")
    grandchild = _target("grandchild")
    sibling = _target("current__1")
    relations = (
        _decl(
            "ancestors", RelationKind.HIERARCHY, inverse="children", label="Ancestors"
        ),
        _decl(
            "children", RelationKind.HIERARCHY, inverse="ancestors", label="Children"
        ),
        _decl("siblings", RelationKind.FAMILY, label="Siblings"),
    )
    index = build_relation_index(
        pane_id="patches",
        relations=relations,
        edges=(
            _edge("ancestors", origin, parent),
            _edge("children", origin, child),
            _edge("children", child, grandchild),
            _edge("siblings", origin, sibling, kind=RelationKind.FAMILY),
        ),
        known_targets={origin, parent, child, grandchild, sibling},
    )
    return index, origin, relations


def test_collapsed_rail_is_one_line_with_declared_labels() -> None:
    index, origin, relations = _relation_index()
    view = build_relation_view(index=index, origin=origin, relations=relations)
    text = _build_collapsed_rail(
        view,
        accent="#87D7FF",
        mode_keys={
            RelationRole.ANCESTOR: "<",
            RelationRole.DESCENDANT: ">",
            RelationRole.FAMILY: "~",
        },
    )

    assert text is not None
    assert view.keymap.ancestors
    assert view.keymap.children
    assert "\n" not in text.plain
    assert "▸" in text.plain
    assert "< 1 ancestors" in text.plain
    assert "> 2 children" in text.plain
    assert "~ 1 siblings" in text.plain


def test_collapsed_rail_leads_with_expand_chip_and_verb() -> None:
    index, origin, relations = _relation_index()
    view = build_relation_view(index=index, origin=origin, relations=relations)
    text = _build_collapsed_rail(
        view,
        accent="#87D7FF",
        mode_keys={
            RelationRole.ANCESTOR: "<",
            RelationRole.DESCENDANT: ">",
            RelationRole.FAMILY: "~",
        },
        toggle_key=".",
    )

    assert text is not None
    plain = text.plain
    assert "\n" not in plain
    chip_at = plain.index("▸")
    verb_at = plain.index("expand")
    first_segment_at = plain.index("< 1 ancestors")
    assert chip_at < verb_at < first_segment_at


def test_collapsed_rail_uses_the_passed_toggle_key() -> None:
    index, origin, relations = _relation_index()
    view = build_relation_view(index=index, origin=origin, relations=relations)
    text = _build_collapsed_rail(view, accent="#87D7FF", toggle_key="^r")

    assert text is not None
    assert "▸ ^r " in text.plain
    assert "▸ . " not in text.plain


def test_collapsed_empty_view_stays_hidden() -> None:
    origin = _target("current")
    relations = (
        _decl("ancestors", RelationKind.HIERARCHY, inverse="children"),
        _decl("children", RelationKind.HIERARCHY, inverse="ancestors"),
    )
    index = build_relation_index(
        pane_id="patches",
        relations=relations,
        edges=(),
        known_targets={origin},
    )
    view = build_relation_view(index=index, origin=origin, relations=relations)

    assert not view.keymap
    assert _build_collapsed_rail(view, accent="#87D7FF") is None


def test_link_only_relation_view_leaves_the_panel_empty() -> None:
    origin = _target("current")
    linked = _target("linked")
    relations = (_decl("implements", RelationKind.LINK, label="implements"),)
    edge = RelationEdge(
        kind=RelationKind.LINK,
        relation="implements",
        label="implements",
        source=origin,
        target=linked,
        description="extends requirement",
        origin="derived",
        uses=2,
    )
    index = build_relation_index(
        pane_id="patches",
        relations=relations,
        edges=(edge,),
        known_targets={origin, linked},
    )
    view = build_relation_view(
        index=index,
        origin=origin,
        relations=relations,
        facts={linked: RelationEntryFact("linked.md")},
    )

    assert index.edges_for_relation(origin, "implements") == (edge,)
    assert view.sections == ()
    assert view.roles == {"implements": RelationRole.LINK}
    assert not view.keymap


def test_patches_footer_appends_toggle_when_keymap_is_live() -> None:
    footer = KeybindingFooter()
    footer._app = SimpleNamespace(  # noqa: SLF001
        _relation_keymap=RelationKeymap(ancestors=(("<", _target("parent")),)),
        artifacts_relations_collapsed=False,
    )
    patch = make_patch(name="feature_a", status="Ready")

    labels = dict(footer._compute_available_bindings(patch))
    assert labels[footer._kd("toggle_relation_panel")] == "collapse relations"

    footer._app.artifacts_relations_collapsed = True  # noqa: SLF001
    labels = dict(footer._compute_available_bindings(patch))
    assert labels[footer._kd("toggle_relation_panel")] == "expand relations"


def test_relations_expanded_config_true_starts_expanded() -> None:
    from sase.ace.tui.app import AceApp

    with patch(
        "sase.config.load_merged_config",
        return_value={"ace": {"artifacts": {"relations_expanded": True}}},
    ):
        app = AceApp(auto_start_axe=False)

    assert app.artifacts_relations_collapsed is False


def test_relations_expanded_config_absent_starts_collapsed() -> None:
    from sase.ace.tui.app import AceApp

    with patch(
        "sase.config.load_merged_config",
        return_value={"ace": {}},
    ):
        app = AceApp(auto_start_axe=False)

    assert app.artifacts_relations_collapsed is True
