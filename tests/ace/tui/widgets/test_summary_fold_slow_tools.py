"""Fold contracts for slow-tool summaries in lane headers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_scale import (
    AGENT_FOLD_SCALE,
    FAMILY_FOLD_SCALE,
    FoldScale,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.tools import SlowToolSource, ToolCallEntry
from sase.ace.tui.widgets.prompt_panel._agent_display_header import (
    build_header_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.ace.tui.widgets.prompt_panel._fold_language import FOLD_CHARS
from tests.ace.tui.widgets._summary_fold_contract_helpers import (
    NOW,
    heading_line,
    make_family,
)


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
        start_time=NOW - timedelta(minutes=9),
        run_start_time=NOW - timedelta(minutes=9),
        stop_time=NOW,
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
    lane = make_family(
        tmp_path,
        suffix="slow-family",
        with_prompt_content=False,
    )
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
        heading = heading_line(
            slow_tool_fold_case.rendered[level],
            "SLOW TOOL CALLS",
        )
        assert heading.startswith(FOLD_CHARS[level]), (
            slow_tool_fold_case.kind,
            level,
            heading,
        )
