"""Row model and row rendering tests for the artifact panel modal."""

from __future__ import annotations

from sase.ace.tui.modals.artifact_panel_modal import _row_label
from sase.ace.tui.modals.artifact_panel_state import (
    build_artifact_panel_rows,
    paged_model_from_paged_detail,
)
from sase.core.artifact_wire import ArtifactLinkWire
from tests.ace.tui.modals._artifact_panel_modal_helpers import (
    _detail,
    _node,
    _paged_detail,
)


def test_rich_row_model_includes_semantic_fields_and_group_counts() -> None:
    child = _node(
        "file:/tmp/plan.md",
        "file",
        "plan.md",
        {"artifact_type": "plan", "status": "fresh"},
        subtitle="Epic plan",
        updated_at="2026-05-06T02:45:00Z",
    )
    paged = _paged_detail(
        "changespec:alpha",
        kind="changespec",
        children=[child],
        child_total=12,
    )

    model = paged_model_from_paged_detail(paged)
    rows = build_artifact_panel_rows(model.detail, paged_model=model).rows

    assert rows[0].label == "Children (1/12)"
    assert rows[0].selectable is False
    assert rows[1].artifact_id == "file:/tmp/plan.md"
    assert rows[1].artifact_kind == "file"
    assert rows[1].file_type == "plan"
    assert rows[1].edge_direction == "children"
    assert rows[1].title == "plan.md"
    assert rows[1].subtitle == "Epic plan · fresh"
    assert rows[1].updated_label == "2026-05-06"
    assert rows[1].group_key == "children"

    rendered = str(_row_label(rows[1]))
    assert "[PLAN]" in rendered
    assert "plan.md" in rendered
    assert "file:/tmp/plan.md" in rendered


def test_row_label_uses_stable_type_and_edge_colors() -> None:
    child = _node(
        "file:/tmp/plan.md",
        "file",
        "plan.md",
        {"artifact_type": "plan"},
    )
    link = ArtifactLinkWire(
        id="out-1",
        link_type="related",
        source_id="alpha",
        target_id="agent:related",
        metadata={"target_kind": "agent", "target_title": "Related agent"},
    )
    rows = build_artifact_panel_rows(
        _detail("alpha", children=[child], outbound_links=[link])
    ).rows

    child_label = _row_label(rows[1])
    link_label = _row_label(rows[3])

    assert any("#7DD3FC" in str(span.style) for span in child_label.spans)
    assert any("#22D3EE" in str(span.style) for span in child_label.spans)
    assert any("#60A5FA" in str(span.style) for span in link_label.spans)
    assert any("#FBBF24" in str(span.style) for span in link_label.spans)


def test_per_group_paging_keeps_other_groups_visible_after_large_group() -> None:
    children = [_node(f"child:{idx}", "agent") for idx in range(10)]
    link = ArtifactLinkWire(
        id="out-1",
        link_type="related",
        source_id="alpha",
        target_id="agent:related",
    )
    paged = _paged_detail(
        "alpha",
        children=children,
        child_total=240,
        outbound_links=[link],
    )

    model = paged_model_from_paged_detail(paged)
    rows = build_artifact_panel_rows(model.detail, paged_model=model).rows
    row_ids = [row.id for row in rows]

    assert "child:child:0" in row_ids
    assert "child:child:9" in row_ids
    assert "show-more:children" in row_ids
    assert "outbound:out-1" in row_ids
    assert "__truncated__" not in row_ids
