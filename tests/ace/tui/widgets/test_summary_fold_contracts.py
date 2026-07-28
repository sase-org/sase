"""Cross-kind contracts for fold-aware agent summary documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.ace.tui.models._agent_clan_sections import (
    CLAN_DISK_SECTIONS,
    ClanDiskMemberSnapshot,
    ClanDiskSnapshot,
    ClanSectionSnapshot,
    aggregate_clan_in_memory,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_lane_neighbors import (
    AgentLaneNeighborProjection,
    LaneNeighborRow,
)
from sase.ace.tui.models.agent_tribe_summary import (
    AgentTribeSummarySnapshot,
    build_agent_tribe_summary_snapshot,
)
from sase.ace.tui.models.fold_scale import (
    AGENT_FOLD_SCALE,
    CLAN_FOLD_SCALE,
    FAMILY_FOLD_SCALE,
    TRIBE_FOLD_SCALE,
    FoldScale,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.tools import SlowToolSource, ToolCallEntry
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import (
    build_header_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_neighbors import (
    neighbor_entry_limit,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.ace.tui.widgets.prompt_panel._fold_language import FOLD_CHARS
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
    tribe_enrichment_sections_for_fold_state,
)
from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
    TribeSectionSnapshot,
    _TribeDiskSnapshot,
)
from sase.ace.tui.widgets.prompt_panel._member_roster import MemberJumpMap
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of

_NOW = datetime(2026, 7, 19, 12, 0, 0)
_SCANNING_TAIL = "⋯ scanning member data…"


@dataclass(frozen=True, slots=True)
class _RenderedSummary:
    plain: str
    jump_map: MemberJumpMap


@dataclass(frozen=True, slots=True)
class _FoldContractCase:
    kind: str
    scale: FoldScale
    populated: dict[FoldLevel, _RenderedSummary]
    empty: dict[FoldLevel, _RenderedSummary]
    unloaded: dict[FoldLevel, _RenderedSummary]
    roster_title: str
    content_section: str
    empty_sections: tuple[str, ...]
    requires_enrichment: bool


def _single_jump_map(published: list[MemberJumpMap]) -> MemberJumpMap:
    assert len(published) == 1
    return published[0]


def _family(
    tmp_path: Path,
    *,
    suffix: str,
    with_prompt_content: bool,
) -> Agent:
    family = f"fold-contract-{suffix}"
    started = _NOW - timedelta(minutes=5)
    phases: list[Agent] = []
    for index, role in enumerate(("plan", "code")):
        artifacts = tmp_path / f"{suffix}-{role}"
        artifacts.mkdir()
        if with_prompt_content:
            (artifacts / "raw_xprompt.md").write_text(
                "\n".join(f"{role} xprompt line {line}" for line in range(1, 16))
                + "\n",
                encoding="utf-8",
            )
            (artifacts / "01_prompt.md").write_text(
                "\n".join(f"{role} prompt line {line}" for line in range(1, 16)) + "\n",
                encoding="utf-8",
            )
        response = artifacts / "response.md"
        response.write_text(f"{role} completed\n", encoding="utf-8")
        phase = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"{family}--{role}",
            project_file="/tmp/fold-contract.sase",
            status="DONE",
            start_time=started + timedelta(minutes=index * 2),
            run_start_time=started + timedelta(minutes=index * 2),
            stop_time=started + timedelta(minutes=(index + 1) * 2),
            raw_suffix=f"{suffix}-{role}",
            artifacts_dir=str(artifacts),
            response_path=str(response),
            agent_name=f"{family}--{role}",
            agent_family=family,
            agent_family_role=role,
            role_suffix=f"--{role}",
            plan_chain_root=role == "plan",
            model="gpt-5",
        )
        phases.append(phase)
    root, child = phases
    root.followup_agents = [child]
    assert root.is_family_container_row
    return root


def _render_family(agent: Agent, level: FoldLevel) -> _RenderedSummary:
    published: list[MemberJumpMap] = []
    header, error = build_header_text(
        agent,
        cheap=True,
        lane_fold_level=level,
        member_jump_map_publisher=published.append,
    )
    panel = FakePromptPanel()
    panel._update_family_display(
        agent,
        header,
        error,
        panel_level=level,
        section_fold_overrides={},
    )
    return _RenderedSummary(
        plain=plain_of(panel.captured[-1]),
        jump_map=_single_jump_map(published),
    )


def _clan_member(*, suffix: str, with_content: bool) -> Agent:
    member = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"contract.{suffix}",
        project_file="/tmp/fold-contract.sase",
        status="FAILED" if with_content else "RUNNING",
        start_time=_NOW - timedelta(minutes=5),
        run_start_time=_NOW - timedelta(minutes=5),
        stop_time=_NOW if with_content else None,
        raw_suffix=suffix,
        agent_name=f"contract.{suffix}",
        agent_clan="contract",
        agent_clan_generation="20260719115500",
        model="gpt-5",
    )
    if with_content:
        member.error_message = "Contract failed\nFull failure detail"
        member.error_traceback = "Traceback line\nValueError: contract"
    return member


def _known_clan_snapshot(container: Agent) -> ClanSectionSnapshot:
    member = container.runtime_children[0]
    return ClanSectionSnapshot(
        in_memory=aggregate_clan_in_memory(container),
        disk=ClanDiskSnapshot(
            loaded_sections=CLAN_DISK_SECTIONS,
            members=(
                ClanDiskMemberSnapshot(
                    member_identity=member.identity,
                    member_label=f".{member.agent_name.rsplit('.', 1)[-1]}",
                    loaded_sections=CLAN_DISK_SECTIONS,
                ),
            ),
            replies=(),
            prompts=(),
            context_lanes=(),
            slow_tool_calls=(),
        ),
    )


def _render_clan(
    container: Agent,
    snapshot: ClanSectionSnapshot,
    level: FoldLevel,
) -> _RenderedSummary:
    published: list[MemberJumpMap] = []
    detail = build_clan_detail_text(
        container,
        now=_NOW,
        snapshot=snapshot,
        fold_level=level,
        member_jump_map_publisher=published.append,
    )
    return _RenderedSummary(detail.plain, _single_jump_map(published))


def _tribe_agent(*, suffix: str, with_content: bool) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"tribe-{suffix}",
        project_file="/tmp/fold-contract.sase",
        status="FAILED" if with_content else "RUNNING",
        start_time=_NOW - timedelta(minutes=5),
        run_start_time=_NOW - timedelta(minutes=5),
        stop_time=_NOW if with_content else None,
        raw_suffix=suffix,
        agent_name=f"tribe-{suffix}",
        model="gpt-5",
    )
    if with_content:
        agent.error_message = "Contract failed\nFull failure detail"
        agent.error_traceback = "Traceback line\nValueError: contract"
    return agent


def _known_tribe_sections(
    panel_identity: tuple[object, ...],
) -> TribeSectionSnapshot:
    return TribeSectionSnapshot(
        panel_identity=panel_identity,
        source_signature=(),
        disk=_TribeDiskSnapshot(
            loaded_sections=frozenset({"replies", "slow-tool-calls"}),
            replies=(),
            slow_tool_calls=(),
        ),
        runtime_statistics_loaded=True,
    )


def _render_tribe(
    snapshot: AgentTribeSummarySnapshot,
    sections: TribeSectionSnapshot,
    level: FoldLevel,
) -> _RenderedSummary:
    published: list[MemberJumpMap] = []
    detail = build_tribe_detail_text(
        snapshot,
        section_snapshot=sections,
        fold_level=level,
        member_jump_map_publisher=published.append,
    )
    return _RenderedSummary(detail.plain, _single_jump_map(published))


def _family_case(tmp_path: Path) -> _FoldContractCase:
    populated_agent = _family(
        tmp_path,
        suffix="family-populated",
        with_prompt_content=True,
    )
    empty_agent = _family(
        tmp_path,
        suffix="family-empty",
        with_prompt_content=False,
    )
    populated = {
        level: _render_family(populated_agent, level) for level in FAMILY_FOLD_SCALE
    }
    return _FoldContractCase(
        kind="family",
        scale=FAMILY_FOLD_SCALE,
        populated=populated,
        empty={
            level: _render_family(empty_agent, level) for level in FAMILY_FOLD_SCALE
        },
        unloaded=populated,
        roster_title="FAMILY MEMBERS",
        content_section="FAMILY MEMBERS",
        empty_sections=(
            "AGENT XPROMPT",
            "AGENT PROMPT",
            "OUTPUT VARIABLES",
            "WORKFLOW VARIABLES",
            "SLOW TOOL CALLS",
            "ERROR",
        ),
        requires_enrichment=False,
    )


def _clan_case() -> _FoldContractCase:
    populated_container = project_clan_tree(
        [_clan_member(suffix="populated", with_content=True)]
    )[0]
    empty_container = project_clan_tree(
        [_clan_member(suffix="empty", with_content=False)]
    )[0]
    populated_snapshot = _known_clan_snapshot(populated_container)
    empty_snapshot = _known_clan_snapshot(empty_container)
    unloaded_snapshot = ClanSectionSnapshot(
        in_memory=aggregate_clan_in_memory(populated_container)
    )
    return _FoldContractCase(
        kind="clan",
        scale=CLAN_FOLD_SCALE,
        populated={
            level: _render_clan(populated_container, populated_snapshot, level)
            for level in CLAN_FOLD_SCALE
        },
        empty={
            level: _render_clan(empty_container, empty_snapshot, level)
            for level in CLAN_FOLD_SCALE
        },
        unloaded={
            level: _render_clan(populated_container, unloaded_snapshot, level)
            for level in CLAN_FOLD_SCALE
        },
        roster_title="CLAN MEMBERS",
        content_section="ERRORS",
        empty_sections=(
            "ERRORS",
            "OUTPUT VARIABLES",
            "WORKFLOW VARIABLES",
            "REPLIES",
            "SASE CONTEXT",
            "SLOW TOOL CALLS",
            "PROMPTS",
        ),
        requires_enrichment=True,
    )


def _tribe_case() -> _FoldContractCase:
    populated_snapshot = build_agent_tribe_summary_snapshot(
        "contract-populated",
        [_tribe_agent(suffix="populated", with_content=True)],
        panel_collapsed=True,
        now=_NOW,
    )
    empty_snapshot = build_agent_tribe_summary_snapshot(
        "contract-empty",
        [_tribe_agent(suffix="empty", with_content=False)],
        panel_collapsed=True,
        now=_NOW,
    )
    populated_sections = _known_tribe_sections(populated_snapshot.container_identity)
    empty_sections = _known_tribe_sections(empty_snapshot.container_identity)
    return _FoldContractCase(
        kind="tribe",
        scale=TRIBE_FOLD_SCALE,
        populated={
            level: _render_tribe(populated_snapshot, populated_sections, level)
            for level in TRIBE_FOLD_SCALE
        },
        empty={
            level: _render_tribe(empty_snapshot, empty_sections, level)
            for level in TRIBE_FOLD_SCALE
        },
        unloaded={
            level: _render_tribe(
                populated_snapshot,
                TribeSectionSnapshot(
                    panel_identity=populated_snapshot.container_identity,
                    source_signature=(),
                    loading_sections=tribe_enrichment_sections_for_fold_state(level),
                ),
                level,
            )
            for level in TRIBE_FOLD_SCALE
        },
        roster_title="TRIBE MEMBERS",
        content_section="ERRORS",
        empty_sections=(
            "NEEDS ATTENTION",
            "ERRORS",
            "OUTPUT VARIABLES",
            "WORKFLOW VARIABLES",
            "REPLIES",
            "SLOW TOOL CALLS",
            "RUNTIME STATISTICS",
        ),
        requires_enrichment=True,
    )


@pytest.fixture(params=("family", "clan", "tribe"))
def fold_contract_case(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> _FoldContractCase:
    if request.param == "family":
        return _family_case(tmp_path)
    if request.param == "clan":
        return _clan_case()
    return _tribe_case()


def _section_body(rendered: str, title: str) -> str:
    lines = rendered.splitlines()
    heading_index = next(
        index
        for index, line in enumerate(lines)
        if title in line and line.lstrip().startswith(("▸", "▾", "▼", "◆"))
    )
    body: list[str] = []
    for line in lines[heading_index + 1 :]:
        stripped = line.strip()
        if stripped and len(set(stripped)) == 1 and stripped[0] in {"─", "━"}:
            break
        body.append(line)
    return "\n".join(body).strip()


def test_zero_content_sections_are_absent_at_every_fold_level(
    fold_contract_case: _FoldContractCase,
) -> None:
    for level in fold_contract_case.scale:
        rendered = fold_contract_case.empty[level].plain
        for section in fold_contract_case.empty_sections:
            assert section not in rendered, (
                fold_contract_case.kind,
                level,
                section,
            )


def test_numbered_rosters_and_jump_maps_exist_at_every_fold_level(
    fold_contract_case: _FoldContractCase,
) -> None:
    for level in fold_contract_case.scale:
        rendered = fold_contract_case.populated[level]
        assert fold_contract_case.roster_title in rendered.plain
        assert " 0  " in rendered.plain
        assert rendered.jump_map.targets
        assert rendered.jump_map.targets[0].number == "0"


def test_scanning_tail_exactly_tracks_unloaded_required_enrichment(
    fold_contract_case: _FoldContractCase,
) -> None:
    expected_unloaded_count = int(fold_contract_case.requires_enrichment)
    for level in fold_contract_case.scale:
        assert fold_contract_case.populated[level].plain.count(_SCANNING_TAIL) == 0
        assert fold_contract_case.empty[level].plain.count(_SCANNING_TAIL) == 0
        assert (
            fold_contract_case.unloaded[level].plain.count(_SCANNING_TAIL)
            == expected_unloaded_count
        )


def test_adjacent_levels_change_non_empty_section_bodies(
    fold_contract_case: _FoldContractCase,
) -> None:
    bodies = [
        _section_body(
            fold_contract_case.populated[level].plain,
            fold_contract_case.content_section,
        )
        for level in fold_contract_case.scale
    ]
    for lower, higher in zip(bodies, bodies[1:], strict=False):
        assert lower != higher, (fold_contract_case.kind, lower)


def test_family_conversation_bodies_do_not_change_across_scale(
    tmp_path: Path,
) -> None:
    family = _family_case(tmp_path)
    documents = []
    for level in family.scale:
        rendered = family.populated[level].plain
        documents.append(rendered[rendered.index("AGENT XPROMPT") :])

    assert documents == [documents[0]] * len(documents)


_LANE_NEIGHBOR_TOTAL = 12
_NUMBERED_ROW = re.compile(r"^ (\d+)  ", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class _LaneNeighborContractCase:
    kind: str
    scale: FoldScale
    leading_member_count: int
    rendered: dict[FoldLevel, _RenderedSummary]


def _lane_neighbor(lane_name: str, index: int) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{lane_name}.neighbor{index}",
        project_file="/tmp/fold-contract.sase",
        status="DONE",
        start_time=_NOW - timedelta(minutes=5),
        run_start_time=_NOW - timedelta(minutes=5),
        stop_time=_NOW,
        raw_suffix=f"neighbor{index}",
        agent_name=f"{lane_name}.neighbor{index}",
        model="gpt-5",
    )


def _lane_projection(lane: Agent, lane_name: str) -> AgentLaneNeighborProjection:
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
    return AgentLaneNeighborProjection(
        lane_identity=lane.identity,
        rows=rows,
        suppressed_lane_member_count=0,
    )


def _render_lane(
    agent: Agent,
    projection: AgentLaneNeighborProjection,
    level: FoldLevel,
) -> _RenderedSummary:
    published: list[MemberJumpMap] = []
    header, _ = build_header_text(
        agent,
        cheap=True,
        lane_fold_level=level,
        lane_neighbors=projection,
        member_jump_map_publisher=published.append,
    )
    return _RenderedSummary(header.plain, _single_jump_map(published))


def _single_agent_lane_case() -> _LaneNeighborContractCase:
    lane_name = "fold-contract-lane"
    lane = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=lane_name,
        project_file="/tmp/fold-contract.sase",
        status="RUNNING",
        start_time=_NOW - timedelta(minutes=9),
        run_start_time=_NOW - timedelta(minutes=9),
        raw_suffix="lane",
        agent_name=lane_name,
        model="gpt-5",
    )
    projection = _lane_projection(lane, lane_name)
    return _LaneNeighborContractCase(
        kind="single-agent-lane",
        scale=AGENT_FOLD_SCALE,
        leading_member_count=0,
        rendered={
            level: _render_lane(lane, projection, level) for level in AGENT_FOLD_SCALE
        },
    )


def _family_lane_case(tmp_path: Path) -> _LaneNeighborContractCase:
    lane = _family(tmp_path, suffix="lane-family", with_prompt_content=False)
    projection = _lane_projection(lane, lane.presented_identity_name or "")
    return _LaneNeighborContractCase(
        kind="family-lane",
        scale=FAMILY_FOLD_SCALE,
        leading_member_count=2,
        rendered={
            level: _render_lane(lane, projection, level) for level in FAMILY_FOLD_SCALE
        },
    )


@pytest.fixture(params=("single-agent-lane", "family-lane"))
def lane_neighbor_case(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> _LaneNeighborContractCase:
    if request.param == "single-agent-lane":
        return _single_agent_lane_case()
    return _family_lane_case(tmp_path)


def _shown_neighbor_count(case: _LaneNeighborContractCase, level: FoldLevel) -> int:
    limit = neighbor_entry_limit(level, case.scale)
    return _LANE_NEIGHBOR_TOTAL if limit is None else min(_LANE_NEIGHBOR_TOTAL, limit)


def _heading_line(rendered: str, title: str) -> str:
    return next(
        line
        for line in rendered.splitlines()
        if title in line and line.lstrip().startswith(("▸", "▾", "▼", "◆"))
    )


def test_lane_neighbor_glyph_tracks_the_lane_fold_level(
    lane_neighbor_case: _LaneNeighborContractCase,
) -> None:
    for level in lane_neighbor_case.scale:
        heading = _heading_line(
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
        body = _section_body(rendered, "NEIGHBORS")
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
        heading = _heading_line(
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


@dataclass(frozen=True, slots=True)
class _SlowToolFoldContractCase:
    kind: str
    scale: FoldScale
    rendered: dict[FoldLevel, str]


def _slow_tool_summary() -> DetailHeaderSummary:
    entry = ToolCallEntry(
        recorded_at="2026-07-19T11:55:00+00:00",
        runtime="codex",
        event="ToolUse",
        status="success",
        tool_name="Bash",
        duration_ms=45_000,
        completed_at="2026-07-19T11:55:45+00:00",
        tool_input_summary={
            "description": "run contract checks",
            "command": "pytest tests/ace/tui -q\nprintf slow-detail-visible",
        },
        tool_response_summary={
            "exit_code": 0,
            "stdout_preview": "contract checks passed",
        },
    )
    return DetailHeaderSummary(
        slow_tool_sources=(
            SlowToolSource(
                label=None,
                entries=(entry,),
                agent_is_active=False,
                end_reference=None,
                palette_index=0,
            ),
        )
    )


def _render_slow_tool_lane(agent: Agent, level: FoldLevel) -> str:
    header, _ = build_header_text(
        agent,
        summary=_slow_tool_summary(),
        lane_fold_level=level,
    )
    return header.plain


def _single_slow_tool_lane_case() -> _SlowToolFoldContractCase:
    lane = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fold-contract-slow",
        project_file="/tmp/fold-contract.sase",
        status="DONE",
        start_time=_NOW - timedelta(minutes=9),
        run_start_time=_NOW - timedelta(minutes=9),
        stop_time=_NOW,
        raw_suffix="slow-lane",
        agent_name="fold-contract-slow",
        model="gpt-5",
    )
    return _SlowToolFoldContractCase(
        kind="single-agent-lane",
        scale=AGENT_FOLD_SCALE,
        rendered={
            level: _render_slow_tool_lane(lane, level) for level in AGENT_FOLD_SCALE
        },
    )


def _family_slow_tool_lane_case(tmp_path: Path) -> _SlowToolFoldContractCase:
    lane = _family(tmp_path, suffix="slow-family", with_prompt_content=False)
    return _SlowToolFoldContractCase(
        kind="family-lane",
        scale=FAMILY_FOLD_SCALE,
        rendered={
            level: _render_slow_tool_lane(lane, level) for level in FAMILY_FOLD_SCALE
        },
    )


@pytest.fixture(params=("single-agent-lane", "family-lane"))
def slow_tool_fold_case(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> _SlowToolFoldContractCase:
    if request.param == "single-agent-lane":
        return _single_slow_tool_lane_case()
    return _family_slow_tool_lane_case(tmp_path)


def test_slow_tool_rows_follow_the_positional_lane_ladder(
    slow_tool_fold_case: _SlowToolFoldContractCase,
) -> None:
    documents = [
        slow_tool_fold_case.rendered[level] for level in slow_tool_fold_case.scale
    ]

    assert "run contract checks" in documents[0]
    assert "slow-detail-visible" not in documents[0]
    assert "full commands hidden" in documents[0]
    assert "slow-detail-visible" in documents[1]
    if len(documents) == 3:
        assert "│ output" not in documents[1]
        assert "│ output contract checks passed" in documents[2]
    else:
        assert "│ output contract checks passed" in documents[1]
    assert len(set(documents)) == len(documents)


def test_slow_tool_heading_glyph_tracks_the_lane_fold_level(
    slow_tool_fold_case: _SlowToolFoldContractCase,
) -> None:
    for level in slow_tool_fold_case.scale:
        heading = _heading_line(
            slow_tool_fold_case.rendered[level],
            "SLOW TOOL CALLS",
        )
        assert heading.startswith(FOLD_CHARS[level]), (
            slow_tool_fold_case.kind,
            level,
            heading,
        )
