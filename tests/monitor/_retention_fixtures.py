"""Shared retention-test helpers for monitor workspace-retention tests.

Public helpers live here so the split ``test_monitor_retention_*`` modules can
share them without importing ``_``-private names across test modules.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from sase.continuation_capture.rollout import (
    MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
)
from sase.monitor.followup import FollowupLaunchResult
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, write_project_file

RETENTION_CLAIM_WORKFLOW = "ace-monitor"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def init_retention_repo(path: Path, *, dirty: bool = False) -> Path:
    """Create a git repo at *path*, optionally with uncommitted dirt."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "sase-test@example.invalid")
    _git(path, "config", "user.name", "SASE Test")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "init")
    if dirty:
        (path / "tracked.txt").write_text("session owned\n", encoding="utf-8")
    return path


def make_retention_monitor(
    repo: Path,
    *,
    monitor_state: str = "stopped",
    next_action: str | None = None,
    protocol: str = MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
    outcome: str | None = None,
    degraded_reason: str | None = None,
    workspace_num: int = 3,
) -> tuple[str, str]:
    """Build a monitor artifacts dir plus project file for *repo*."""
    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(
                workspace_num,
                RETENTION_CLAIM_WORKFLOW,
                "acme",
                pid=os.getpid(),
                artifacts_timestamp="20260906120000",
            )
        ],
    )
    artifacts_dir = make_starter_agent(
        "proj",
        "20260906120000",
        "acme--mon",
        agent_session="acme",
        agent_session_role="monitor",
        monitor_id="abc123def456",
        monitor_command="true",
        monitor_cwd=str(repo),
        monitor_reason="test",
        monitor_start_status="MONITORING",
        monitor_stop_status="MONITORED",
        monitor_timeout_seconds=30.0,
        monitor_state="running",
        cl_name="acme",
        workspace_dir=str(repo),
        workspace_num=workspace_num,
        pid=os.getpid(),
        monitor_continuation_protocol=protocol,
        **({"monitor_next_action": next_action} if next_action else {}),
        **({"monitor_followup_outcome": outcome} if outcome else {}),
        **(
            {"monitor_followup_degraded_reason": degraded_reason}
            if degraded_reason
            else {}
        ),
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["monitor_state"] = monitor_state
    meta_path.write_text(json.dumps(meta))
    return artifacts_dir, project_file


def read_retention_meta(artifacts_dir: str) -> dict:
    """Read the monitor ``agent_meta.json`` for *artifacts_dir*."""
    return json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())


def write_retention_meta(artifacts_dir: str, meta: dict) -> None:
    """Write the monitor ``agent_meta.json`` for *artifacts_dir*."""
    (Path(artifacts_dir) / "agent_meta.json").write_text(json.dumps(meta))


def retention_record(artifacts_dir: str) -> dict | None:
    """Read the terminal workspace-retention record, if present."""
    path = Path(artifacts_dir) / "diagnostics" / "workspace_retention.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def no_launch_followup(*_args: object, **_kwargs: object) -> FollowupLaunchResult:
    """Follow-up launcher that asserts no launch was attempted."""
    raise AssertionError("no follow-up launch expected")


def persist_retention_delivery(
    artifacts_dir: str,
    meta: dict,
    *,
    agent: str,
    disposition: str,
    result_id: str | None = None,
    branch: str = "failed",
    degraded: bool = False,
) -> None:
    """Persist a delivery record for successor-proof tests."""
    from sase.monitor.delivery import (
        new_delivery_record,
        persist_delivery_record,
        transition_delivery,
    )

    key = {
        "monitor_id": str(meta.get("monitor_id") or "abc123def456"),
        "result_id": result_id
        or str(
            meta.get("monitor_result_id")
            or meta.get("continuation_monitor_result_id")
            or "result"
        ),
        "branch": branch,
    }
    record = new_delivery_record(key, selected_action="continue")
    reserved = transition_delivery(record, "reserved", reserved_identity=agent)
    if disposition == "reserved":
        persist_delivery_record(artifacts_dir, reserved)
        return
    current = transition_delivery(reserved, "dispatching")
    if disposition == "dispatching":
        if degraded:
            current = transition_delivery(
                current, "dispatching", workspace_degraded=True
            )
        persist_delivery_record(artifacts_dir, current)
        return
    current = transition_delivery(
        current,
        "acknowledged",
        acknowledged_by=agent,
        workspace_degraded=degraded,
    )
    if disposition == "acknowledged":
        persist_delivery_record(artifacts_dir, current)
        return
    current = transition_delivery(current, "settled")
    persist_delivery_record(artifacts_dir, current)


def transfer_retention_to_successor(
    project_file: str,
    repo: Path,
    *,
    from_pid: int,
    to_pid: int,
    timestamp: str,
) -> None:
    """Move the workspace claim and occupant to a successor process."""
    from sase.running_field import transfer_workspace_claim
    from sase.workspace_provider.occupant import (
        new_occupant_record,
        write_occupant_record,
    )

    result = transfer_workspace_claim(
        project_file,
        3,
        from_pid=from_pid,
        to_pid=to_pid,
        new_workflow="ace-run",
        new_artifacts_timestamp=timestamp,
        cl_name="acme",
    )
    assert result.success is True
    write_occupant_record(
        str(repo),
        new_occupant_record(
            pid=to_pid,
            workflow="ace-run",
            project="proj",
            workspace_num=3,
            artifacts_timestamp=timestamp,
            agent_name="acme--mon@1",
            cl_name="acme",
        ),
    )


def write_opened_linked(artifacts_dir: str, name: str, workspace_dir: Path) -> None:
    """Write an opened-linked-workspaces marker covering *workspace_dir*."""
    payload = {
        "schema_version": 3,
        "linked_repos": [
            {
                "name": name,
                "workspace_dir": str(workspace_dir),
                "reason": "test",
                "opened_at": "",
                "kind": "linked",
            }
        ],
    }
    (Path(artifacts_dir) / "opened_linked_workspaces.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def pending_retention_record(artifacts_dir: str) -> dict | None:
    """Read the pending-retention fact, if present."""
    from sase.turns.workspace_retention_pending import PENDING_RETENTION_LOCATOR

    path = Path(artifacts_dir) / PENDING_RETENTION_LOCATOR
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fail_fresh_python_c(exc: BaseException):
    """Return a ``subprocess.run`` wrapper that fails ``python -c`` attempts."""
    real_run = subprocess.run

    def _run(argv: object, *args: object, **kwargs: object) -> object:
        command = list(argv) if isinstance(argv, (list, tuple)) else []
        if len(command) > 1 and str(command[1]) == "-c":
            raise exc
        return real_run(argv, *args, **kwargs)  # type: ignore[misc]

    return _run
