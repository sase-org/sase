"""Shared builders for clan display tests."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models._agent_clan_sections import (
    CLAN_DISK_SECTIONS,
    ClanContextEntry,
    ClanContextLane,
    ClanDiskMemberSnapshot,
    ClanDiskSnapshot,
    ClanSectionSnapshot,
    ClanSlowToolEntry,
    ClanTextEntry,
    aggregate_clan_in_memory,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tools._entry import ToolCallEntry
from sase.ace.tui.tools.slow import SlowToolCall

_GENERATION = "20260717120000"
_SASE_BEADS_SKILL = "sase" + "_beads"


def style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


def make_clan_agent(
    name: str,
    *,
    status: str,
    start: datetime,
    stop: datetime | None = None,
    model: str | None = "gpt-5",
    parent_timestamp: str | None = None,
    family: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/demo.sase",
        status=status,
        start_time=start,
        run_start_time=start,
        stop_time=stop,
        raw_suffix=start.strftime("%Y%m%d%H%M%S") + name,
        agent_name=name,
        parent_timestamp=parent_timestamp,
        agent_family=family,
        agent_clan="research",
        agent_clan_generation=_GENERATION,
        model=model,
    )


def rich_clan_snapshot() -> tuple[Agent, ClanSectionSnapshot]:
    member = make_clan_agent(
        "research.one",
        status="FAILED",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 3, 0),
    )
    member.activity = "reviewing patch"
    member.waiting_for = ["research.peer"]
    member.workspace_num = 7
    member.epic_bead_id = "sase-demo"
    member.plan_path = "/tmp/demo-plan.md"
    member.error_message = "Build failed\nSecond error detail"
    member.error_traceback = "Traceback line one\nValueError: broken"
    member.output_variables = {
        "report": {
            "findings": [
                {
                    "file": "src/a.py",
                    "severity": "high",
                }
            ],
            "passed": True,
            "ratio": 2.5,
            "summary": "summary line",
        }
    }
    member.step_output = {
        "meta_release_notes": "release summary\nrelease detail",
    }
    container = project_clan_tree([member])[0]
    in_memory = aggregate_clan_in_memory(container)
    identity = member.identity
    reply = ClanTextEntry(
        member_identity=identity,
        member_label=".one",
        kind="AGENT REPLY",
        preview="Reply summary",
        body="Reply summary\nReply full detail",
    )
    prompt = ClanTextEntry(
        member_identity=identity,
        member_label=".one",
        kind="AGENT XPROMPT",
        preview="#review segment",
        body="#review segment\nPrompt full detail",
    )
    context_lanes = (
        ClanContextLane(
            label="BEAD",
            entries=(
                ClanContextEntry(
                    key="sase-demo",
                    label="sase-demo · render clan summary",
                    member_labels=(".one",),
                ),
            ),
        ),
        ClanContextLane(
            label="SKILLS",
            entries=(
                ClanContextEntry(
                    key=_SASE_BEADS_SKILL,
                    label=_SASE_BEADS_SKILL,
                    member_labels=(".one",),
                    count=2,
                ),
            ),
        ),
    )
    tool_entry = ToolCallEntry(
        recorded_at="2026-07-17T12:00:00Z",
        runtime="codex",
        event="ToolCall",
        status="completed",
        tool_name="Bash",
        duration_ms=125_000,
        tool_input_summary={"command": "just check"},
    )
    slow_tool = ClanSlowToolEntry(
        member_identity=identity,
        member_label=".one",
        source_label="attempt 1",
        call=SlowToolCall(
            entry=tool_entry,
            started_at=datetime.fromisoformat("2026-07-17T12:00:00+00:00"),
            effective_duration_ms=125_000,
        ),
    )
    disk_member = ClanDiskMemberSnapshot(
        member_identity=identity,
        member_label=".one",
        loaded_sections=CLAN_DISK_SECTIONS,
        replies=(reply,),
        prompts=(prompt,),
    )
    disk = ClanDiskSnapshot(
        loaded_sections=CLAN_DISK_SECTIONS,
        members=(disk_member,),
        replies=(reply,),
        prompts=(prompt,),
        context_lanes=context_lanes,
        slow_tool_calls=(slow_tool,),
    )
    return container, ClanSectionSnapshot(in_memory=in_memory, disk=disk)
