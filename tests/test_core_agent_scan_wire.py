from __future__ import annotations

from dataclasses import fields

import pytest

from sase.core.agent_scan_wire import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexStatusWire,
    AgentArtifactIndexUpdateWire,
    agent_artifact_index_query_to_dict,
    agent_artifact_index_status_from_dict,
    agent_artifact_index_update_from_dict,
    agent_scan_wire_from_dict,
    agent_scan_wire_to_json_dict,
)

from .agent_scan_golden import (
    EXPECTED_DECODE_ERRORS,
    EXPECTED_OS_ERRORS,
    EXPECTED_TIMESTAMPS,
    fixture_summary,
)


def test_schema_version_pinned() -> None:
    """Bumping the schema is a deliberate, reviewable event."""
    assert AGENT_SCAN_WIRE_SCHEMA_VERSION == 6
    assert AGENT_ARTIFACT_INDEX_SCHEMA_VERSION == 19


def test_clan_context_round_trips_with_source_identity() -> None:
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "records": [],
            "clan_context": [
                {
                    "agent_clan": "toobig-0",
                    "agent_clan_generation": "g1",
                    "clan_tribe": "chop",
                    "clan_summary": "Chop generation",
                    "clan_tribe_source_launch_timestamp": "20260701000000",
                    "clan_tribe_source_identity": "/tmp/declarer",
                    "clan_summary_source_launch_timestamp": "20260701000000",
                    "clan_summary_source_identity": "/tmp/declarer",
                }
            ],
        }
    )

    assert snapshot.clan_context[0].clan_tribe == "chop"
    assert snapshot.clan_context[0].clan_summary == "Chop generation"
    assert agent_scan_wire_to_json_dict(snapshot)["clan_context"] == [
        {
            "agent_clan": "toobig-0",
            "agent_clan_generation": "g1",
            "clan_tribe": "chop",
            "clan_summary": "Chop generation",
            "clan_tribe_source_launch_timestamp": "20260701000000",
            "clan_tribe_source_identity": "/tmp/declarer",
            "clan_summary_source_launch_timestamp": "20260701000000",
            "clan_summary_source_identity": "/tmp/declarer",
        }
    ]


def test_scan_wire_rejects_stale_binding_schema() -> None:
    with pytest.raises(ValueError, match="schema mismatch"):
        agent_scan_wire_from_dict(
            {
                "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION - 1,
                "projects_root": "/tmp/projects",
                "records": [],
            }
        )


def test_legacy_metadata_tag_hydrates_canonical_tribe_only() -> None:
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "records": [
                {
                    "project_name": "proj",
                    "project_dir": "/tmp/projects/proj",
                    "project_file": "/tmp/projects/proj/proj.sase",
                    "workflow_dir_name": "ace-run",
                    "artifact_dir": "/tmp/projects/proj/artifacts/ace-run/1",
                    "timestamp": "1",
                    "agent_meta": {"tag": "legacy"},
                }
            ],
        }
    )

    assert snapshot.records[0].agent_meta is not None
    assert snapshot.records[0].agent_meta.tribe == "legacy"
    serialized = agent_scan_wire_to_json_dict(snapshot)
    metadata = serialized["records"][0]["agent_meta"]
    assert metadata["tribe"] == "legacy"
    assert "tag" not in metadata


def test_artifact_index_wire_helpers() -> None:
    assert AgentArtifactIndexQueryWire().active_limit is None
    assert AgentArtifactIndexQueryWire().freshness == "revalidate"

    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=False,
        include_full_history=True,
        active_limit=50,
        recent_completed_limit=None,
        include_hidden=True,
        freshness="cached",
        only_monitors=True,
    )
    assert agent_artifact_index_query_to_dict(query) == {
        "include_active": True,
        "include_recent_completed": False,
        "include_full_history": True,
        "active_limit": 50,
        "recent_completed_limit": None,
        "include_hidden": True,
        "freshness": "cached",
        "only_monitors": True,
    }
    assert AgentArtifactIndexQueryWire().only_monitors is False

    update = agent_artifact_index_update_from_dict(
        {
            "schema_version": 1,
            "index_path": "/tmp/index.sqlite",
            "projects_root": "/tmp/projects",
            "rows_indexed": 2,
            "rows_deleted": 1,
            "rows_skipped": 3,
        }
    )
    assert update == AgentArtifactIndexUpdateWire(
        schema_version=1,
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        rows_indexed=2,
        rows_deleted=1,
        rows_skipped=3,
    )

    status = agent_artifact_index_status_from_dict(
        {
            "schema_version": 4,
            "index_path": "/tmp/index.sqlite",
            "agent_artifacts_rows": 10,
            "agent_artifact_aliases_rows": 1,
            "dismissed_agents_rows": 2,
        }
    )
    assert status == AgentArtifactIndexStatusWire(
        schema_version=4,
        index_path="/tmp/index.sqlite",
        agent_artifacts_rows=10,
        agent_artifact_aliases_rows=1,
        dismissed_agents_rows=2,
    )


def test_agent_meta_output_variables_round_trip() -> None:
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
                    "artifact_dir": "/tmp/projects/myproj/artifacts/ace-run/20260601010101",
                    "timestamp": "20260601010101",
                    "agent_meta": {
                        "name": "producer",
                        "agent_family": "legacy_clan",
                        "agent_family_role": "phase",
                        "agent_family_parallel": True,
                        "clan_summary": "[bold]Research[/bold]",
                        "output_path": "/tmp/producer.log",
                        "linked_repos": [
                            {
                                "name": "sase-core",
                                "workspace_dir": "/tmp/sase-core_7",
                                "workspace_strategy": "suffix",
                            }
                        ],
                        "output_variables": {
                            "attempts": 2,
                            "duration_s": 42.5,
                            "findings": [
                                {
                                    "file": "src/a.py",
                                    "severity": "high",
                                },
                                {
                                    "file": "src/b.py",
                                    "severity": "low",
                                },
                            ],
                            "missing": None,
                            "passed": True,
                            "report_path": "/tmp/report.md",
                            "status": "ok",
                            "suites": ["unit", "integration"],
                        },
                    },
                    "done": None,
                    "running": None,
                    "waiting": None,
                    "pending_question": None,
                    "workflow_state": None,
                    "plan_path": None,
                    "prompt_steps": [],
                    "raw_prompt_snippet": None,
                    "has_done_marker": False,
                }
            ],
        }
    )

    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.agent_family_parallel is True
    assert record.agent_meta.agent_clan == "legacy_clan"
    assert record.agent_meta.clan_summary == "[bold]Research[/bold]"
    assert record.agent_meta.agent_family is None
    assert record.agent_meta.agent_family_role is None
    assert record.agent_meta.output_variables == {
        "attempts": 2,
        "duration_s": 42.5,
        "findings": [
            {"file": "src/a.py", "severity": "high"},
            {"file": "src/b.py", "severity": "low"},
        ],
        "missing": None,
        "passed": True,
        "report_path": "/tmp/report.md",
        "status": "ok",
        "suites": ["unit", "integration"],
    }
    assert record.agent_meta.output_path == "/tmp/producer.log"
    assert record.agent_meta.linked_repos == [
        {
            "name": "sase-core",
            "workspace_dir": "/tmp/sase-core_7",
            "workspace_strategy": "suffix",
        }
    ]
    payload = agent_scan_wire_to_json_dict(snapshot)
    assert payload["records"][0]["agent_meta"]["agent_family_parallel"] is True
    assert payload["records"][0]["agent_meta"]["agent_clan"] == "legacy_clan"
    assert payload["records"][0]["agent_meta"]["clan_summary"] == (
        "[bold]Research[/bold]"
    )
    assert payload["records"][0]["agent_meta"]["agent_family"] is None
    assert payload["records"][0]["agent_meta"]["linked_repos"] == [
        {
            "name": "sase-core",
            "workspace_dir": "/tmp/sase-core_7",
            "workspace_strategy": "suffix",
        }
    ]
    assert payload["records"][0]["agent_meta"]["output_variables"] == {
        "attempts": 2,
        "duration_s": 42.5,
        "findings": [
            {"file": "src/a.py", "severity": "high"},
            {"file": "src/b.py", "severity": "low"},
        ],
        "missing": None,
        "passed": True,
        "report_path": "/tmp/report.md",
        "status": "ok",
        "suites": ["unit", "integration"],
    }
    assert payload["records"][0]["agent_meta"]["agent_family_parallel"] is True
    assert payload["records"][0]["agent_meta"]["output_path"] == "/tmp/producer.log"


def test_agent_meta_clan_field_order_matches_rust_wire() -> None:
    from sase.core.agent_scan_wire import AgentMetaWire

    names = [field.name for field in fields(AgentMetaWire)]
    workflow_index = names.index("workflow_name")
    assert names[workflow_index : workflow_index + 8] == [
        "workflow_name",
        "agent_clan",
        "agent_clan_generation",
        "clan_tribe",
        "clan_summary",
        "agent_family",
        "agent_family_role",
        "agent_family_parallel",
    ]


def test_explicit_agent_clan_preserves_sequential_family_fields() -> None:
    from sase.core.agent_scan_wire import AgentMetaWire

    meta = AgentMetaWire(
        agent_clan="alpha",
        agent_clan_generation="g1",
        clan_tribe="quality",
        agent_family="alpha.family",
        agent_family_role="code",
    )
    assert meta.agent_clan == "alpha"
    assert meta.agent_clan_generation == "g1"
    assert meta.clan_tribe == "quality"
    assert meta.agent_family == "alpha.family"
    assert meta.agent_family_role == "code"


def test_agent_meta_plan_committed_preserves_true_false_and_absent() -> None:
    values = [True, False, None, "false"]
    records = []
    for index, value in enumerate(values):
        meta = {"name": f"agent-{index}"}
        if value is not None:
            meta["plan_committed"] = value
        records.append(
            {
                "project_name": "myproj",
                "project_dir": "/tmp/projects/myproj",
                "project_file": "/tmp/projects/myproj/myproj.sase",
                "workflow_dir_name": "ace-run",
                "artifact_dir": f"/tmp/projects/myproj/artifacts/ace-run/{index}",
                "timestamp": str(index),
                "agent_meta": meta,
                "prompt_steps": [],
                "has_done_marker": False,
            }
        )

    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": records,
        }
    )

    assert [
        record.agent_meta.plan_committed  # type: ignore[union-attr]
        for record in snapshot.records
    ] == [True, False, None, None]


def test_rehydration_ignores_unknown_marker_keys() -> None:
    """A newer Rust core (or marker files written by a newer sase) may carry
    fields this reader does not know yet; they must be dropped, not raise.

    Regression guard for the released-pair crash where ``sase-core-rs``
    0.3.4 added ``video_paths`` to the done-marker wire and every published
    sase TUI died with ``TypeError`` on scan rehydration.
    """
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {"added_by_newer_writer": True},
            "stats": {"added_by_newer_writer": 7},
            "records": [
                {
                    "project_name": "myproj",
                    "project_dir": "/tmp/projects/myproj",
                    "project_file": "/tmp/projects/myproj/myproj.sase",
                    "workflow_dir_name": "ace-run",
                    "artifact_dir": "/tmp/projects/myproj/artifacts/ace-run/20260601010101",
                    "timestamp": "20260601010101",
                    "agent_meta": {
                        "name": "producer",
                        "added_by_newer_writer": "ignored",
                    },
                    "done": {
                        "outcome": "completed",
                        "cl_name": "myproj",
                        "added_by_newer_writer": ["ignored"],
                    },
                    "running": {"pid": 123, "added_by_newer_writer": None},
                    "waiting": {"added_by_newer_writer": 1},
                    "pending_question": {"added_by_newer_writer": 1},
                    "workflow_state": {
                        "cl_name": "myproj",
                        "added_by_newer_writer": 1,
                        "steps": [
                            {"name": "main", "added_by_newer_writer": 1},
                        ],
                    },
                    "plan_path": {"added_by_newer_writer": 1},
                    "prompt_steps": [
                        {
                            "file_name": "prompt_step_main.json",
                            "added_by_newer_writer": 1,
                        }
                    ],
                    "raw_prompt_snippet": None,
                    "has_done_marker": True,
                }
            ],
        }
    )

    record = snapshot.records[0]
    assert record.done is not None
    assert record.done.outcome == "completed"
    assert record.done.cl_name == "myproj"
    assert record.running is not None
    assert record.running.pid == 123
    assert record.agent_meta is not None
    assert record.agent_meta.name == "producer"
    assert record.workflow_state is not None
    assert record.workflow_state.cl_name == "myproj"
    assert [step.name for step in record.workflow_state.steps] == ["main"]
    assert [step.file_name for step in record.prompt_steps] == ["prompt_step_main.json"]
    assert not hasattr(record.done, "added_by_newer_writer")


def _record_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_name": "myproj",
        "project_dir": "/tmp/projects/myproj",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "workflow_dir_name": "ace-run",
        "artifact_dir": "/tmp/projects/myproj/artifacts/ace-run/20260601010101",
        "timestamp": "20260601010101",
        "has_done_marker": True,
    }
    payload.update(overrides)
    return payload


def test_used_xprompts_round_trip_survives_the_json_projection() -> None:
    """Index staleness is diffed on the projected dict, so it must carry usage.

    ``verify_agent_artifact_index`` compares a fresh scan against the cached
    index through :func:`agent_scan_wire_to_json_dict`. Dropping
    ``used_xprompts`` here would report a row seeded with a late
    ``xprompts.json`` as fresh even though the cached projection is empty.
    """
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [
                _record_payload(
                    used_xprompts=[
                        {
                            "name": "gh",
                            "kind": "workflow",
                            "tags": ["rollover", "vcs"],
                            "references": 2,
                            "added_by_newer_writer": 1,
                        },
                        {"name": "split_file", "kind": "part", "references": 1},
                    ]
                )
            ],
        }
    )

    record = snapshot.records[0]
    assert [used.name for used in record.used_xprompts] == ["gh", "split_file"]
    assert record.used_xprompts[0].kind == "workflow"
    assert record.used_xprompts[0].tags == ["rollover", "vcs"]
    assert record.used_xprompts[0].references == 2
    assert record.used_xprompts[1].tags == []
    assert not hasattr(record.used_xprompts[0], "added_by_newer_writer")

    projected = agent_scan_wire_to_json_dict(record)
    assert projected["used_xprompts"] == [
        {
            "name": "gh",
            "kind": "workflow",
            "tags": ["rollover", "vcs"],
            "references": 2,
        },
        {"name": "split_file", "kind": "part", "tags": [], "references": 1},
    ]


def test_used_xprompts_defaults_to_empty_for_older_payloads() -> None:
    """An older core build reports no usage rather than failing the scan."""
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [_record_payload(), _record_payload(used_xprompts=None)],
        }
    )

    assert [record.used_xprompts for record in snapshot.records] == [[], []]


def test_monitor_marker_fields_round_trip() -> None:
    """Monitor family members must survive the agent artifact scan."""
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [
                _record_payload(
                    agent_meta={
                        "name": "acme--mon",
                        "agent_family": "acme",
                        "agent_family_role": "monitor",
                        "monitor_id": "m4kq",
                        "monitor_command": "just check-full",
                        "monitor_cwd": "/home/bryan/workspaces/acme",
                        "monitor_label": "just check-full",
                        "monitor_reason": "Verify the refactor",
                        "monitor_next_action": "Reply to the user.",
                        "monitor_start_status": "MONITORING",
                        "monitor_stop_status": "MONITORED",
                        "monitor_timeout_seconds": 2700.0,
                        "monitor_state": "running",
                        "monitor_exit_code": None,
                        "monitor_output_path": "live_reply.md",
                        "monitor_output_truncated": True,
                        "monitor_starter_agent": "acme--0",
                        "monitor_followup_agent": None,
                        "monitor_tail_lines": 200,
                        "monitor_pgid": 4242,
                        "monitor_supervisor_identity": "boot-abc123:98765",
                        "monitor_settled": True,
                        "monitor_idle_timeout_seconds": 600.0,
                        "monitor_next_output": "tail",
                        "monitor_request_fingerprint": "sha256:deadbeef",
                    },
                    done={
                        "outcome": "monitored",
                        "monitor_state": "completed",
                        "monitor_exit_code": 0,
                        "monitor_elapsed_seconds": 17.5,
                        "status_label": "MONITORED",
                    },
                )
            ],
        }
    )

    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.monitor_id == "m4kq"
    assert record.agent_meta.monitor_command == "just check-full"
    assert record.agent_meta.monitor_state == "running"
    assert record.agent_meta.monitor_output_truncated is True
    assert record.agent_meta.monitor_tail_lines == 200
    assert record.agent_meta.monitor_pgid == 4242
    assert record.agent_meta.monitor_supervisor_identity == "boot-abc123:98765"
    assert record.agent_meta.monitor_settled is True
    assert record.agent_meta.monitor_idle_timeout_seconds == 600.0
    assert record.agent_meta.monitor_next_output == "tail"
    assert record.agent_meta.monitor_request_fingerprint == "sha256:deadbeef"
    assert record.done is not None
    assert record.done.monitor_state == "completed"
    assert record.done.monitor_exit_code == 0
    assert record.done.monitor_elapsed_seconds == 17.5
    assert record.done.status_label == "MONITORED"

    payload = agent_scan_wire_to_json_dict(snapshot)
    meta_payload = payload["records"][0]["agent_meta"]
    assert meta_payload["monitor_id"] == "m4kq"
    assert meta_payload["monitor_state"] == "running"
    assert meta_payload["monitor_pgid"] == 4242
    assert meta_payload["monitor_supervisor_identity"] == "boot-abc123:98765"
    assert meta_payload["monitor_settled"] is True
    assert meta_payload["monitor_idle_timeout_seconds"] == 600.0
    assert meta_payload["monitor_next_output"] == "tail"
    assert meta_payload["monitor_request_fingerprint"] == "sha256:deadbeef"
    done_payload = payload["records"][0]["done"]
    assert done_payload["monitor_state"] == "completed"
    assert done_payload["status_label"] == "MONITORED"


def test_monitor_marker_fields_default_for_older_records() -> None:
    """A record from a pre-monitor core/agent must still parse cleanly."""
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [
                _record_payload(
                    agent_meta={"name": "pre-monitor-agent"},
                    done={"outcome": "completed", "cl_name": "myproj"},
                )
            ],
        }
    )

    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.monitor_id is None
    assert record.agent_meta.monitor_state is None
    assert record.agent_meta.monitor_output_truncated is False
    assert record.agent_meta.monitor_pgid is None
    assert record.agent_meta.monitor_supervisor_identity is None
    assert record.agent_meta.monitor_settled is False
    assert record.agent_meta.monitor_idle_timeout_seconds is None
    assert record.agent_meta.monitor_next_output is None
    assert record.agent_meta.monitor_request_fingerprint is None
    assert record.done is not None
    assert record.done.monitor_state is None
    assert record.done.monitor_exit_code is None
    assert record.done.status_label is None


def test_fixture_summary_matches_expectations() -> None:
    """Pin the fixture's surface area so adding a branch forces a test update."""
    summary = fixture_summary()
    assert summary["timestamps"] == list(EXPECTED_TIMESTAMPS)
    assert summary["expected_decode_errors"] == EXPECTED_DECODE_ERRORS
    assert summary["expected_os_errors"] == EXPECTED_OS_ERRORS
