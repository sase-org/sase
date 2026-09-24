"""Legacy-input and no-legacy-emitted tests for durable-json cutover.

Phase sase-17m.3.1.5 (durable-json): every durable Python-owned JSON surface
below writes only the agent-session spelling while named legacy readers still
load pre-rename files.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.dismissed_agent_groups import _WIRE_CAPABILITY_PROBE
from sase.agent.fork_waits import fork_wait_dependency
from sase.agent.launch_request_planning import normalize_request_payload
from sase.bead.epic_launch_handoff_model import CompletionNotificationPayload
from sase.bead.epic_launch_handoff_monitor import monitor_settlement_payload
from sase.bead.epic_launch_handoff_payload import settlement_notification_action_data
from sase.continuation_baseline import _source_node_identities
from sase.core.agent_group_archive_wire import (
    saved_agent_group_from_dict,
    saved_agent_group_wire_to_json_dict,
)
from sase.dispatch.follow_store import load_follow_snapshot
from sase.gate_shell.transaction import _stamp_pending_shell_on_spec
from sase.history.chat_fork.common import (
    LEGACY_FORK_SOURCE_KIND,
    fork_source_has_failure,
    fork_source_has_proc_content,
    fork_source_kind,
)
from sase.notification_gates.model_shell import (
    GateShellBranchSpec,
    GateShellNext,
    LEGACY_GATE_SHELL_NEXT_FORK,
)
from sase.ops.commands._agent_revert import (
    _bulk_preview_from_payload,
    _single_preview_from_payload,
    serialize_bulk_revert_preview,
)
from sase.stats._view_builders import build_runtime_view
from sase.stats.query import normalize_runtime_group_by

__all__: list[str] = []


def _group_base() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "group_id": "g-1",
        "created_at": "2026-09-01T00:00:00Z",
        "source": "marked_agents",
        "title": "1 agent in cl",
        "agent_count": 1,
        "top_level_agent_count": 1,
    }


# Surface 1: saved dismissed groups.


def test_dismissed_group_probe_emits_new_spelling() -> None:
    assert (
        _WIRE_CAPABILITY_PROBE["canonical_global_agent_session"] == "alice.athena.probe"
    )
    assert "canonical_global_family" not in _WIRE_CAPABILITY_PROBE


def test_dismissed_group_legacy_file_loads_and_rewrites_new() -> None:
    group = saved_agent_group_from_dict(
        {**_group_base(), "canonical_global_family": "alice.athena.probe"}
    )
    assert group.canonical_global_agent_session == "alice.athena.probe"
    emitted = saved_agent_group_wire_to_json_dict(group)
    assert emitted["canonical_global_agent_session"] == "alice.athena.probe"
    assert "canonical_global_family" not in emitted


# Surface 2: wait_for_fork_sources and chat-fork source kinds.


def test_fork_source_kind_normalizes_legacy_family() -> None:
    assert fork_source_kind({"kind": "session"}) == "session"
    assert fork_source_kind({"kind": LEGACY_FORK_SOURCE_KIND}) == "session"


def test_fork_source_predicates_accept_both_kinds() -> None:
    members = [{"kind": "agent", "name": "a", "failure": {"outcome": "failed"}}]
    for kind in ("session", "family"):
        source = {"kind": kind, "name": "chain", "members": members}
        assert fork_source_has_failure(source) is True
    proc_members = [{"kind": "proc", "name": "p"}]
    for kind in ("session", "family"):
        assert (
            fork_source_has_proc_content(
                {"kind": kind, "name": "chain", "members": proc_members}
            )
            is True
        )


def test_fork_wait_writer_emits_session_kind(monkeypatch: Any) -> None:
    from sase.agent import names as agent_names
    from sase.agent.names._lookup_groups import AgentFamily

    monkeypatch.setattr(agent_names, "find_agent_clan", lambda _name: None)
    monkeypatch.setattr(
        agent_names,
        "find_agent_family",
        lambda _name: AgentFamily(base_name="feat", root=None, members=()),
    )
    assert fork_wait_dependency("feat") == {"kind": "session", "name": "feat"}


def test_continuation_baseline_measures_both_kinds() -> None:
    member = {"kind": "agent", "name": "a", "path": "/tmp/chat.md"}
    for kind in ("session", "family"):
        assert _source_node_identities(
            {"kind": kind, "name": "chain", "members": [member]}
        ) == ["agent:path:/tmp/chat.md"]


# Surface 3: gate descriptors and gate_next_fork.


def test_gate_next_fork_defaults_to_session() -> None:
    assert GateShellNext.from_mapping(None, target="shell.next").fork == "session"
    assert GateShellNext.from_mapping({}, target="shell.next").fork == "session"


def test_gate_next_fork_normalizes_legacy_family() -> None:
    policy = GateShellNext.from_mapping(
        {"fork": LEGACY_GATE_SHELL_NEXT_FORK}, target="shell.next"
    )
    assert policy.fork == "session"
    branch = GateShellBranchSpec.from_mapping(
        {"fork": "family", "status": "DONE"},
        target="shell.branches.done",
        inherited_next=GateShellNext(),
    )
    assert branch.fork == "session"


def test_gate_next_fork_writer_emits_no_legacy() -> None:
    policy = GateShellNext.from_mapping({"fork": "family"}, target="shell.next")
    assert policy.to_dict()["fork"] == "session"
    assert "family" not in json.dumps(policy.to_dict())


# Surface 4: notification action_data session suffix.


def test_gate_shell_stamp_writes_session_suffix() -> None:
    spec = SimpleNamespace(
        presentation={"action_data": {"raw_suffix": "ts-1", "agent_timestamp": "ts-1"}}
    )
    _stamp_pending_shell_on_spec(
        spec, member_artifacts_dir="/tmp/dir", member_timestamp="ts-1"
    )
    action_data = spec.presentation["action_data"]
    assert action_data["agent_session_root_suffix"] == "ts-1"
    assert "family_root_suffix" not in action_data


def test_gate_shell_stamp_reads_legacy_suffix() -> None:
    spec = SimpleNamespace(presentation={"action_data": {"family_root_suffix": "ts-9"}})
    _stamp_pending_shell_on_spec(
        spec, member_artifacts_dir="/tmp/dir", member_timestamp="ts-1"
    )
    assert spec.presentation["action_data"]["agent_session_root_suffix"] == "ts-9"


def test_settlement_action_data_writes_session_suffix() -> None:
    data = settlement_notification_action_data(
        None, cl_name="cl", action_data={"raw_suffix": "ts-1"}
    )
    assert data["agent_session_root_suffix"] == "ts-1"
    assert "family_root_suffix" not in data


def test_monitor_settlement_payload_reads_legacy_suffix(tmp_path: Path) -> None:
    root = tmp_path / "20260727123456"
    monitor = tmp_path / "20260727123500"
    root.mkdir()
    monitor.mkdir()
    (monitor / "agent_meta.json").write_text("{}")
    payload = CompletionNotificationPayload(
        sender="user-agent",
        cl_name="demo-cl",
        success=True,
        notes=[],
        action="JumpToAgent",
        action_data={"family_root_suffix": "20260727123456"},
        extra_files=[],
        silent=False,
        tags=None,
    )
    updated = monitor_settlement_payload(root, monitor, payload)
    assert updated.action_data["agent_session_root_suffix"] == "20260727123456"
    assert "family_root_suffix" not in updated.action_data


# Surface 5: ops revert session base and scope.


def test_revert_serialize_emits_session_base() -> None:
    from sase.ace.revert_agent_models import BulkRevertPreview, RevertTarget

    preview = BulkRevertPreview(
        workspace_dir="/tmp",
        targets=(
            RevertTarget(
                agent_name="feat--plan",
                display_name="feat--plan",
                workspace_dir="/tmp",
                agent_session_base="feat",
            ),
        ),
    )
    from sase.ops.commands._agent_revert import serialize_bulk_revert_preview

    payload = serialize_bulk_revert_preview(preview)
    assert payload["targets"][0]["agent_session_base"] == "feat"
    assert "family_base" not in payload["targets"][0]
    assert preview.targets[0].scope == "session"


def test_revert_payload_readers_accept_legacy_spellings() -> None:
    preview = _single_preview_from_payload({"scope": "family"}, "agent")
    assert preview.scope == "session"
    bulk = _bulk_preview_from_payload(
        {
            "targets": [
                {
                    "agent_name": "feat--plan",
                    "display_name": "feat--plan",
                    "workspace_dir": "/tmp",
                    "family_base": "feat",
                }
            ]
        },
        "agent",
    )
    assert bulk.targets[0].agent_session_base == "feat"
    assert bulk.targets[0].scope == "session"


def test_revert_serialize_round_trip_has_no_legacy() -> None:
    from sase.ace.revert_agent_models import BulkRevertPreview, RevertTarget

    preview = BulkRevertPreview(
        workspace_dir="/tmp",
        targets=(
            RevertTarget(
                agent_name="a",
                display_name="a",
                workspace_dir="/tmp",
                agent_session_base="feat",
            ),
        ),
    )
    payload = serialize_bulk_revert_preview(preview)
    assert "family" not in json.dumps(payload)


# Surface 6: launch-request session type and context keys.


def _launch_payload(**overrides: Any) -> dict[str, Any]:
    payload = {"schema_version": 1, "prompt": "do it", "reason": "test"}
    payload.update(overrides)
    return payload


def test_launch_request_type_normalizes_legacy_family_type() -> None:
    assert (
        normalize_request_payload(_launch_payload(family_type="bulk"))[
            "agent_session_type"
        ]
        == "bulk"
    )
    assert (
        normalize_request_payload(_launch_payload(agent_session_type="bulk"))[
            "agent_session_type"
        ]
        == "bulk"
    )


def test_launch_request_writer_emits_no_legacy_type() -> None:
    normalized = normalize_request_payload(_launch_payload(family_type="bulk"))
    assert "family_type" not in normalized
    assert normalized["agent_session_type"] == "bulk"


def test_requester_identity_prefers_session_context() -> None:
    from sase.agent.launch_request_continuation import _requester_family_identity

    assert (
        _requester_family_identity(
            {
                "agent_meta.agent_session": "new-base",
                "agent_meta.agent_family": "old-base",
            }
        )
        == "new-base"
    )
    assert (
        _requester_family_identity({"agent_meta.agent_family": "old-base"})
        == "old-base"
    )


# Surface 7: stats runtime_group_by.


def test_stats_group_by_normalizes_legacy_family(monkeypatch: Any) -> None:
    assert normalize_runtime_group_by("family") == "session"
    assert normalize_runtime_group_by("session") == "session"

    from sase.stats import query as stats_query

    requests: list[dict[str, Any]] = []

    def binding(_index: str, request: dict[str, Any]) -> dict[str, Any]:
        requests.append(request)
        return {}

    monkeypatch.setattr(stats_query, "require_rust_binding", lambda _name: binding)
    stats_query.query_run_stats(
        start_ts=0,
        end_ts=100,
        runtime_group_by="family",  # type: ignore[arg-type]
        index_path=Path("/tmp/index"),
    )
    assert requests[0]["runtime_group_by"] == "session"


def test_stats_view_normalizes_core_family_group() -> None:
    from sase.project_display_names import ProjectDisplaySnapshot

    payload: dict[str, Any] = {
        "totals": {},
        "runtime_groups": [],
        "runtime_group_by": "family",
    }
    view = build_runtime_view(payload, ProjectDisplaySnapshot())
    assert view.group_by == "session"


# Surface 8: fleet follows.json logical keys.


def test_follows_store_loads_family_and_session_keys(tmp_path: Path) -> None:
    from sase.core.rust import require_rust_binding

    key_binding = require_rust_binding("fleet_logical_locator_key")
    locator = {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": {
                "schema_version": 1,
                "installation_id": "sase_inst_v1_" + "b" * 64,
            },
            "project_id": "sase-main",
        },
        "agent_id": "agent-1",
        "family_id": "family-1",
    }
    family_key = key_binding(dict(locator))
    assert "family:" in family_key
    session_key = family_key.replace("family:", "session:", 1)

    def record(key: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "logical_locator": dict(locator),
            "logical_key": key,
            "created_by": "explicit",
            "state": "active",
            "created_at_unix": 20.0,
            "updated_at_unix": 20.0,
            "activated_at_unix": 20.0,
            "operation_key": None,
        }

    path = tmp_path / "follows.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [record(family_key), record(session_key)],
                "tombstones": [],
            }
        )
    )
    snapshot = load_follow_snapshot(path)
    assert family_key in snapshot.active_logical_keys
    assert session_key in snapshot.active_logical_keys
