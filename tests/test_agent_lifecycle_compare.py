from __future__ import annotations

from sase.agent.running import RunningAgentInfo
from sase.agents.lifecycle_compare import compare_lifecycle_classifications
from sase.daemon.read_models import agent_list_from_dict


def test_projection_summary_preserves_lifecycle_edge_fields() -> None:
    page = agent_list_from_dict(
        {
            "snapshot": {"schema_version": 1, "snapshot_id": "snap-1"},
            "page": {"schema_version": 1, "next_cursor": None},
            "bounded": {"schema_version": 1, "max_payload_bytes": 1024},
            "entries": {
                "schema_version": 1,
                "entries": [
                    {
                        "schema_version": 1,
                        "agent_id": "agent:demo:20260514010101",
                        "project_id": "demo",
                        "project_name": "demo",
                        "project_dir": "/tmp/demo",
                        "project_file": "/tmp/demo/demo.sase",
                        "workflow_dir_name": "ace-run",
                        "artifact_dir": "/tmp/demo/artifacts/ace-run/20260514010101",
                        "timestamp": "20260514010101",
                        "status": "queued",
                        "agent_type": "agent",
                        "has_done_marker": False,
                        "has_running_marker": False,
                        "has_waiting_marker": False,
                        "has_workflow_state": False,
                        "batch_id": "batch-1",
                        "queue_id": "default",
                        "parent_agent_id": "agent:demo:parent",
                        "workflow_id": "wf-1",
                        "retry_of_agent_id": None,
                        "resume_of_agent_id": None,
                        "host_id": "host-a",
                        "pid": 1234,
                        "workspace_claim_id": "demo:7",
                        "last_heartbeat_at": "2026-05-14T01:01:02Z",
                        "last_check_at": "2026-05-14T01:01:03Z",
                        "lifecycle_changed_at": "2026-05-14T01:01:04Z",
                        "stale_reason": None,
                        "last_seq": 9,
                    }
                ],
            },
        }
    )

    summary = page.agents[0]
    assert summary.batch_id == "batch-1"
    assert summary.queue_id == "default"
    assert summary.parent_agent_id == "agent:demo:parent"
    assert summary.workflow_id == "wf-1"
    assert summary.pid == 1234
    assert summary.workspace_claim_id == "demo:7"


def test_lifecycle_compare_normalizes_python_and_projection_statuses() -> None:
    expected = [
        RunningAgentInfo(
            name="alpha",
            project="demo",
            pid=10,
            model=None,
            provider=None,
            workspace_num=None,
            duration="1s",
            approve=False,
            status="DONE",
            artifacts_dir="/tmp/demo/artifacts/ace-run/20260514010101",
        )
    ]
    observed = [
        agent_list_from_dict(
            {
                "snapshot": {"schema_version": 1, "snapshot_id": "snap-1"},
                "page": {"schema_version": 1, "next_cursor": None},
                "bounded": {"schema_version": 1, "max_payload_bytes": 1024},
                "entries": {
                    "schema_version": 1,
                    "entries": [
                        {
                            "schema_version": 1,
                            "agent_id": "agent:demo:20260514010101",
                            "project_id": "demo",
                            "project_name": "demo",
                            "project_dir": "/tmp/demo",
                            "project_file": "/tmp/demo/demo.sase",
                            "workflow_dir_name": "ace-run",
                            "artifact_dir": "/tmp/demo/artifacts/ace-run/20260514010101",
                            "timestamp": "20260514010101",
                            "status": "completed",
                            "agent_type": "agent",
                            "agent_name": "alpha",
                            "has_done_marker": True,
                            "last_seq": 2,
                        }
                    ],
                },
            }
        ).agents[0]
    ]

    assert compare_lifecycle_classifications(expected, observed).clean
