"""Cross-kind contracts for fold-aware agent summary documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
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
from sase.ace.tui.models.agent_tribe_summary import (
    AgentTribeSummarySnapshot,
    build_agent_tribe_summary_snapshot,
)
from sase.ace.tui.models.fold_scale import (
    CLAN_FOLD_SCALE,
    FAMILY_FOLD_SCALE,
    TRIBE_FOLD_SCALE,
    FoldScale,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
    tribe_enrichment_sections_for_fold_state,
)
from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
    TribeSectionSnapshot,
    _TribeDiskSnapshot,
)
from sase.ace.tui.widgets.prompt_panel._member_roster import MemberJumpMap
from tests.ace.tui.widgets._summary_fold_contract_helpers import (
    NOW,
    RenderedSummary,
    make_family,
    render_family,
    section_body,
    single_jump_map,
)

_SCANNING_TAIL = "⋯ scanning member data…"


@dataclass(frozen=True, slots=True)
class _FoldContractCase:
    kind: str
    scale: FoldScale
    populated: dict[FoldLevel, RenderedSummary]
    empty: dict[FoldLevel, RenderedSummary]
    unloaded: dict[FoldLevel, RenderedSummary]
    roster_title: str
    content_section: str
    empty_sections: tuple[str, ...]
    requires_enrichment: bool


def _clan_member(*, suffix: str, with_content: bool) -> Agent:
    member = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"contract.{suffix}",
        project_file="/tmp/fold-contract.sase",
        status="FAILED" if with_content else "RUNNING",
        start_time=NOW - timedelta(minutes=5),
        run_start_time=NOW - timedelta(minutes=5),
        stop_time=NOW if with_content else None,
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
) -> RenderedSummary:
    published: list[MemberJumpMap] = []
    detail = build_clan_detail_text(
        container,
        now=NOW,
        snapshot=snapshot,
        fold_level=level,
        member_jump_map_publisher=published.append,
    )
    return RenderedSummary(detail.plain, single_jump_map(published))


def _tribe_agent(*, suffix: str, with_content: bool) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"tribe-{suffix}",
        project_file="/tmp/fold-contract.sase",
        status="FAILED" if with_content else "RUNNING",
        start_time=NOW - timedelta(minutes=5),
        run_start_time=NOW - timedelta(minutes=5),
        stop_time=NOW if with_content else None,
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
) -> RenderedSummary:
    published: list[MemberJumpMap] = []
    detail = build_tribe_detail_text(
        snapshot,
        section_snapshot=sections,
        fold_level=level,
        member_jump_map_publisher=published.append,
    )
    return RenderedSummary(detail.plain, single_jump_map(published))


def _family_case(tmp_path: Path) -> _FoldContractCase:
    populated_agent = make_family(
        tmp_path,
        suffix="family-populated",
        with_prompt_content=True,
    )
    empty_agent = make_family(
        tmp_path,
        suffix="family-empty",
        with_prompt_content=False,
    )
    populated = {
        level: render_family(populated_agent, level) for level in FAMILY_FOLD_SCALE
    }
    return _FoldContractCase(
        kind="family",
        scale=FAMILY_FOLD_SCALE,
        populated=populated,
        empty={level: render_family(empty_agent, level) for level in FAMILY_FOLD_SCALE},
        unloaded=populated,
        roster_title="FAMILY SHELLS",
        content_section="FAMILY SHELLS",
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
        now=NOW,
    )
    empty_snapshot = build_agent_tribe_summary_snapshot(
        "contract-empty",
        [_tribe_agent(suffix="empty", with_content=False)],
        panel_collapsed=True,
        now=NOW,
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
        section_body(
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
