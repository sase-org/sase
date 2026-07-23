from __future__ import annotations

import argparse
import io
import json

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
            info(records[1], "RUNNING"),
            info(records[2], "DONE"),
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
    assert by_target[("clan", "squad")] == {
        "name": "squad",
        "kind": "clan",
        "member_count": 2,
        "status": "RUNNING",
        "detail": "clan · 2 members · RUNNING",
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
