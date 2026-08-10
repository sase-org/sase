"""Tests for integration-facing rich agent list projections."""

from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

from sase.agent.running_listing import _running_from_snapshot
from sase.agents.cli_list import _agent_to_json
from sase.core.agent_scan_wire import (
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentClanContextWire,
    AgentMetaWire,
    WaitingMarkerWire,
)
from sase.integrations.agent_list_entries import (
    _attach_runner_slot_context,
    _build_agent_list_entry,
    agent_list_entries,
)
from tests._agent_list_entries_helpers import agent, record


def test_agent_list_json_exposes_runner_slot_fields() -> None:
    entry = _build_agent_list_entry(
        agent(status="WAITING"),
        record=record(
            agent_meta=AgentMetaWire(),
            waiting=WaitingMarkerWire(
                waiting_for=["phase"],
                wait_for_beads=["sase-87.2"],
                wait_runners=0,
                wait_runners_explicit=True,
                wait_priority=3,
                slot_requested_at="2026-07-12T12:00:00Z",
            ),
        ),
    )
    (entry,) = _attach_runner_slot_context([entry], 0, runner_slot_holders=("phase",))

    payload = _agent_to_json(entry)

    assert payload["waiting_for"] == ["phase"]
    assert payload["wait_for_beads"] == ["sase-87.2"]
    assert payload["wait_runners"] == 0
    assert payload["wait_runners_explicit"] is True
    assert payload["wait_priority"] == 3
    assert payload["slot_requested_at"] == "2026-07-12T12:00:00Z"
    assert payload["runner_slots_in_use"] == 0
    assert payload["runner_slot_queue_position"] == 1
    assert payload["runner_slot_queue_size"] == 1
    assert payload["parent_agent_name"] is None
    assert payload["agent_family"] is None
    assert payload["tribe"] is None
    assert payload["runner_slot_holders"] == ["phase"]


def test_agent_list_projects_hidden_clan_declaration_context(
    monkeypatch: MonkeyPatch,
) -> None:
    artifact_record = record(
        agent_meta=AgentMetaWire(
            name="toobig-0.joiner",
            pid=1234,
            run_started_at="2026-07-19T12:00:00Z",
            agent_clan="toobig-0",
            agent_clan_generation="g1",
        )
    )
    snapshot = AgentArtifactScanWire(
        schema_version=4,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[artifact_record],
        clan_context=[
            AgentClanContextWire(
                agent_clan="toobig-0",
                agent_clan_generation="g1",
                clan_tribe="chop",
                clan_tribe_source_launch_timestamp="20260701000000",
                clan_tribe_source_identity="/tmp/declarer",
            )
        ],
    )
    monkeypatch.setattr(
        "sase.agent.running_listing.is_process_alive",
        lambda *_args: True,
    )

    (info,) = _running_from_snapshot(snapshot)
    entry = _build_agent_list_entry(info, record=artifact_record)
    payload = _agent_to_json(entry)

    assert info.tribe == "chop"
    assert entry.tribe == "chop"
    assert entry.agent_clan == "toobig-0"
    assert entry.agent_clan_generation == "g1"
    assert entry.clan_tribe == "chop"
    assert payload["tribe"] == "chop"
    assert payload["agent_clan"] == "toobig-0"
    assert payload["agent_clan_generation"] == "g1"
    assert payload["clan_tribe"] == "chop"


def test_agent_list_preserves_standalone_tribe_without_clan_context(
    monkeypatch: MonkeyPatch,
) -> None:
    artifact_record = record(
        agent_meta=AgentMetaWire(
            name="standalone",
            pid=1234,
            run_started_at="2026-07-19T12:00:00Z",
            tribe="ops",
        )
    )
    snapshot = AgentArtifactScanWire(
        schema_version=4,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[artifact_record],
    )
    monkeypatch.setattr(
        "sase.agent.running_listing.is_process_alive",
        lambda *_args: True,
    )

    (info,) = _running_from_snapshot(snapshot)
    entry = _build_agent_list_entry(info, record=artifact_record)

    assert info.tribe == "ops"
    assert entry.tribe == "ops"
    assert entry.clan_tribe is None


def test_agent_list_entries_names_parallel_child_blocking_waiter(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    child_dir = tmp_path / "ace-run" / "20260717120001"
    child_dir.mkdir(parents=True)
    (child_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "parent_agent_name": "epic",
                "agent_family": "epic",
            }
        )
    )
    waiter_dir = tmp_path / "ace-run" / "20260717120002"
    waiter_dir.mkdir()
    (waiter_dir / "waiting.json").write_text(
        json.dumps(
            {
                "wait_runners": 0,
                "slot_requested_at": "2026-07-17T12:00:02-04:00",
            }
        )
    )
    child = agent(
        name="epic--phase",
        artifacts_dir=str(child_dir),
        holds_runner_slot=True,
    )
    waiter = agent(
        name="waiter",
        status="WAITING",
        artifacts_dir=str(waiter_dir),
        holds_runner_slot=False,
    )
    monkeypatch.setattr(
        "sase.integrations.agent_list_entries.list_running_agents",
        lambda: [child, waiter],
    )
    monkeypatch.setattr(
        "sase.integrations.agent_list_entries._children_by_parent_timestamp",
        lambda **_kwargs: {},
    )

    entries = agent_list_entries()
    by_name = {entry.name: entry for entry in entries}

    assert by_name["waiter"].wait.runner_slots_in_use == 1
    assert by_name["waiter"].wait.runner_slot_holders == ("epic--phase",)
    child_payload = _agent_to_json(by_name["epic--phase"])
    assert child_payload["parent_agent_name"] == "epic"
    assert child_payload["agent_family"] == "epic"
