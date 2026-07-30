"""Pure aggregation tests for clan metadata sections."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_clan_sections import (
    ClanVariableEntry,
    aggregate_clan_in_memory,
    first_meaningful_line,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType

_GENERATION = "20260718090000"


def _agent(
    name: str,
    *,
    minute: int,
    status: str = "DONE",
    parent_timestamp: str | None = None,
    family: str | None = None,
    **overrides: object,
) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/demo.sase",
        "status": status,
        "start_time": datetime(2026, 7, 18, 9, minute),
        "raw_suffix": f"row-{minute}",
        "agent_name": name,
        "agent_clan": "research",
        "agent_clan_generation": _GENERATION,
        "parent_timestamp": parent_timestamp,
        "agent_family": family,
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def test_in_memory_aggregate_includes_family_rows_and_all_section_facts() -> None:
    family = "research.writer"
    planner = _agent(
        "research.writer--plan",
        minute=0,
        status="FAILED",
        family=family,
        error_message="\n  Planning failed first\nextra detail",
        error_traceback="Traceback: boom",
        output_variables={"z_path": "/z", "a_path": "/a"},
        activity="checking plan",
        waiting_for=["research.reader"],
        retry_count=1,
        max_retries=3,
        retry_status="running_retry",
        epic_bead_id="sase-6u",
        plan_path="/tmp/plan.md",
        workspace_num=7,
    )
    coder = _agent(
        "research.writer--code",
        minute=1,
        family=family,
        parent_timestamp=planner.raw_suffix,
        output_variables={
            "result": {
                "passed": True,
                "files": ["a.py", "b.py"],
            }
        },
        step_output={
            "meta_result": "ok",
            "meta_workspace": 7,
            "meta_commit_message": "ignored",
        },
        phase_bead_id="sase-6u.2",
        sdd_plan_path="/tmp/plan.md",
    )
    reader = _agent(
        "research.reader",
        minute=2,
        status="FAILED",
        error_message=None,
        step_output={"meta_report_path": "/tmp/report.md"},
        workspace_num=9,
    )
    planner.runtime_children = [coder]
    container = project_clan_tree([reader, coder, planner])[0]

    snapshot = aggregate_clan_in_memory(container)

    assert [member.label for member in snapshot.members] == [
        ".writer--plan",
        ".writer--code",
        ".reader",
    ]
    assert [member.family_depth for member in snapshot.members] == [0, 1, 0]
    assert snapshot.members[0].activity == "checking plan"
    assert snapshot.members[0].waiting == ("for research.reader",)
    assert snapshot.members[0].retry == ("1/3", "running retry")

    assert [(entry.member_label, entry.preview) for entry in snapshot.errors] == [
        (".writer--plan", "Planning failed first"),
        (".reader", "Runner failed without error details."),
    ]
    assert snapshot.errors[0].traceback == "Traceback: boom"
    assert [
        (entry.member_label, entry.name) for entry in snapshot.output_variables
    ] == [
        (".writer--plan", "a_path"),
        (".writer--plan", "z_path"),
        (".writer--code", "result"),
    ]
    assert snapshot.output_variables[2].value == {
        "passed": True,
        "files": ["a.py", "b.py"],
    }
    assert [
        (entry.member_label, entry.name, entry.value)
        for entry in snapshot.workflow_variables
    ] == [
        (".writer--code", "Result", "ok"),
        (".reader", "Report Path", "/tmp/report.md"),
    ]
    assert snapshot.bead_ids == ("sase-6u", "sase-6u.2")
    assert snapshot.plan_paths == ("/tmp/plan.md",)
    assert snapshot.workspace_numbers == (7, 9)
    assert snapshot.heading_counts.members == 3
    assert snapshot.heading_counts.errors == 2
    assert snapshot.heading_counts.output_variables == 3
    assert snapshot.heading_counts.workflow_variables == 2
    assert snapshot.heading_counts.for_section("prompts") is None


def test_first_meaningful_line_normalizes_and_enforces_exact_bound() -> None:
    assert first_meaningful_line("\n\t hello   clan \nsecond") == "hello clan"
    assert first_meaningful_line("abcdefgh", max_chars=5) == "abcd…"
    assert len(first_meaningful_line("abcdefgh", max_chars=5)) == 5
    assert first_meaningful_line("\n \t", max_chars=5) == ""
    assert first_meaningful_line("abc", max_chars=0) == ""


def test_structured_variable_entries_preserve_values_and_hash_canonically() -> None:
    identity = (AgentType.RUNNING, "demo", "suffix")
    left = ClanVariableEntry(
        member_identity=identity,
        member_label=".demo",
        name="report",
        value={"passed": True, "files": ["a.py", "b.py"]},
    )
    right = ClanVariableEntry(
        member_identity=identity,
        member_label=".demo",
        name="report",
        value={"files": ["a.py", "b.py"], "passed": True},
    )

    assert left == right
    assert hash(left) == hash(right)
