from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from sase.integrations.editor_helpers import handle_editor_helper_bridge
from sase.main.parser import create_parser


def test_parser_accepts_editor_helper_bridge_agent_catalog() -> None:
    args = create_parser().parse_args(["editor", "helper-bridge", "agent-catalog"])

    assert args.command == "editor"
    assert args.editor_subcommand == "helper-bridge"
    assert args.editor_helper_bridge_subcommand == "agent-catalog"


def test_editor_helper_bridge_agent_catalog_is_fresh_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.running_listing import RunningAgentInfo

    calls = 0

    def list_agents() -> list[RunningAgentInfo]:
        nonlocal calls
        calls += 1
        return [
            RunningAgentInfo(
                name="planner",
                project="sase",
                pid=1,
                model=None,
                provider=None,
                workspace_num=14,
                duration="1m",
                approve=False,
                status="RUNNING",
            ),
            RunningAgentInfo(
                name="planner",
                project="sase-old",
                pid=None,
                model=None,
                provider=None,
                workspace_num=None,
                duration="2m",
                approve=False,
                status="DONE",
            ),
            RunningAgentInfo(
                name="coder",
                project="core",
                pid=None,
                model=None,
                provider=None,
                workspace_num=None,
                duration="2m",
                approve=False,
                status="DONE",
            ),
        ]

    monkeypatch.setattr("sase.agent.running_listing.list_all_agents", list_agents)

    for _ in range(2):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = handle_editor_helper_bridge(
            argparse.Namespace(editor_helper_bridge_subcommand="agent-catalog"),
            stdin=io.StringIO(json.dumps({"schema_version": 1})),
            stdout=stdout,
            stderr=stderr,
        )

        assert code == 0
        assert stderr.getvalue() == ""
        assert json.loads(stdout.getvalue())["entries"] == [
            {
                "name": "planner",
                "status": "RUNNING",
                "project": "sase",
                "kind": "agent",
                "member_count": 1,
                "detail": "RUNNING · sase",
            },
            {
                "name": "coder",
                "status": "DONE",
                "project": "core",
                "kind": "agent",
                "member_count": 1,
                "detail": "DONE · core",
            },
        ]

    assert calls == 2


def test_editor_helper_bridge_agent_catalog_uses_monitor_member_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.running_listing import RunningAgentInfo

    monkeypatch.setattr(
        "sase.agent.running_listing.list_all_agents",
        lambda: [
            RunningAgentInfo(
                name="alpha--0",
                project="sase",
                pid=None,
                model=None,
                provider=None,
                workspace_num=None,
                duration="2m",
                approve=False,
                status="DONE",
                agent_family="alpha",
                agent_family_role="root",
                role_suffix="--0",
                monitor_id="m123",
            ),
            RunningAgentInfo(
                name="alpha--mon",
                project="sase",
                pid=None,
                model=None,
                provider=None,
                workspace_num=None,
                duration="2m",
                approve=False,
                status="MONITORED",
                agent_family="alpha",
                agent_family_role="monitor",
                role_suffix="--mon",
                monitor_id="m123",
            ),
        ],
    )

    stdout = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="agent-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 0
    entries = json.loads(stdout.getvalue())["entries"]
    assert [(entry["kind"], entry["name"]) for entry in entries] == [
        ("agent", "alpha--0"),
        ("monitor", "alpha--mon"),
    ]


def test_editor_helper_bridge_agent_catalog_derives_groups_from_one_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.running_listing import RunningAgentInfo, _RunningAgentListing
    from sase.core.agent_scan_wire import (
        AGENT_SCAN_WIRE_SCHEMA_VERSION,
        AgentArtifactRecordWire,
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
        AgentClanContextWire,
        AgentMetaWire,
        DoneMarkerWire,
    )

    def record(
        timestamp: str,
        name: str | None,
        **meta_values: object,
    ) -> AgentArtifactRecordWire:
        artifact_dir = f"/tmp/artifacts/{timestamp}"
        return AgentArtifactRecordWire(
            project_name="sase",
            project_dir="/tmp/sase",
            project_file="/tmp/sase/sase.sase",
            workflow_dir_name="ace-run",
            artifact_dir=artifact_dir,
            timestamp=timestamp,
            agent_meta=(
                AgentMetaWire(name=name, cl_name="change", **meta_values)
                if name is not None
                else None
            ),
            done=DoneMarkerWire(outcome="completed", cl_name="change"),
            has_done_marker=True,
        )

    records = [
        record(
            "20260719010101",
            "old.one",
            agent_clan="squad",
            agent_clan_generation="g1",
        ),
        record(
            "20260719020101",
            "squad.alpha",
            agent_clan="squad",
            agent_clan_generation="g2",
        ),
        record(
            "20260719020102",
            "squad.beta",
            agent_clan="squad",
            agent_clan_generation="g2",
        ),
        record(
            "20260719030101",
            "review--plan",
            agent_family="review",
        ),
        record(
            "20260719030102",
            "review--code",
            agent_family="review",
            parent_timestamp="20260719030101",
        ),
        record("20260719040101", "solo", tribe="writers"),
        record("20260719050101", None),
    ]
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=records,
        clan_context=[
            AgentClanContextWire(
                agent_clan="squad",
                agent_clan_generation="g2",
                clan_tribe="builders",
                clan_tribe_source_launch_timestamp="20260719020000",
                clan_tribe_source_identity="/tmp/omitted-declarer",
            )
        ],
    )

    def info(record: AgentArtifactRecordWire, status: str) -> RunningAgentInfo:
        assert record.agent_meta is not None
        return RunningAgentInfo(
            name=record.agent_meta.name,
            project="sase",
            pid=None,
            model=None,
            provider=None,
            workspace_num=None,
            duration="1m",
            approve=False,
            status=status,
            artifacts_dir=record.artifact_dir,
        )

    listing = _RunningAgentListing(
        [
            info(records[1], "QUEUED"),
            info(records[2], "WAITING"),
            info(records[3], "DONE"),
            info(records[4], "RUNNING"),
            info(records[5], "DONE"),
        ],
        artifact_snapshot=snapshot,
    )
    monkeypatch.setattr("sase.agent.running_listing.list_all_agents", lambda: listing)
    monkeypatch.setattr(
        "sase.core.agent_tribe.load_raw_agent_tribes",
        lambda: {("workflow", "change", "20260719020102"): "ops"},
    )

    stdout = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="agent-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 0
    data = json.loads(stdout.getvalue())
    by_target = {(entry["kind"], entry["name"]): entry for entry in data["entries"]}
    assert data["schema_version"] == 1
    assert by_target[("family", "review")]["member_count"] == 2
    assert by_target[("family", "review")]["detail"] == "family · 2 members"
    assert "documentation" not in by_target[("family", "review")]
    assert by_target[("clan", "squad")] == {
        "name": "squad",
        "kind": "clan",
        "member_count": 2,
        "status": "QUEUED",
        "detail": "clan · 2 members · QUEUED",
    }
    assert by_target[("tribe", "@builders")]["detail"] == "tribe · 1 clan"
    assert by_target[("tribe", "@ops")]["detail"] == "tribe · 1 agent"
    assert by_target[("tribe", "@writers")]["detail"] == "tribe · 1 agent"


def test_editor_helper_bridge_agent_catalog_tolerates_group_derivation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.running_listing import RunningAgentInfo, _RunningAgentListing
    from sase.core.agent_scan_wire import (
        AGENT_SCAN_WIRE_SCHEMA_VERSION,
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
    )

    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
    )
    listing = _RunningAgentListing(
        [
            RunningAgentInfo(
                name="planner",
                project="sase",
                pid=None,
                model=None,
                provider=None,
                workspace_num=None,
                duration="1m",
                approve=False,
            )
        ],
        artifact_snapshot=snapshot,
    )
    monkeypatch.setattr("sase.agent.running_listing.list_all_agents", lambda: listing)
    monkeypatch.setattr(
        "sase.integrations._editor_helper_agents._derive_group_entries",
        lambda *_args: (_ for _ in ()).throw(ValueError("legacy metadata")),
    )

    stdout = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="agent-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 0
    entries = json.loads(stdout.getvalue())["entries"]
    assert [(entry["kind"], entry["name"]) for entry in entries] == [
        ("agent", "planner")
    ]


_EPIC_PLAN = """\
---
tier: epic
title: Plan-aware agent-family completion previews
goal: Agent-family completion entries lead with the tale or epic they belong to.
phases:
  - id: preview
    title: Shared family plan-preview value and TUI resolution cache
    depends_on: []
    description: "preview: add the surface-neutral value."
    size: medium
  - id: rows
    title: Prompt-input completion rows and panel subtitle
    depends_on: [preview]
    description: "rows: schedule warmup and render rows."
    size: medium
---
# Plan
"""

_TALE_PLAN = """\
---
tier: tale
title: Complete common words from the middle of a word
goal: Finish a word from an interior fragment.
size: small
---
# Plan
"""


def _scan_record(
    timestamp: str,
    name: str,
    *,
    raw_prompt_snippet: str | None = None,
    archived_plan_path: str | None = None,
    **meta_values: object,
) -> object:
    from sase.core.agent_scan_wire import (
        AgentArtifactRecordWire,
        AgentMetaWire,
        DoneMarkerWire,
        PlanPathMarkerWire,
    )

    return AgentArtifactRecordWire(
        project_name="sase",
        project_dir="/tmp/sase",
        project_file="/tmp/sase/sase.sase",
        workflow_dir_name="ace-run",
        artifact_dir=f"/tmp/artifacts/{timestamp}",
        timestamp=timestamp,
        agent_meta=AgentMetaWire(name=name, **meta_values),
        done=DoneMarkerWire(outcome="completed", plan_path=archived_plan_path),
        plan_path=(
            PlanPathMarkerWire(plan_path=archived_plan_path)
            if archived_plan_path
            else None
        ),
        raw_prompt_snippet=raw_prompt_snippet,
        has_done_marker=True,
    )


def _catalog_by_target(
    monkeypatch: pytest.MonkeyPatch,
    records: list[object],
) -> dict[tuple[str, str], dict[str, object]]:
    from sase.agent.running_listing import _RunningAgentListing
    from sase.core.agent_scan_wire import (
        AGENT_SCAN_WIRE_SCHEMA_VERSION,
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
    )

    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=records,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "sase.agent.running_listing.list_all_agents",
        lambda: _RunningAgentListing([], artifact_snapshot=snapshot),
    )
    monkeypatch.setattr("sase.core.agent_tribe.load_raw_agent_tribes", dict)
    stdout = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="agent-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == 0
    data = json.loads(stdout.getvalue())
    assert data["schema_version"] == 1
    return {(entry["kind"], entry["name"]): entry for entry in data["entries"]}


def _family_record(
    timestamp: str,
    family: str,
    *,
    suffix: str = "--plan",
    parent_timestamp: str | None = None,
    **kwargs: object,
) -> object:
    return _scan_record(
        timestamp,
        f"{family}{suffix}",
        agent_family=family,
        parent_timestamp=parent_timestamp,
        **kwargs,
    )


def test_editor_helper_family_catalog_epic_detail_and_documentation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic = tmp_path / "epic.md"
    epic.write_text(_EPIC_PLAN, encoding="utf-8")
    by_target = _catalog_by_target(
        monkeypatch,
        [_family_record("20260816010101", "previewers", plan_path=str(epic))],
    )

    family = by_target[("family", "previewers")]
    assert family["detail"] == (
        "epic · 2 phases · 2 waves · Plan-aware agent-family completion previews"
    )
    documentation = str(family["documentation"])
    assert documentation.startswith("**Epic** · 2 phases · 2 waves")
    assert "## Plan-aware agent-family completion previews" in documentation
    assert (
        "Agent-family completion entries lead with the tale or epic they belong to."
        in documentation
    )
    assert (
        "- `preview` — Shared family plan-preview value and TUI resolution cache "
        "(medium)" in documentation
    )
    assert documentation.endswith("family · 1 member · DONE")


def test_editor_helper_family_catalog_tale_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tale = tmp_path / "tale.md"
    tale.write_text(_TALE_PLAN, encoding="utf-8")
    by_target = _catalog_by_target(
        monkeypatch,
        [_family_record("20260816010101", "wordsmiths", sdd_plan_path=str(tale))],
    )

    family = by_target[("family", "wordsmiths")]
    assert family["detail"] == (
        "tale · Complete common words from the middle of a word"
    )
    assert str(family["documentation"]).startswith("**Tale**")


def test_editor_helper_family_catalog_phase_and_task_beads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.model import Issue, IssueType, PhaseSize

    issues = {
        "sase-n9": Issue(
            id="sase-n9",
            title="Plan-aware agent-family completion previews",
            issue_type=IssueType.PLAN,
        ),
        "sase-n9.2": Issue(
            id="sase-n9.2",
            title="Prompt-input completion rows and panel subtitle",
            issue_type=IssueType.PHASE,
            parent_id="sase-n9",
            size=PhaseSize.MEDIUM,
        ),
        "sase-t1": Issue(
            id="sase-t1",
            title="Fix the flaky selection-health test",
            issue_type=IssueType.TASK,
            size=PhaseSize.SMALL,
        ),
    }
    monkeypatch.setattr(
        "sase.integrations._editor_helper_agent_plans.lookup_bead_issue",
        lambda bead_id, **_kwargs: issues.get(bead_id),
    )
    by_target = _catalog_by_target(
        monkeypatch,
        [
            _family_record(
                "20260816010101",
                "rows",
                phase_bead_id="sase-n9.2",
                epic_bead_id="sase-n9",
            ),
            _family_record("20260816020202", "fixers", phase_bead_id="sase-t1"),
        ],
    )

    phase = by_target[("family", "rows")]
    assert phase["detail"] == (
        "phase · Prompt-input completion rows and panel subtitle"
    )
    assert "_Part of Plan-aware agent-family completion previews_" in str(
        phase["documentation"]
    )
    assert by_target[("family", "fixers")]["detail"] == (
        "task · Fix the flaky selection-health test"
    )


def test_editor_helper_family_catalog_snippet_fallback_and_directive_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    by_target = _catalog_by_target(
        monkeypatch,
        [
            _family_record(
                "20260816010101",
                "snippers",
                raw_prompt_snippet=(
                    "---\nname: x\n---\n%wait:foo\n#gh:sase Fix the flaky "
                    "selection-health test"
                ),
            ),
            _family_record(
                "20260816020202",
                "directives",
                raw_prompt_snippet="---\nname: x\n---\n%wait:foo\n#gh:sase\n",
            ),
        ],
    )

    assert by_target[("family", "snippers")]["detail"] == (
        "family · 1 member · Fix the flaky selection-health test"
    )
    assert "documentation" not in by_target[("family", "snippers")]
    assert by_target[("family", "directives")]["detail"] == "family · 1 member"
    assert "documentation" not in by_target[("family", "directives")]


def test_editor_helper_family_catalog_recency_cap_skips_older_families(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.integrations import _editor_helper_agent_plans as plans

    monkeypatch.setattr(plans, "_FAMILY_PREVIEW_LIMIT", 2)
    tale = tmp_path / "tale.md"
    tale.write_text(_TALE_PLAN, encoding="utf-8")
    by_target = _catalog_by_target(
        monkeypatch,
        [
            _family_record("20260816010101", "old", plan_path=str(tale)),
            _family_record("20260816020202", "mid", plan_path=str(tale)),
            _family_record("20260816030303", "new", plan_path=str(tale)),
        ],
    )

    expected = "tale · Complete common words from the middle of a word"
    assert by_target[("family", "old")]["detail"] == "family · 1 member"
    assert by_target[("family", "mid")]["detail"] == expected
    assert by_target[("family", "new")]["detail"] == expected


def test_editor_helper_family_catalog_plan_and_bead_failures_degrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreadable = tmp_path / "broken.md"
    unreadable.write_text("not a plan\n", encoding="utf-8")

    def _unavailable(bead_id: str, **_kwargs: object) -> None:
        raise RuntimeError(f"bead store unavailable for {bead_id}")

    monkeypatch.setattr(
        "sase.integrations._editor_helper_agent_plans.lookup_bead_issue",
        _unavailable,
    )
    by_target = _catalog_by_target(
        monkeypatch,
        [
            _family_record(
                "20260816010101",
                "missing",
                plan_path="/tmp/sase-n9-missing-plan.md",
                raw_prompt_snippet="Use the launch prompt instead",
            ),
            _family_record("20260816020202", "broken", plan_path=str(unreadable)),
            _family_record("20260816030303", "beads", phase_bead_id="sase-n9.2"),
        ],
    )

    assert by_target[("family", "missing")]["detail"] == (
        "family · 1 member · Use the launch prompt instead"
    )
    assert by_target[("family", "broken")]["detail"] == "family · 1 member"
    assert by_target[("family", "beads")]["detail"] == "family · 1 member"


def test_editor_helper_family_catalog_root_then_member_uses_child_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tale = tmp_path / "tale.md"
    tale.write_text(_TALE_PLAN, encoding="utf-8")
    by_target = _catalog_by_target(
        monkeypatch,
        [
            _family_record("20260816010101", "later", suffix="--plan"),
            _family_record(
                "20260816010102",
                "later",
                suffix="--code",
                parent_timestamp="20260816010101",
                plan_path=str(tale),
            ),
        ],
    )

    family = by_target[("family", "later")]
    assert family["member_count"] == 2
    assert family["detail"] == (
        "tale · Complete common words from the middle of a word"
    )
