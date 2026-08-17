"""Disk-backed clan member loading and aggregation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.glossary_reads import GlossaryReadDisplayEvent
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.models._agent_clan_sections import (
    ClanDiskMemberSnapshot,
    aggregate_clan_in_memory,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_associated_plan import PhaseBeadSummary
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.tools import SlowToolSource, ToolCallEntry
from sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation import (
    _aggregate_clan_context_lanes,
    _aggregate_clan_slow_tool_calls,
    _ClanDiskContentCache,
    _load_clan_disk_member_snapshot,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.glossary.read_log import GLOSSARY_READ_LOG_SCHEMA_VERSION, GlossaryReadEvent
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from sase.skills.use_log import SKILL_USE_LOG_SCHEMA_VERSION, SkillUseEvent

_GENERATION = "20260718100000"
_SASE_BEADS_SKILL = "sase" + "_beads"


def _agent(name: str, *, minute: int = 0, **overrides: object) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/demo.sase",
        "status": "DONE",
        "start_time": datetime(2026, 7, 18, 10, minute),
        "stop_time": datetime(2026, 7, 18, 10, minute + 1),
        "raw_suffix": f"row-{minute}-{name}",
        "agent_name": name,
        "agent_clan": "research",
        "agent_clan_generation": _GENERATION,
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _member_snapshot(
    member: Agent,
    label: str,
    *,
    context: DetailHeaderSummary | None = None,
    sources: tuple[SlowToolSource, ...] | None = None,
) -> ClanDiskMemberSnapshot:
    return ClanDiskMemberSnapshot(
        member_identity=member.identity,
        member_label=label,
        loaded_sections=frozenset({"context", "slow-tool-calls"}),
        context=context,
        slow_tool_sources=sources,
    )


def test_member_cache_hits_same_mtime_token_and_expands_section_union(
    monkeypatch: Any,
) -> None:
    member = _agent("research.one")
    cache = _ClanDiskContentCache()
    calls: list[frozenset[str]] = []
    token = [1]
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation."
        "_clan_member_source_token",
        lambda _member: ("stable", token[0]),
    )

    def loader(
        member_arg: Agent,
        label: str,
        sections: frozenset[Any],
    ) -> ClanDiskMemberSnapshot:
        calls.append(frozenset(sections))
        return ClanDiskMemberSnapshot(
            member_identity=member_arg.identity,
            member_label=label,
            loaded_sections=sections,
        )

    first = cache.load(
        member,
        member_label=".one",
        sections=frozenset({"replies"}),
        loader=loader,
    )
    second = cache.load(
        member,
        member_label=".one",
        sections=frozenset({"replies"}),
        loader=loader,
    )
    expanded = cache.load(
        member,
        member_label=".one",
        sections=frozenset({"context"}),
        loader=loader,
    )
    token[0] = 2
    invalidated = cache.load(
        member,
        member_label=".one",
        sections=frozenset({"replies"}),
        loader=loader,
    )

    assert first is second
    assert calls == [
        frozenset({"replies"}),
        frozenset({"replies", "context"}),
        frozenset({"replies"}),
    ]
    assert expanded.loaded_sections == frozenset({"replies", "context"})
    assert invalidated is not expanded


def test_member_loader_reuses_reply_and_prompt_precedence(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text(
        "\n#research first segment\n",
        encoding="utf-8",
    )
    (artifacts / "01_prompt.md").write_text(
        "\nExpanded prompt body\n",
        encoding="utf-8",
    )
    response = artifacts / "response.md"
    response.write_text("\nFinal member conclusion\nsecond line\n", encoding="utf-8")
    member = _agent(
        "research.one",
        artifacts_dir=str(artifacts),
        response_path=str(response),
    )

    snapshot = _load_clan_disk_member_snapshot(
        member,
        ".one",
        frozenset({"replies", "prompts"}),
    )

    assert [(entry.kind, entry.preview) for entry in snapshot.replies] == [
        ("AGENT REPLY", "Final member conclusion")
    ]
    assert [(entry.kind, entry.preview) for entry in snapshot.prompts] == [
        ("AGENT XPROMPT", "#research first segment"),
        ("AGENT PROMPT", "Expanded prompt body"),
    ]


def test_context_lanes_dedupe_in_declared_order_and_count_uses() -> None:
    first = _agent(
        "research.first",
        epic_bead_id="sase-6u",
        plan_path="/tmp/plan.md",
        workspace_num=4,
    )
    second = _agent(
        "research.second",
        minute=2,
        epic_bead_id="sase-6u",
        plan_path="/tmp/plan.md",
        workspace_num=4,
    )
    container = project_clan_tree([second, first])[0]
    in_memory = aggregate_clan_in_memory(container)
    memory_event = MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id="read-1",
        timestamp="2026-07-18T10:00:00+00:00",
        project="demo",
        cwd="/tmp",
        canonical_path="tui_perf.md",
        resolved_path="/tmp/tui_perf.md",
        agent_name="research.first",
        agent_source="test",
        artifacts_dir="/tmp/artifacts",
        reason="test",
        byte_count=10,
        frontmatter_stripped=False,
    )
    skill_event = SkillUseEvent(
        schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
        id="skill-1",
        timestamp="2026-07-18T10:00:00+00:00",
        project="demo",
        cwd="/tmp",
        skill_name=_SASE_BEADS_SKILL,
        agent_name="research.first",
        agent_source="test",
        artifacts_dir="/tmp/artifacts",
        reason="test",
        runtime="codex",
    )
    glossary_event = GlossaryReadEvent(
        schema_version=GLOSSARY_READ_LOG_SCHEMA_VERSION,
        id="glossary-1",
        timestamp="2026-07-18T10:00:00+00:00",
        project="demo",
        cwd="/tmp",
        agent_name="research.first",
        agent_source="test",
        artifacts_dir="/tmp/artifacts",
        reason="test",
        terms=("Agent Hood",),
        related_terms=(),
        depth_limit=None,
        definition_bytes=10,
        source_path="/tmp/sase.yml",
    )

    def summary(suffix: str) -> DetailHeaderSummary:
        return DetailHeaderSummary(
            artifact_file_paths=[
                ArtifactFilePath(
                    display_path="report.md",
                    actual_path="/tmp/report.md",
                )
            ],
            memory_reads=(MemoryReadDisplayEvent(event=memory_event),),
            glossary_reads=(GlossaryReadDisplayEvent(event=glossary_event),),
            skill_uses=(SkillUseDisplayEvent(event=skill_event),),
            opened_workspaces=(
                OpenedWorkspaceDisplayEvent(
                    name="sase-core",
                    workspace_dir="/tmp/sase-core",
                    reason=suffix,
                    opened_at="2026-07-18T10:00:00+00:00",
                ),
            ),
        )

    members = (
        _member_snapshot(first, ".first", context=summary("first")),
        _member_snapshot(second, ".second", context=summary("second")),
    )
    lanes = _aggregate_clan_context_lanes(in_memory, members)

    assert [lane.label for lane in lanes] == [
        "PLAN",
        "BEAD",
        "ARTIFACTS",
        "MEMORY",
        "GLOSSARY",
        "SKILLS",
        "WORKSPACES",
    ]
    by_label = {lane.label: lane for lane in lanes}
    assert len(by_label["ARTIFACTS"].entries) == 1
    assert by_label["ARTIFACTS"].entries[0].member_labels == (
        ".first",
        ".second",
    )
    assert by_label["MEMORY"].entries[0].count == 2
    assert by_label["GLOSSARY"].entries[0].label == "Agent Hood"
    assert by_label["GLOSSARY"].entries[0].count == 2
    assert by_label["SKILLS"].entries[0].label == _SASE_BEADS_SKILL
    assert by_label["SKILLS"].entries[0].count == 2
    # The in-memory workspace number and disk-backed opened repo remain
    # distinct, while duplicate opened repo paths collapse across members.
    assert [entry.label for entry in by_label["WORKSPACES"].entries] == [
        "workspace 4",
        "sase-core",
    ]


def test_phase_bead_clan_labels_prefer_title_then_description_then_id() -> None:
    titled = _agent("research.titled")
    described = _agent("research.described", minute=2)
    bare = _agent("research.bare", minute=4)
    container = project_clan_tree([titled, described, bare])[0]
    in_memory = aggregate_clan_in_memory(container)

    def phase_summary(
        bead_id: str,
        *,
        phase_title: str | None,
        description: str | None,
    ) -> DetailHeaderSummary:
        return DetailHeaderSummary(
            phase_bead=PhaseBeadSummary(
                id=bead_id,
                phase_title=phase_title,
                description=description,
                actual_plan_path=None,
                display_plan_path=None,
                plan_exists=False,
                plan_readable=False,
                epic_title=None,
                size=None,
            )
        )

    members = (
        _member_snapshot(
            titled,
            ".titled",
            context=phase_summary(
                "sase-title.1",
                phase_title="Preferred phase title\nignored continuation",
                description="Description must not win.",
            ),
        ),
        _member_snapshot(
            described,
            ".described",
            context=phase_summary(
                "sase-description.1",
                phase_title=None,
                description="\nFallback description\nignored continuation",
            ),
        ),
        _member_snapshot(
            bare,
            ".bare",
            context=phase_summary(
                "sase-bare.1",
                phase_title=None,
                description=None,
            ),
        ),
    )

    lanes = _aggregate_clan_context_lanes(in_memory, members)

    bead_lane = next(lane for lane in lanes if lane.label == "BEAD")
    assert [entry.label for entry in bead_lane.entries] == [
        "sase-title.1 · Preferred phase title",
        "sase-description.1 · Fallback description",
        "sase-bare.1",
    ]


def test_slow_calls_are_deduped_and_ranked_by_duration() -> None:
    first = _agent("research.first")
    second = _agent("research.second", minute=2)
    shorter = ToolCallEntry(
        recorded_at="2026-07-18T10:00:00+00:00",
        runtime="codex",
        event="PostToolUse",
        status="success",
        tool_name="Read",
        tool_use_id="call-1",
        duration_ms=25_000,
        artifact_dir="/tmp/first",
        line_number=1,
    )
    longer = ToolCallEntry(
        recorded_at="2026-07-18T10:01:00+00:00",
        runtime="codex",
        event="PostToolUse",
        status="success",
        tool_name="Bash",
        tool_use_id="call-2",
        duration_ms=40_000,
        artifact_dir="/tmp/first",
        line_number=2,
    )
    source = SlowToolSource(
        label=None,
        entries=(shorter, longer),
        agent_is_active=False,
        end_reference=None,
        palette_index=0,
    )
    duplicate_source = SlowToolSource(
        label=None,
        entries=(shorter,),
        agent_is_active=False,
        end_reference=None,
        palette_index=0,
    )
    members = (
        _member_snapshot(first, ".first", sources=(source,)),
        _member_snapshot(second, ".second", sources=(duplicate_source,)),
    )

    calls = _aggregate_clan_slow_tool_calls(
        members,
        now=datetime(2026, 7, 18, 10, 2, tzinfo=UTC),
        threshold_ms=20_000,
    )

    assert [entry.call.entry.tool_use_id for entry in calls] == ["call-2", "call-1"]
    assert [entry.member_label for entry in calls] == [".first", ".first"]
