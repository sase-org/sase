"""Wire-mirrors cutover: Python wire mirrors hydrate either spelling.

Covers bead ``sase-17m.3.1.3``: the scan markers/conversion, cleanup,
group-archive, runner-slot capacity, hold identity, and fleet locator mirrors
hydrate legacy- and new-shaped dicts identically, writers emit only new
spellings, and payloads sent to core round-trip through the real
``sase_core_rs`` bindings.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.models._fleet_agents_promotion import _locator_wire
from sase.core.agent_cleanup_wire import (
    agent_cleanup_wire_to_json_dict,
    cleanup_target_from_dict,
)
from sase.core.agent_group_archive_wire import (
    saved_agent_group_from_dict,
    saved_agent_group_wire_to_json_dict,
)
from sase.core.agent_hold_facade import agent_armer_wire_for_artifacts
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchUnitWire,
    agent_launch_wire_to_json_dict,
    launch_plan_from_dict,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    agent_scan_wire_from_dict,
    agent_scan_wire_to_json_dict,
)
from sase.core.agent_scan_wire_agent_session_turn import (
    agent_session_turn_from_mapping,
)
from sase.core.agent_scan_wire_conversion import (
    _agent_meta_from_dict,
    _done_marker_from_dict,
)
from sase.core.runner_slots._admission_capacity_records import (
    capacity_record_from_scan,
    capacity_session_keys_for_core,
)
from sase.core.runner_slots._admission_snapshot import (
    runner_capacity_snapshot_from_capacity_records,
)
from sase.core.agent_scan_wire_records import AgentArtifactRecordWire
from sase.core.rust import require_rust_binding

_LEGACY_META = {
    "name": "acme--code",
    "agent_family": "acme",
    "agent_family_role": "code",
    "parent_timestamp": None,
    "workflow_name": "acme",
}
_NEW_META = {
    "name": "acme--code",
    "agent_session": "acme",
    "agent_session_role": "code",
    "parent_timestamp": None,
    "workflow_name": "acme",
}

_LEGACY_SHELL = {"kind": "monitor", "id": "m1", "state": "running"}
_FLAT_SHELL_META = {
    "name": "acme--mon",
    "agent_family": "acme",
    "agent_family_role": "monitor",
    "monitor_id": "m1",
    "monitor_state": "running",
}


def test_agent_meta_hydrates_either_spelling_identically() -> None:
    legacy = _agent_meta_from_dict(
        {**_LEGACY_META, "family_shell": dict(_LEGACY_SHELL)}
    )
    new = _agent_meta_from_dict(
        {**_NEW_META, "agent_session_turn": dict(_LEGACY_SHELL)}
    )
    assert legacy == new
    assert legacy.agent_session == "acme"
    assert legacy.agent_session_role == "code"
    assert legacy.agent_session_parallel is False
    assert legacy.agent_session_turn is not None
    assert legacy.agent_session_turn.id == "m1"


def test_agent_meta_parallel_backfill_reads_either_spelling() -> None:
    for meta in (
        {"agent_family": "acme", "agent_family_parallel": True},
        {"agent_session": "acme", "agent_session_parallel": True},
    ):
        wire = _agent_meta_from_dict(dict(meta))
        assert wire.agent_clan == "acme"
        assert wire.agent_session is None
        assert wire.agent_session_role is None
        assert wire.agent_session_parallel is True


def test_done_marker_hydrates_flat_and_nested_either_spelling() -> None:
    flat = _done_marker_from_dict(dict(_FLAT_SHELL_META))
    nested_legacy = _done_marker_from_dict(
        {"outcome": "x", "family_shell": dict(_LEGACY_SHELL)}
    )
    nested_new = _done_marker_from_dict(
        {"outcome": "x", "agent_session_turn": dict(_LEGACY_SHELL)}
    )
    for shell in (
        flat.agent_session_turn,
        nested_legacy.agent_session_turn,
        nested_new.agent_session_turn,
    ):
        assert shell is not None
        assert shell.kind == "monitor"
        assert shell.id == "m1"
        assert shell.state == "running"
    assert nested_legacy.agent_session_turn == nested_new.agent_session_turn


def test_shell_from_mapping_reads_flat_legacy_keys() -> None:
    shell = agent_session_turn_from_mapping(dict(_FLAT_SHELL_META))
    assert shell is not None and shell.kind == "monitor" and shell.id == "m1"


def test_scan_wire_json_emits_only_new_spellings() -> None:
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [
                {
                    "project_name": "myproj",
                    "project_dir": "/tmp/projects/myproj",
                    "project_file": "/tmp/projects/myproj/myproj.sase",
                    "workflow_dir_name": "ace-run",
                    "artifact_dir": "/tmp/projects/myproj/artifacts/ace-run/t",
                    "timestamp": "t",
                    "agent_meta": {
                        **_LEGACY_META,
                        "family_shell": dict(_LEGACY_SHELL),
                    },
                    "done": {"outcome": "completed"},
                    "has_done_marker": True,
                }
            ],
        }
    )
    payload = agent_scan_wire_to_json_dict(snapshot)
    meta_payload = payload["records"][0]["agent_meta"]
    assert meta_payload["agent_session"] == "acme"
    assert meta_payload["agent_session_role"] == "code"
    assert meta_payload["agent_session_turn"]["id"] == "m1"
    for legacy_key in (
        "agent_family",
        "agent_family_role",
        "agent_family_parallel",
        "family_shell",
        "agent_session_turn",
    ):
        assert legacy_key not in meta_payload
    assert "agent_session_turn" in meta_payload


def test_cleanup_wire_hydrates_either_spelling_and_emits_new() -> None:
    legacy = cleanup_target_from_dict(
        {
            "identity": {"agent_type": "run", "cl_name": "cl"},
            "agent_type": "run",
            "status": "x",
            "agent_family_parallel": True,
        }
    )
    new = cleanup_target_from_dict(
        {
            "identity": {"agent_type": "run", "cl_name": "cl"},
            "agent_type": "run",
            "status": "x",
            "agent_session_parallel": True,
        }
    )
    assert legacy == new
    assert legacy.agent_session_parallel is True
    emitted = agent_cleanup_wire_to_json_dict(legacy)
    assert emitted["agent_session_parallel"] is True
    assert "agent_family_parallel" not in emitted


def test_group_archive_reads_legacy_emits_new() -> None:
    base = {
        "group_id": "g",
        "created_at": "2026-05-27T12:00:00Z",
        "source": "marked_agents",
        "title": "t",
        "agent_count": 1,
        "top_level_agent_count": 1,
    }
    legacy = saved_agent_group_from_dict(
        {**base, "canonical_global_family": "alice.athena.probe"}
    )
    new = saved_agent_group_from_dict(
        {**base, "canonical_global_agent_session": "alice.athena.probe"}
    )
    assert legacy == new
    assert legacy.canonical_global_agent_session == "alice.athena.probe"
    emitted = saved_agent_group_wire_to_json_dict(legacy)
    assert emitted["canonical_global_agent_session"] == "alice.athena.probe"
    assert "canonical_global_family" not in emitted


def test_capacity_session_keys_shape_uses_new_parallel_spelling() -> None:
    keys = capacity_session_keys_for_core(
        agent_session="acme",
        agent_session_role="member",
        agent_session_parallel=True,
        turn_kind="monitor",
        turn_id="m1",
        turn_state="running",
    )
    assert keys == {
        "agent_session": "acme",
        "agent_session_role": "member",
        "agent_session_parallel": True,
        "agent_session_turn_kind": "monitor",
        "agent_session_turn_id": "m1",
        "agent_session_turn_state": "running",
    }


def test_capacity_session_keys_legacy_shell_spelling_still_resolves() -> None:
    keys = capacity_session_keys_for_core(
        agent_session="acme",
        agent_session_role="member",
        agent_session_parallel=True,
        shell_kind="monitor",
        shell_id="m1",
        shell_state="running",
    )
    assert keys == {
        "agent_session": "acme",
        "agent_session_role": "member",
        "agent_session_parallel": True,
        "agent_session_turn_kind": "monitor",
        "agent_session_turn_id": "m1",
        "agent_session_turn_state": "running",
    }


def _scan_record(meta: dict[str, Any]) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="p",
        project_dir="d",
        project_file="f",
        workflow_dir_name="ace-run",
        artifact_dir="d/20260924010000",
        timestamp="20260924010000",
        agent_meta=_agent_meta_from_dict(meta),
    )


def test_capacity_snapshot_real_round_trip_accepts_new_spellings() -> None:
    """Payloads built from legacy markers round-trip through real core."""
    record = _scan_record({**_LEGACY_META, "family_shell": dict(_LEGACY_SHELL)})
    capacity = capacity_record_from_scan(record, lambda _record: True)
    assert capacity["agent_session"] == "acme"
    assert "agent_family" not in capacity
    assert capacity["agent_session_turn_kind"] == "monitor"
    assert "family_shell_kind" not in capacity
    snapshot = runner_capacity_snapshot_from_capacity_records(
        [capacity], effective_limit=4.0
    )
    assert isinstance(snapshot, dict) and snapshot.get("schema_version") is not None


def test_hold_armer_wire_emits_session_for_either_spelling(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_artifacts_dir",
        lambda *_args: "proj",
    )
    for meta in (
        {"name": "worker", "agent_family": "holder"},
        {"name": "worker", "agent_session": "holder"},
    ):
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps({**meta, "pid": 4242}), encoding="utf-8"
        )
        wire = agent_armer_wire_for_artifacts(str(artifacts_dir))
        assert wire["agent_session"] == "holder"
        assert "family" not in wire
        assert "session" not in wire


def test_hold_pending_identities_send_session_key(
    monkeypatch: Any,
) -> None:
    """Identities sent to core carry ``agent_session``, never ``family``."""
    import sase.core.agent_hold_pending as pending

    captured: dict[str, Any] = {}

    def fake_binding(name: str) -> Any:
        assert name == "agent_hold_summarize_capture"
        real = require_rust_binding(name)

        def wrapper(scope_wire: Any, identities: Any, armer: Any) -> Any:
            captured["identities"] = [dict(item) for item in identities]
            return real(scope_wire, identities, armer)

        return wrapper

    # ``capture_pending_targets`` imports ``require_rust_binding`` at call
    # time, so patching the ``sase.core.rust`` attribute intercepts it.
    monkeypatch.setattr("sase.core.rust.require_rust_binding", fake_binding)
    entries = [
        SimpleNamespace(
            status="WAITING",
            artifacts_dir="/a/w1",
            name="w1",
            project="scratch",
            timestamp="20260910120001",
        ),
    ]
    monkeypatch.setattr(
        "sase.integrations.agent_list_entries.agent_list_entries",
        lambda project=None: entries,
    )
    capture = pending.capture_pending_targets(project="scratch", scope="project")
    assert capture.waiting_count == 1
    assert len(captured["identities"]) == 1
    assert "agent_session" in captured["identities"][0]
    assert "family" not in captured["identities"][0]
    assert "session" not in captured["identities"][0]


def _installation_id() -> str:
    return "sase_inst_v1_" + "cd" * 32


def _fleet_locator(session_key: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": {
                "schema_version": 1,
                "installation_id": _installation_id(),
            },
            "project_id": "sase-main",
        },
        "agent_id": "agent-1",
        session_key: "session-1",
    }


def test_fleet_locator_wire_emits_new_and_matches_core_key() -> None:
    """Legacy and new locator inputs normalize to one core-accepted shape."""
    # legacy agent-family spelling: pre-rename locators carry ``family_id``
    legacy = _locator_wire(_fleet_locator("family_id"))
    new = _locator_wire(_fleet_locator("agent_session_id"))
    assert legacy == new
    assert legacy is not None and legacy["agent_session_id"] == "session-1"
    assert "family_id" not in legacy
    key = require_rust_binding("fleet_logical_locator_key")(legacy)
    assert "|session:9:session-1|" in key


def _launch_plan_with_attach(parent_key: str, suffix_key: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "launch_kind": "auto",
        "selected_project": "sase",
        "content_digest": "a" * 64,
        "units": [
            {
                "logical_id": "unit-1",
                "source_order": 0,
                "waits": [],
                "payload": {
                    "kind": "agent",
                    "prompt": "Review",
                    parent_key: "parent",
                    suffix_key: "reviewer",
                },
            }
        ],
        "diagnostics": [],
    }


def test_launch_agent_unit_hydrates_either_attach_spelling() -> None:
    """Core-returned (legacy) and Python-built (new) launch units match."""
    # legacy agent-family spelling: core still returns the ``family_attach_*`` keys
    legacy = launch_plan_from_dict(
        _launch_plan_with_attach("family_attach_parent", "family_attach_suffix")
    )
    new = launch_plan_from_dict(
        _launch_plan_with_attach(
            "agent_session_attach_parent", "agent_session_attach_suffix"
        )
    )
    assert legacy == new
    agent = new.units[0].payload
    assert isinstance(agent, AgentUnitWire)
    assert agent.agent_session_attach_parent == "parent"
    assert agent.agent_session_attach_suffix == "reviewer"


def test_launch_agent_unit_json_emits_only_new_attach_spelling() -> None:
    agent = AgentUnitWire(
        prompt="Review",
        agent_session_attach_parent="parent",
        agent_session_attach_suffix="reviewer",
    )
    payload = agent_launch_wire_to_json_dict(agent)
    assert payload["agent_session_attach_parent"] == "parent"
    assert payload["agent_session_attach_suffix"] == "reviewer"
    assert "family_attach_parent" not in payload
    assert "family_attach_suffix" not in payload
    bare = agent_launch_wire_to_json_dict(AgentUnitWire(prompt="Review"))
    assert "agent_session_attach_parent" not in bare
    assert "agent_session_attach_suffix" not in bare


def test_launch_unit_real_round_trip_accepts_new_attach_spelling() -> None:
    """Real core reads the new attach keys Python sends as aliases."""
    unit = LaunchUnitWire(
        logical_id="u1",
        source_order=0,
        payload=AgentUnitWire(
            prompt="Review",
            agent_session_attach_parent="parent",
            agent_session_attach_suffix="reviewer",
        ),
    )
    payload = agent_launch_wire_to_json_dict(unit)
    assert "family_attach_parent" not in payload["payload"]
    armer = require_rust_binding("launch_unit_hold_armer")(
        payload, "req-attach", "sase", 4242, "/tmp/done.json"
    )
    assert armer["agent_name"] == "parent--reviewer"
    assert armer["agent_session"] == "parent"
    assert "family" not in armer
