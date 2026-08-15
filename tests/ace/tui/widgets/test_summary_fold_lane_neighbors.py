"""Fold contracts for lane neighbor summaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.sase_agent_neighbors import (
    SaseAgentNeighborProjection,
    LaneNeighborRow,
)
from sase.ace.tui.models.fold_scale import (
    AGENT_FOLD_SCALE,
    FAMILY_FOLD_SCALE,
    FoldScale,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_header import (
    build_header_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_neighbors import (
    neighbor_entry_limit,
)
from sase.ace.tui.widgets.prompt_panel._fold_language import FOLD_CHARS
from sase.ace.tui.widgets.prompt_panel._member_roster import MemberJumpMap
from tests.ace.tui.widgets._summary_fold_contract_helpers import (
    NOW,
    RenderedSummary,
    heading_line,
    make_family,
    section_body,
    single_jump_map,
)

_LANE_NEIGHBOR_TOTAL = 12
_NUMBERED_ROW = re.compile(r"^ (\d+)  ", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class _LaneNeighborContractCase:
    kind: str
    scale: FoldScale
    leading_member_count: int
    rendered: dict[FoldLevel, RenderedSummary]


def _lane_neighbor(lane_name: str, index: int) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{lane_name}.neighbor{index}",
        project_file="/tmp/fold-contract.sase",
        status="DONE",
        start_time=NOW - timedelta(minutes=5),
        run_start_time=NOW - timedelta(minutes=5),
        stop_time=NOW,
        raw_suffix=f"neighbor{index}",
        agent_name=f"{lane_name}.neighbor{index}",
        model="gpt-5",
    )


def _lane_projection(lane: Agent, lane_name: str) -> SaseAgentNeighborProjection:
    rows = tuple(
        LaneNeighborRow(
            agent=_lane_neighbor(lane_name, index),
            relation="neighbor",
            group_label=f"{lane_name} hood",
            label_prefix=lane_name,
            is_prospective=False,
            is_dismissed=False,
        )
        for index in range(_LANE_NEIGHBOR_TOTAL)
    )
    return SaseAgentNeighborProjection(
        lane_identity=lane.identity,
        rows=rows,
        suppressed_lane_member_count=0,
    )


def _render_lane(
    agent: Agent,
    projection: SaseAgentNeighborProjection,
    level: FoldLevel,
) -> RenderedSummary:
    published: list[MemberJumpMap] = []
    header, _ = build_header_text(
        agent,
        cheap=True,
        lane_fold_level=level,
        lane_neighbors=projection,
        member_jump_map_publisher=published.append,
    )
    return RenderedSummary(header.plain, single_jump_map(published))


def _single_sase_agent_case() -> _LaneNeighborContractCase:
    lane_name = "fold-contract-lane"
    lane = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=lane_name,
        project_file="/tmp/fold-contract.sase",
        status="RUNNING",
        start_time=NOW - timedelta(minutes=9),
        run_start_time=NOW - timedelta(minutes=9),
        raw_suffix="lane",
        agent_name=lane_name,
        model="gpt-5",
    )
    projection = _lane_projection(lane, lane_name)
    return _LaneNeighborContractCase(
        kind="single-sase-agent",
        scale=AGENT_FOLD_SCALE,
        leading_member_count=0,
        rendered={
            level: _render_lane(lane, projection, level) for level in AGENT_FOLD_SCALE
        },
    )


def _family_lane_case(tmp_path: Path) -> _LaneNeighborContractCase:
    lane = make_family(
        tmp_path,
        suffix="lane-family",
        with_prompt_content=False,
    )
    projection = _lane_projection(lane, lane.presented_identity_name or "")
    return _LaneNeighborContractCase(
        kind="family-sase-agent",
        scale=FAMILY_FOLD_SCALE,
        leading_member_count=2,
        rendered={
            level: _render_lane(lane, projection, level) for level in FAMILY_FOLD_SCALE
        },
    )


@pytest.fixture(params=("single-sase-agent", "family-sase-agent"))
def lane_neighbor_case(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> _LaneNeighborContractCase:
    if request.param == "single-sase-agent":
        return _single_sase_agent_case()
    return _family_lane_case(tmp_path)


def _shown_neighbor_count(case: _LaneNeighborContractCase, level: FoldLevel) -> int:
    limit = neighbor_entry_limit(level, case.scale)
    return _LANE_NEIGHBOR_TOTAL if limit is None else min(_LANE_NEIGHBOR_TOTAL, limit)


def test_lane_neighbor_glyph_tracks_the_lane_fold_level(
    lane_neighbor_case: _LaneNeighborContractCase,
) -> None:
    for level in lane_neighbor_case.scale:
        heading = heading_line(
            lane_neighbor_case.rendered[level].plain,
            "NEIGHBORS",
        )
        assert heading.startswith(FOLD_CHARS[level]), (
            lane_neighbor_case.kind,
            level,
            heading,
        )


def test_lane_neighbor_rows_follow_the_positional_ladder(
    lane_neighbor_case: _LaneNeighborContractCase,
) -> None:
    for level in lane_neighbor_case.scale:
        rendered = lane_neighbor_case.rendered[level].plain
        body = section_body(rendered, "NEIGHBORS")
        shown = _shown_neighbor_count(lane_neighbor_case, level)
        assert len(_NUMBERED_ROW.findall(body)) == shown, (
            lane_neighbor_case.kind,
            level,
        )
        hidden = _LANE_NEIGHBOR_TOTAL - shown
        if hidden:
            assert f"… +{hidden} more neighbors" in body
        else:
            assert "more neighbors" not in body


def test_lane_neighbor_heading_always_counts_every_neighbor(
    lane_neighbor_case: _LaneNeighborContractCase,
) -> None:
    for level in lane_neighbor_case.scale:
        heading = heading_line(
            lane_neighbor_case.rendered[level].plain,
            "NEIGHBORS",
        )
        assert heading.endswith(f"NEIGHBORS · {_LANE_NEIGHBOR_TOTAL}"), (
            lane_neighbor_case.kind,
            level,
        )


def test_lane_document_digits_match_the_published_jump_map(
    lane_neighbor_case: _LaneNeighborContractCase,
) -> None:
    for level in lane_neighbor_case.scale:
        rendered = lane_neighbor_case.rendered[level]
        expected_total = lane_neighbor_case.leading_member_count
        expected_total += _shown_neighbor_count(lane_neighbor_case, level)
        numbers = [target.number for target in rendered.jump_map.targets]
        assert numbers == _NUMBERED_ROW.findall(rendered.plain), (
            lane_neighbor_case.kind,
            level,
        )
        assert len(numbers) == expected_total
        width = 1 if expected_total <= 10 else 2
        assert numbers == [f"{index:0{width}d}" for index in range(expected_total)]


def test_lane_neighbor_target_roles_stay_neighbor_at_every_level(
    lane_neighbor_case: _LaneNeighborContractCase,
) -> None:
    leading = lane_neighbor_case.leading_member_count
    for level in lane_neighbor_case.scale:
        targets = lane_neighbor_case.rendered[level].jump_map.targets
        assert [target.role for target in targets[:leading]] == ["member"] * leading
        assert {target.role for target in targets[leading:]} == {"neighbor"}
