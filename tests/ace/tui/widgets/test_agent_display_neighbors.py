"""Fold-aware lane-neighbor detail panel tests."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_lane_neighbors import (
    AgentLaneNeighborProjection,
    LaneNeighborRow,
)
from sase.ace.tui.models.fold_scale import AGENT_FOLD_SCALE, FAMILY_FOLD_SCALE
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_neighbors import (
    _neighbor_roster_entries,
    append_lane_neighbors_section,
    neighbor_entry_limit,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
)
from sase.ace.tui.widgets.prompt_panel._member_roster_digest import (
    _AgentRosterDigest,
)
from tests.ace.tui.widgets._agent_display_plan_helpers import plan_summary

_NOW = datetime(2026, 7, 25, 14, 0, 0)


def _agent(name: str, **overrides: object) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/neighbors.sase",
        "status": "DONE",
        "start_time": _NOW - timedelta(minutes=5),
        "stop_time": _NOW,
        "raw_suffix": name,
        "agent_name": name,
        "model": "codex/gpt-5",
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _row(
    agent: Agent,
    *,
    group: str = "descendants",
    prefix: str = "lane",
    dismissed: bool = False,
    prospective: bool = False,
) -> LaneNeighborRow:
    return LaneNeighborRow(
        agent=agent,
        relation="descendant",
        group_label=group,
        label_prefix=prefix,
        is_prospective=prospective,
        is_dismissed=dismissed,
    )


def _projection(
    lane: Agent,
    rows: tuple[LaneNeighborRow, ...],
    *,
    suppressed: int = 0,
) -> AgentLaneNeighborProjection:
    return AgentLaneNeighborProjection(
        lane_identity=lane.identity,
        rows=rows,
        suppressed_lane_member_count=suppressed,
    )


@pytest.mark.parametrize(
    ("level", "scale", "expected"),
    [
        (FoldLevel.COLLAPSED, AGENT_FOLD_SCALE, 3),
        (FoldLevel.EXPANDED, AGENT_FOLD_SCALE, 10),
        (FoldLevel.FULLY_EXPANDED, AGENT_FOLD_SCALE, None),
        (FoldLevel.EXPANDED, FAMILY_FOLD_SCALE, 3),
        (FoldLevel.FULLY_EXPANDED, FAMILY_FOLD_SCALE, None),
    ],
)
def test_neighbor_entry_limit_uses_lane_scale_position(
    level: FoldLevel,
    scale: tuple[FoldLevel, ...],
    expected: int | None,
) -> None:
    assert neighbor_entry_limit(level, scale) == expected


def test_neighbor_entries_share_labels_annotations_and_target_roles() -> None:
    prospective = _agent("lane.code")
    dismissed = _agent("lane.scratch")
    rows = (
        _row(
            prospective,
            group="lane hood",
            prospective=True,
        ),
        _row(dismissed, dismissed=True),
    )

    entries = _neighbor_roster_entries(
        rows,
        unread_agent_ids={prospective.identity},
        marked_identities={dismissed.identity},
        now=_NOW,
    )

    assert [entry.label for entry in entries] == [".code", ".scratch"]
    assert [entry.group_label for entry in entries] == [
        "lane hood",
        "descendants",
    ]
    assert entries[0].is_unread is True
    assert isinstance(entries[0].digest, _AgentRosterDigest)
    assert entries[0].digest.extra_annotations == ("folded",)
    assert entries[1].is_marked is True
    assert entries[1].is_dismissed is True
    assert entries[1].target_role == "dismissed"


@pytest.mark.parametrize(
    ("level", "scale", "shown"),
    [
        (FoldLevel.COLLAPSED, AGENT_FOLD_SCALE, 3),
        (FoldLevel.EXPANDED, AGENT_FOLD_SCALE, 10),
        (FoldLevel.FULLY_EXPANDED, AGENT_FOLD_SCALE, 12),
        (FoldLevel.EXPANDED, FAMILY_FOLD_SCALE, 3),
        (FoldLevel.FULLY_EXPANDED, FAMILY_FOLD_SCALE, 12),
    ],
)
def test_neighbors_section_renders_fold_ladder_and_truthful_count(
    level: FoldLevel,
    scale: tuple[FoldLevel, ...],
    shown: int,
) -> None:
    lane = _agent("lane")
    rows = tuple(_row(_agent(f"lane.child{index}")) for index in range(12))
    text = Text()

    jump_map = append_lane_neighbors_section(
        text,
        projection=_projection(lane, rows),
        panel_level=level,
        scale=scale,
        now=_NOW,
    )

    assert jump_map is not None
    assert len(jump_map.targets) == shown
    assert "NEIGHBORS · 12" in text.plain
    assert text.plain.count(" · agent · ") == shown
    if shown < 12:
        assert f"… +{12 - shown} more neighbors (zz / za to show more)" in text.plain
    else:
        assert "more neighbors" not in text.plain


def test_neighbors_section_marks_dismissed_targets_and_suppression_tail() -> None:
    lane = _agent("lane")
    active = _agent("lane.active")
    dismissed = _agent("lane.dismissed")
    text = Text()

    jump_map = append_lane_neighbors_section(
        text,
        projection=_projection(
            lane,
            (
                _row(active),
                _row(dismissed, dismissed=True),
            ),
            suppressed=2,
        ),
        panel_level=FoldLevel.FULLY_EXPANDED,
        scale=AGENT_FOLD_SCALE,
        now=_NOW,
    )

    assert jump_map is not None
    assert [target.role for target in jump_map.targets] == [
        "neighbor",
        "dismissed",
    ]
    assert "⊘ .dismissed" in text.plain
    assert "dismissed" in text.plain
    assert "… +2 also listed under FAMILY MEMBERS" in text.plain


def test_header_places_neighbors_below_workflow_variables_and_above_sase_context() -> (
    None
):
    lane = _agent("lane", status="FAILED", error_message="boom")
    lane.step_output = {"meta_foo": "bar"}
    neighbor = _agent("lane.child")
    published = []

    header, _ = build_header_text(
        lane,
        lane_fold_level=FoldLevel.COLLAPSED,
        summary=DetailHeaderSummary(associated_plan=plan_summary()),
        lane_neighbors=_projection(lane, (_row(neighbor),)),
        member_jump_map_publisher=published.append,
    )

    plain = header.plain
    assert plain.index("WORKFLOW VARIABLES") < plain.index("NEIGHBORS")
    assert plain.index("NEIGHBORS") < plain.index("SASE CONTEXT")
    assert plain.index("SASE CONTEXT") < plain.index("ERROR")
    assert plain.index("NEIGHBORS") < plain.rindex("─" * 50)
    assert len(published) == 1
    assert [target.member_identity for target in published[0].targets] == [
        neighbor.identity
    ]


def test_family_header_publishes_one_contiguous_shared_width_jump_map() -> None:
    root = _agent(
        "lane--plan",
        agent_family="lane",
        agent_family_role="root",
        role_suffix="--plan",
        plan_chain_root=True,
    )
    child = _agent(
        "lane--code",
        agent_family="lane",
        agent_family_role="code",
        role_suffix="--code",
    )
    root.followup_agents = [child]
    neighbors = tuple(
        _row(_agent(f"lane.neighbor{index}"), prefix="lane") for index in range(9)
    )
    published = []

    header, _ = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.FULLY_EXPANDED,
        lane_neighbors=_projection(root, neighbors, suppressed=1),
        member_jump_map_publisher=published.append,
    )

    assert header.plain.index("FAMILY MEMBERS") < header.plain.index("NEIGHBORS")
    assert len(published) == 1
    assert [target.number for target in published[0].targets] == [
        f"{index:02d}" for index in range(11)
    ]
    assert [target.member_identity for target in published[0].targets[:2]] == [
        root.identity,
        child.identity,
    ]
    assert [target.role for target in published[0].targets[2:]] == ["neighbor"] * 9


def test_neighbors_are_absent_for_empty_projection_and_non_lane_rows() -> None:
    lane = _agent("lane")
    empty, _ = build_header_text(
        lane,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        lane_neighbors=_projection(lane, ()),
    )

    family_child = _agent(
        "lane--code",
        parent_timestamp="lane--plan",
        agent_family="lane",
    )
    invalid_projection = _projection(
        family_child,
        (_row(_agent("lane.peer"), prefix="lane"),),
    )
    child_header, _ = build_header_text(
        family_child,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        lane_neighbors=invalid_projection,
    )

    clan = _agent("clan")
    clan.is_clan_container = True
    clan_header, _ = build_header_text(
        clan,
        cheap=True,
        lane_neighbors=_projection(clan, (_row(_agent("clan.peer")),)),
    )

    assert "NEIGHBORS" not in empty.plain
    assert "NEIGHBORS" not in child_header.plain
    assert "NEIGHBORS" not in clan_header.plain
