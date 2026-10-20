"""Flat-key projection guards for agent-session-turn wire maps."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from sase.core import agent_tribe_evidence as evidence_mod
from sase.core import agent_scan_wire_agent_session_turn as wire_mod
from sase.core.agent_scan_wire_agent_session_turn import (
    AgentSessionTurnGateWire,
    AgentSessionTurnMonitorWire,
    AgentSessionTurnWire,
    agent_session_turn_from_mapping,
)


@pytest.mark.parametrize(
    ("map_name", "wire_cls", "excluded"),
    [
        (
            "_MONITOR_SHARED_KEYS",
            AgentSessionTurnWire,
            frozenset({"kind", "monitor", "gate"}),
        ),
        (
            "_GATE_SHARED_KEYS",
            AgentSessionTurnWire,
            frozenset({"kind", "monitor", "gate"}),
        ),
        ("_MONITOR_SPECIFIC_KEYS", AgentSessionTurnMonitorWire, frozenset()),
        ("_GATE_SPECIFIC_KEYS", AgentSessionTurnGateWire, frozenset()),
    ],
)
def test_flat_key_targets_are_wire_fields(
    map_name: str, wire_cls: type[object], excluded: frozenset[str]
) -> None:
    key_map = getattr(wire_mod, map_name)
    fields = set(dataclasses.fields(wire_cls))
    field_names = {field.name for field in fields}
    for target in key_map.values():
        assert target not in excluded
        assert target in field_names, f"{map_name} maps to unknown field {target!r}"


def test_recovery_monitor_flat_marker_with_plural_reasons_projects() -> None:
    done = {
        "monitor_id": "99--mon-1",
        "monitor_state": "failed",
        "monitor_host_completion_status": "recovery",
        "monitor_host_completion_reason": "no_new_verdict_insufficient:new_failures",
        "monitor_host_completion_reasons": ["no_new_verdict_insufficient:new_failures"],
        "monitor_followup_outcome": "launched",
        "outcome": "monitored",
    }
    turn = agent_session_turn_from_mapping(done)
    assert turn is not None
    assert turn.kind == "monitor"
    assert turn.host_completion_status == "recovery"
    assert turn.host_completion_reason == "no_new_verdict_insufficient:new_failures"
    from sase.core.dismissed_agent_completion import effective_done_outcome

    assert effective_done_outcome(done) == "failed"


def test_poisoned_marker_does_not_wedge_stored_tribe_scan(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / "20261020105054"
    artifact_dir.mkdir(parents=True)
    marker = {
        "name": "proj--mon-1",
        "agent_session": "proj",
        "agent_session_role": "monitor",
        "monitor_id": "99--mon-1",
        "monitor_state": "failed",
        "monitor_host_completion_status": "recovery",
        "monitor_host_completion_reason": "no_new_verdict_insufficient:new_failures",
        "monitor_host_completion_reasons": ["no_new_verdict_insufficient:new_failures"],
    }
    (artifact_dir / "agent_meta.json").write_text(json.dumps(marker), encoding="utf-8")
    (artifact_dir / "done.json").write_text(
        json.dumps({**marker, "outcome": "monitored"}), encoding="utf-8"
    )
    tribes_path = tmp_path / "agent_tribes.json"
    legacy_path = tmp_path / "agent_tags.json"

    evidence_mod._CACHE.clear()
    try:
        names = evidence_mod.stored_tribe_names_for_resolution(
            projects_root=projects_root,
            agent_tribes_path=tribes_path,
            legacy_store_path=legacy_path,
        )
        assert isinstance(names, tuple)
    finally:
        evidence_mod._CACHE.clear()
