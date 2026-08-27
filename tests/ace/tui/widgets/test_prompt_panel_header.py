"""Integration tests for the prompt-panel header SASE CONTEXT section."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from rich.text import Text

from sase.ace.tui import artifact_reads as artifact_reads_module
from sase.ace.tui import memory_reads as memory_reads_module
from sase.ace.tui import opened_workspaces as opened_workspaces_module
from sase.ace.tui import skill_uses as skill_uses_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tools import SlowToolSource, ToolCallEntry
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_detail_header_summary,
    build_header_text,
)
from sase.memory.read_log import (
    READ_LOG_SCHEMA_VERSION,
    MemoryReadEvent,
    memory_read_log_path,
)
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
)
from sase.linked_repos import OPENED_LINKED_FILENAME
from sase.skills.use_log import (
    SKILL_USE_LOG_SCHEMA_VERSION,
    SkillUseEvent,
    skill_use_log_path,
)

_MAJOR_SECTION_RULE = "\u2500" * 50
HISTORICAL_Q_SUFFIX = "--q"


@pytest.fixture(autouse=True)
def _setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    memory_reads_module._memory_reads_cache.clear()
    memory_reads_module._memory_reads_context_cache.clear()
    memory_reads_module._memory_reads_snapshot_cache.clear()
    artifact_reads_module._artifact_reads_cache.clear()
    artifact_reads_module._artifact_reads_context_cache.clear()
    artifact_reads_module._artifact_reads_snapshot_cache.clear()
    opened_workspaces_module._opened_workspaces_cache.clear()
    opened_workspaces_module._opened_workspaces_context_cache.clear()
    skill_uses_module._skill_uses_cache.clear()
    skill_uses_module._skill_uses_context_cache.clear()
    skill_uses_module._skill_uses_snapshot_cache.clear()
    sase_home = tmp_path / "sase-home"
    sase_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: sase_home))
    monkeypatch.setattr(
        memory_reads_module,
        "project_memory_name",
        lambda _root: "header-test",
    )
    monkeypatch.setattr(
        artifact_reads_module,
        "project_memory_name",
        lambda _root: "header-test",
    )
    monkeypatch.setattr(
        skill_uses_module,
        "project_memory_name",
        lambda _root: "header-test",
    )
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )
    yield sase_home
    memory_reads_module._memory_reads_cache.clear()
    memory_reads_module._memory_reads_context_cache.clear()
    memory_reads_module._memory_reads_snapshot_cache.clear()
    artifact_reads_module._artifact_reads_cache.clear()
    artifact_reads_module._artifact_reads_context_cache.clear()
    artifact_reads_module._artifact_reads_snapshot_cache.clear()
    opened_workspaces_module._opened_workspaces_cache.clear()
    opened_workspaces_module._opened_workspaces_context_cache.clear()
    skill_uses_module._skill_uses_cache.clear()
    skill_uses_module._skill_uses_context_cache.clear()
    skill_uses_module._skill_uses_snapshot_cache.clear()


def _assert_dim_divider_before(header: Text, section: str) -> None:
    plain = header.plain
    section_start = plain.index(section)
    rule_start = plain.rfind(_MAJOR_SECTION_RULE, 0, section_start)
    assert rule_start != -1
    assert plain[rule_start - 1 : section_start] == (f"\n{_MAJOR_SECTION_RULE}\n\n")
    rule_end = rule_start + len(_MAJOR_SECTION_RULE)
    assert any(
        span.start <= rule_start and span.end >= rule_end and str(span.style) == "dim"
        for span in header.spans
    )


def _make_agent(
    *,
    artifacts_dir: Path,
    workspace_dir: Path,
    agent_name: str = "alpha",
    raw_suffix: str = "20260524-142200",
    role_suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="header-test",
        project_file="/tmp/header-test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 24, 14, 22, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_dir=str(workspace_dir),
        artifacts_dir=str(artifacts_dir),
        role_suffix=role_suffix,
    )


def _write_events(events: list[MemoryReadEvent]) -> None:
    path = memory_read_log_path("header-test")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for event in events:
            json.dump(asdict(event), out, sort_keys=True)
            out.write("\n")


def _write_skill_events(events: list[SkillUseEvent]) -> None:
    path = skill_use_log_path("header-test")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for event in events:
            json.dump(asdict(event), out, sort_keys=True)
            out.write("\n")


def _write_opened_workspaces(
    artifacts_dir: Path,
    records: list[dict[str, str]],
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / OPENED_LINKED_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 2,
                "linked_repos": records,
            }
        ),
        encoding="utf-8",
    )


def _event(
    *,
    canonical_path: str,
    timestamp: str,
    artifacts_dir: str,
    reason: str = "audit reason",
) -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id=canonical_path + timestamp,
        timestamp=timestamp,
        project="header-test",
        cwd="/tmp/header-test",
        canonical_path=canonical_path,
        resolved_path=f"/tmp/header-test/memory/{canonical_path}",
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=artifacts_dir,
        reason=reason,
        byte_count=64,
        frontmatter_stripped=False,
    )


def _skill_event(
    *,
    skill_name: str,
    timestamp: str,
    artifacts_dir: str,
    reason: str = "skill reason",
) -> SkillUseEvent:
    return SkillUseEvent(
        schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
        id=skill_name + timestamp,
        timestamp=timestamp,
        project="header-test",
        cwd="/tmp/header-test",
        skill_name=skill_name,
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=artifacts_dir,
        reason=reason,
        runtime="codex",
    )


def _tool_entry(**overrides: object) -> ToolCallEntry:
    kwargs = {
        "recorded_at": "2026-07-03T14:00:00+00:00",
        "runtime": "codex",
        "event": "ToolUse",
        "status": "success",
        "tool_name": "Bash",
        "tool_use_id": "call_1",
        "duration_ms": 30_000,
        "tool_input_summary": {"command": "just test"},
        "tool_response_summary": {"exit_code": 0},
    }
    kwargs.update(overrides)
    return ToolCallEntry(**kwargs)  # type: ignore[arg-type]


def _slow_source(*entries: ToolCallEntry) -> SlowToolSource:
    return SlowToolSource(
        label=None,
        entries=tuple(entries),
        agent_is_active=False,
        end_reference=None,
        palette_index=0,
    )


def test_header_renders_workflow_variables_before_agent_context(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_events(
        [
            _event(
                canonical_path="generated_skills.md",
                timestamp="2026-05-24T14:22:08+00:00",
                artifacts_dir=str(artifacts_dir),
                reason="needed commit hook contract for runtime parity refactor",
            ),
        ]
    )

    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)
    agent.step_output = {"meta_foo": "bar"}

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))
    plain = header.plain

    assert "SASE CONTEXT\n" in plain
    assert "▸ MEMORY · 1 read · 1 file\n" in plain
    assert "▸ SKILLS" not in plain
    assert "▸ WORKSPACES" not in plain
    assert "WORKFLOW VARIABLES\n" in plain
    assert "generated_skills.md" in plain
    assert "↳ needed commit hook contract for runtime parity refactor" in plain
    assert "none recorded" not in plain
    _assert_dim_divider_before(header, "SASE CONTEXT\n")
    _assert_dim_divider_before(header, "WORKFLOW VARIABLES\n")
    assert plain.index("WORKFLOW VARIABLES\n") < plain.index("SASE CONTEXT\n")


def test_header_renders_skill_uses_without_memory_reads(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_skill_events(
        [
            _skill_event(
                skill_name="sase_plan",
                timestamp="2026-05-24T14:23:08+00:00",
                artifacts_dir=str(artifacts_dir),
                reason="needed an implementation plan",
            ),
        ]
    )

    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))
    plain = header.plain

    assert "SASE CONTEXT\n" in plain
    assert "▸ SKILLS · 1 use · 1 skill\n" in plain
    assert "sase_plan" in plain
    assert "↳ needed an implementation plan" in plain
    assert "▸ MEMORY" not in plain
    assert "none recorded" not in plain


def test_header_renders_opened_workspaces_without_other_context(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_opened_workspaces(
        artifacts_dir,
        [
            {
                "name": "sase-core",
                "workspace_dir": "/tmp/workspaces/sase-core_13",
                "reason": "inspect core backend boundary",
                "opened_at": "2026-05-24T14:24:08+00:00",
            }
        ],
    )

    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))
    plain = header.plain

    assert "SASE CONTEXT\n" in plain
    assert "▸ WORKSPACES · 1 open · 1 repo\n" in plain
    assert "▣ sase-core" in plain
    assert "→ /tmp/workspaces/sase-core_13" in plain
    assert "↳ inspect core backend boundary" in plain
    assert "▸ MEMORY" not in plain
    assert "▸ SKILLS" not in plain


def test_cheap_header_omits_agent_context(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_events(
        [
            _event(
                canonical_path="skill.md",
                timestamp="2026-05-24T14:22:08+00:00",
                artifacts_dir=str(artifacts_dir),
            )
        ]
    )

    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)
    header, _ = build_header_text(agent, cheap=True)

    assert "SASE CONTEXT" not in header.plain
    assert "AGENT CONTEXT" not in header.plain
    assert "▸ MEMORY" not in header.plain
    assert "▸ SKILLS" not in header.plain
    assert "▸ WORKSPACES" not in header.plain


def test_full_header_renders_slow_tool_calls_before_error(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)
    agent.error_message = "boom"
    summary = DetailHeaderSummary(slow_tool_sources=(_slow_source(_tool_entry()),))

    header, _ = build_header_text(agent, summary=summary)
    plain = header.plain

    assert "SLOW TOOL CALLS · ≥20s · 1 call" in plain
    assert "✔ Bash" in plain
    assert "just test" in plain
    assert plain.index("SLOW TOOL CALLS") < plain.index("ERROR")
    _assert_dim_divider_before(header, "▸ SLOW TOOL CALLS")


def test_full_header_uses_custom_slow_tool_threshold(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)
    summary = DetailHeaderSummary(
        slow_tool_sources=(
            _slow_source(
                _tool_entry(
                    duration_ms=29_999,
                    tool_input_summary={"command": "under threshold"},
                ),
                _tool_entry(
                    duration_ms=30_000,
                    tool_input_summary={"command": "exact threshold"},
                ),
            ),
        )
    )

    header, _ = build_header_text(
        agent,
        summary=summary,
        slow_tool_call_threshold_ms=30_000,
    )
    plain = header.plain

    assert "SLOW TOOL CALLS · ≥30s · 1 call" in plain
    assert "exact threshold" in plain
    assert "under threshold" not in plain


def test_cheap_header_omits_slow_tool_calls_even_with_summary(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)
    summary = DetailHeaderSummary(slow_tool_sources=(_slow_source(_tool_entry()),))

    header, _ = build_header_text(agent, cheap=True, summary=summary)

    assert "SLOW TOOL CALLS" not in header.plain


def test_no_events_omits_agent_context_section(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "SASE CONTEXT" not in header.plain
    assert "AGENT CONTEXT" not in header.plain


def test_family_header_renders_followup_role_attribution(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    plan_dir = tmp_path / "artifacts" / "plan"
    coder_dir = tmp_path / "artifacts" / "coder"
    q_dir = tmp_path / "artifacts" / "q"
    for directory in (plan_dir, coder_dir, q_dir):
        directory.mkdir(parents=True)

    _write_events(
        [
            _event(
                canonical_path="cli_rules.md",
                timestamp="2026-05-24T14:22:08+00:00",
                artifacts_dir=str(plan_dir),
                reason="planner reviewed CLI rules",
            ),
            _event(
                canonical_path="tui_perf.md",
                timestamp="2026-05-24T14:30:00+00:00",
                artifacts_dir=str(coder_dir),
                reason="coder checked perf budget",
            ),
        ]
    )
    _write_skill_events(
        [
            _skill_event(
                skill_name="sase_questions",
                timestamp="2026-05-24T14:25:00+00:00",
                artifacts_dir=str(q_dir),
                reason="needed answers before coding",
            ),
        ]
    )

    root = _make_agent(
        artifacts_dir=plan_dir,
        workspace_dir=workspace_dir,
        agent_name="alpha--plan",
        raw_suffix="20260524-142200-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = _make_agent(
        artifacts_dir=coder_dir,
        workspace_dir=workspace_dir,
        agent_name="alpha--code",
        raw_suffix="20260524-142200-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    question = _make_agent(
        artifacts_dir=q_dir,
        workspace_dir=workspace_dir,
        agent_name="alpha--q",
        raw_suffix="20260524-142200-q",
        role_suffix=HISTORICAL_Q_SUFFIX,
    )
    root.followup_agents = [coder, question]

    header, _ = build_header_text(root, summary=build_detail_header_summary(root))
    plain = header.plain

    assert "SASE CONTEXT\n" in plain
    # Memory lane: 2 reads from 2 producers, newest (coder) first.
    assert "▸ MEMORY · 2 reads · 2 files · 2 agents\n" in plain
    assert "coder  ◇ tui_perf.md" in plain
    assert "plan   ◇ cli_rules.md" in plain
    # Skills lane: the question follow-up's audited use is attributed to `q`.
    assert "▸ SKILLS · 1 use · 1 skill\n" in plain
    assert "q      ◆ sase_questions" in plain
