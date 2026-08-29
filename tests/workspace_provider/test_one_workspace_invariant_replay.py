"""Regression replay for the one-workspace-per-family incident shape."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.agent.pending_handoff import MONITOR_PENDING_MARKER
from sase.logs.workspace_claim_ledger import read_ledger_records
from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
from sase.monitor.start_claim import claim_monitor_workspace
from sase.running_field import (
    WorkspaceClaim,
    claim_next_axe_workspace,
    get_claimed_workspaces,
)
from sase.workspace_provider.occupant import (
    new_occupant_record,
    read_occupant_record,
    write_occupant_record,
)
from sase.workspace_provider.vcs_release import SKIP_HANDOFF, release_vcs_workspace
from tests._running_field_helpers import create_project_file_with_running


def test_gate_vcs_monitor_handoff_keeps_one_claim_and_blocks_reallocation(
    tmp_path: Path,
) -> None:
    starter_pid = 1001
    monitor_pid = 1002
    later_pid = 1003
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                23,
                "ace(run)-launcher",
                "feature",
                pid=starter_pid,
                artifacts_timestamp="20260828165831",
            )
        ],
    )
    checkout = tmp_path / "project_23"
    checkout.mkdir()
    write_occupant_record(
        str(checkout),
        new_occupant_record(
            pid=starter_pid,
            workflow="ace(run)-launcher",
            project="project",
            workspace_num=23,
            agent_name="starter--code",
            cl_name="feature",
        ),
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / MONITOR_PENDING_MARKER).write_text("{}", encoding="utf-8")
    ledger_file = str(tmp_path / "workspace_claims.jsonl")

    with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
        monitor_claim = claim_monitor_workspace(
            project_file,
            23,
            supervisor_pid=monitor_pid,
            transfer_from_pid=starter_pid,
            artifacts_timestamp="20260828172034",
            cl_name="feature",
        )
        release_result = release_vcs_workspace(
            project_file=project_file,
            workspace_num=23,
            workspace_dir=str(checkout),
            workflow_name="gh-gh_project",
            cl_name="feature",
            caller_tag="gh-release",
            runner_pid=starter_pid,
            artifacts_dir=str(artifacts),
        )
        later_workspace = claim_next_axe_workspace(
            project_file,
            "ace(run)-later",
            later_pid,
            cl_name="later",
            min_workspace=23,
            max_workspace=24,
            caller_tag="pool-allocation",
        )
        records = read_ledger_records(ledger_file=ledger_file)

    assert monitor_claim.result.success is True
    assert release_result.skip_reason == SKIP_HANDOFF
    assert later_workspace == 24

    claims = sorted(
        get_claimed_workspaces(project_file), key=lambda claim: claim.workspace_num
    )
    assert [(claim.pid, claim.workspace_num, claim.workflow) for claim in claims] == [
        (monitor_pid, 23, MONITOR_WORKSPACE_CLAIM_WORKFLOW),
        (later_pid, 24, "ace(run)-later"),
    ]
    assert len({claim.workspace_num for claim in claims}) == len(claims)
    assert all(
        len({claim.workspace_num for claim in claims if claim.pid == candidate.pid})
        == 1
        for candidate in claims
    )

    occupant = read_occupant_record(str(checkout))
    assert occupant is not None
    assert occupant.pid == starter_pid
    assert any(record["operation"] == "transfer" for record in records)
    assert any(
        record["caller_tag"] == "gh-release"
        and record["success"] is False
        and "handed off" in (record["error"] or "")
        for record in records
    )
    assert any(
        record["caller_tag"] == "pool-allocation" and record["workspace_num"] == 24
        for record in records
    )
