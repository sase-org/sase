from __future__ import annotations

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
    assert AGENT_SCAN_WIRE_SCHEMA_VERSION == 1
    assert AGENT_ARTIFACT_INDEX_SCHEMA_VERSION == 10


def test_artifact_index_wire_helpers() -> None:
    assert AgentArtifactIndexQueryWire().active_limit is None

    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=False,
        include_full_history=True,
        active_limit=50,
        recent_completed_limit=None,
        include_hidden=True,
    )
    assert agent_artifact_index_query_to_dict(query) == {
        "include_active": True,
        "include_recent_completed": False,
        "include_full_history": True,
        "active_limit": 50,
        "recent_completed_limit": None,
        "include_hidden": True,
    }

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
                        "agent_family_parallel": True,
                        "output_path": "/tmp/producer.log",
                        "linked_repos": [
                            {
                                "name": "sase-core",
                                "workspace_dir": "/tmp/sase-core_7",
                                "workspace_strategy": "suffix",
                            }
                        ],
                        "output_variables": {
                            "report_path": "/tmp/report.md",
                            "status": "ok",
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
    assert record.agent_meta.output_variables == {
        "report_path": "/tmp/report.md",
        "status": "ok",
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
    assert payload["records"][0]["agent_meta"]["linked_repos"] == [
        {
            "name": "sase-core",
            "workspace_dir": "/tmp/sase-core_7",
            "workspace_strategy": "suffix",
        }
    ]
    assert payload["records"][0]["agent_meta"]["output_variables"] == {
        "report_path": "/tmp/report.md",
        "status": "ok",
    }
    assert payload["records"][0]["agent_meta"]["agent_family_parallel"] is True
    assert payload["records"][0]["agent_meta"]["output_path"] == "/tmp/producer.log"


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


def test_fixture_summary_matches_expectations() -> None:
    """Pin the fixture's surface area so adding a branch forces a test update."""
    summary = fixture_summary()
    assert summary["timestamps"] == list(EXPECTED_TIMESTAMPS)
    assert summary["expected_decode_errors"] == EXPECTED_DECODE_ERRORS
    assert summary["expected_os_errors"] == EXPECTED_OS_ERRORS
