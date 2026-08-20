"""Tests for the agent ARTIFACTS Reads prompt-panel rows."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_artifact_reads import (
    MAX_VISIBLE_READS,
    append_agent_artifact_read_rows,
)
from sase.ace.tui.widgets.prompt_panel._agent_artifacts_lane import (
    append_agent_artifacts_lane,
)
from sase.ace.tui.widgets.prompt_panel._agent_context import (
    append_agent_context_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    REASON_LINE_CELL_LIMIT,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.artifact_read_log import ARTIFACT_READ_LOG_SCHEMA_VERSION, ArtifactReadEvent
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def _event(
    *,
    ref: str,
    timestamp: str,
    reason: str = "needed it",
    read_id: str | None = None,
    resolved_path: str | None = "/tmp/test/plan.md",
) -> ArtifactReadEvent:
    return ArtifactReadEvent(
        schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
        id=read_id or ref + timestamp,
        timestamp=timestamp,
        project="test",
        cwd="/tmp/test",
        ref=ref,
        reason=reason,
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/tmp/test/artifacts",
        recorded_link=False,
        resolved_path=resolved_path,
    )


def _display(
    event: ArtifactReadEvent, label: str | None = None
) -> ArtifactReadDisplayEvent:
    return ArtifactReadDisplayEvent(event=event, agent_label=label)


def _hint_state(start: int = 1) -> HeaderHintState:
    return HeaderHintState(
        hint_counter=start,
        hint_mappings={},
        workspace_dir=None,
        tool_call_reports={},
    )


def test_empty_events_appends_nothing() -> None:
    text = Text()
    append_agent_artifact_read_rows(text, events=())
    assert text.plain == ""


def test_read_only_artifacts_lane_renders_context() -> None:
    text = Text()
    event = _event(
        ref="plan:202608/design.md",
        timestamp="2026-05-24T14:22:08+00:00",
        reason="compare the approved constraints with this implementation",
    )
    append_agent_context_section(text, artifact_reads=(_display(event),))

    plain = text.plain
    assert "SASE CONTEXT\n" in plain
    assert "▸ ARTIFACTS · 1 read\n" in plain
    assert "  Reads:\n" in plain
    assert "14:22:08  ← plan:202608/design.md" in plain
    assert "↳ compare the approved constraints with this implementation" in plain
    assert "  Commits:" not in plain
    assert "  Deltas:" not in plain
    assert "  Files:" not in plain


def test_reads_precede_commits_deltas_and_files() -> None:
    text = Text()
    agent = make_agent(
        step_output={
            "meta_commits": [
                {
                    "message": "feat: grouped outputs",
                    "sha": "abcdef1234567890",
                }
            ]
        }
    )
    append_agent_artifacts_lane(
        text,
        agent=agent,
        artifact_reads=(
            _display(
                _event(
                    ref="plan:202608/design.md",
                    timestamp="2026-05-24T14:22:08+00:00",
                )
            ),
        ),
        artifact_file_paths=[
            ArtifactFilePath("reports/result.md", "/tmp/reports/result.md"),
        ],
    )
    plain = text.plain
    assert "▸ ARTIFACTS · 1 read · 1 commit · 1 artifact file\n" in plain
    assert plain.index("  Reads:") < plain.index("  Commits:")
    assert plain.index("  Commits:") < plain.index("  Files:")


def test_hint_state_maps_resolved_paths_and_skips_pathless() -> None:
    with_path = _event(
        ref="plan:202608/design.md",
        timestamp="2026-05-24T14:22:08+00:00",
        reason="needed the design",
        read_id="read-1",
        resolved_path="/tmp/test/design.md",
    )
    pathless = _event(
        ref="bead:sase-1",
        timestamp="2026-05-24T14:21:08+00:00",
        reason="legacy row",
        read_id="read-2",
        resolved_path=None,
    )
    state = _hint_state(start=3)
    text = Text()
    append_agent_artifact_read_rows(
        text,
        events=(_display(with_path), _display(pathless)),
        hint_state=state,
    )

    assert "← [3] plan:202608/design.md" in text.plain
    assert "← bead:sase-1" in text.plain
    assert "[4]" not in text.plain
    assert state.hint_mappings == {3: "/tmp/test/design.md"}
    assert state.hint_counter == 4


def test_overflow_renders_truncation_footer() -> None:
    events = tuple(
        _event(
            ref=f"plan:file_{index}.md",
            timestamp=f"2026-05-24T14:{30 - index:02d}:00+00:00",
            reason=f"reason {index}",
            read_id=f"id-{index}",
        )
        for index in range(MAX_VISIBLE_READS + 2)
    )
    text = Text()
    append_agent_artifacts_lane(
        text, artifact_reads=tuple(_display(event) for event in events)
    )

    plain = text.plain
    assert "▸ ARTIFACTS · 7 reads\n" in plain
    assert plain.count("↳") == MAX_VISIBLE_READS
    overflow = len(events) - MAX_VISIBLE_READS
    assert f"+ {overflow} more" in plain
    earliest_hhmm = events[-1].timestamp[11:16]
    assert f"· {earliest_hhmm} earliest" in plain


def test_repeated_refs_remain_separate_rows() -> None:
    first = _event(
        ref="plan:design.md",
        timestamp="2026-05-24T14:22:08+00:00",
        reason="first look",
        read_id="read-1",
    )
    second = _event(
        ref="plan:design.md",
        timestamp="2026-05-24T14:18:31+00:00",
        reason="second look",
        read_id="read-2",
    )
    text = Text()
    append_agent_artifact_read_rows(text, events=(_display(first), _display(second)))
    plain = text.plain
    assert plain.count("plan:design.md") == 2
    assert "first look" in plain
    assert "second look" in plain


def test_long_reason_is_wrapped_without_truncation() -> None:
    long_reason = " ".join(f"reason-word-{index:02d}" for index in range(18))
    text = Text()
    event = _event(
        ref="plan:skill.md",
        timestamp="2026-05-24T14:00:00+00:00",
        reason=long_reason,
    )
    append_agent_artifact_read_rows(text, events=(_display(event),))

    plain = text.plain
    assert "…" not in plain
    assert long_reason in " ".join(plain.split())
    for line in plain.splitlines():
        assert cell_len(line) <= REASON_LINE_CELL_LIMIT


def test_attributed_rows_render_role_labels() -> None:
    text = Text()
    events = (
        _display(
            _event(
                ref="plan:design.md",
                timestamp="2026-05-24T14:22:08+00:00",
                read_id="id-1",
            ),
            "coder",
        ),
        _display(
            _event(
                ref="research:prior.md",
                timestamp="2026-05-24T14:21:00+00:00",
                read_id="id-2",
            ),
            "plan",
        ),
    )
    append_agent_artifact_read_rows(text, events=events)

    plain = text.plain
    assert "14:22:08  coder  ← plan:design.md" in plain
    assert "14:21:00  plan   ← research:prior.md" in plain


def test_single_agent_rows_omit_empty_role_column() -> None:
    text = Text()
    append_agent_artifact_read_rows(
        text,
        events=(
            _display(
                _event(
                    ref="plan:design.md",
                    timestamp="2026-05-24T14:22:08+00:00",
                )
            ),
        ),
    )
    row = next(line for line in text.plain.splitlines() if "plan:design.md" in line)
    assert "14:22:08  ← plan:design.md" in row


def test_no_output_when_lane_has_no_reads_or_outputs() -> None:
    text = Text()
    append_agent_artifacts_lane(text)
    assert text.plain == ""
