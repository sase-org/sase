"""Shared helpers for approved-epic launch tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.bead.epic_launch import start_epic_launch_monitor
from sase.workspace_provider.lease import OperationalLease
from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    OperationContext,
)


def fake_lease(tmp_path: Path, *, claim_pid: int = 4321) -> OperationalLease:
    checkout = tmp_path / "leased"
    checkout.mkdir(exist_ok=True)
    context = OperationContext(
        project="sase",
        access_kind=AccessKind.LEASED_OPERATIONAL,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=10,
        checkout_dir=checkout,
        primary_checkout_dir=tmp_path / "primary",
        claim_pid=claim_pid,
        claim_workflow="epic-launch",
    )
    return OperationalLease(
        project="sase",
        workflow="epic-launch",
        holder="planner",
        workspace_num=10,
        checkout_dir=checkout,
        project_file=tmp_path / "sase.sase",
        claim_pid=claim_pid,
        cl_name=None,
        context=context,
    )


def start_epic_launch_monitor_request(
    tmp_path: Path,
    *,
    agent_meta: dict[str, object],
    plan: Path | None = None,
    artifacts: Path | None = None,
    cl_name: str | None = None,
) -> object:
    plan = plan if plan is not None else tmp_path / "child epic.md"
    artifacts = artifacts if artifacts is not None else tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(agent_meta) + "\n",
        encoding="utf-8",
    )
    monitor = SimpleNamespace(monitor_id="m7k2xyz")
    lease = fake_lease(tmp_path)
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[]),
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        ),
        patch("sase.workspace_provider.lease.release_operational_lease"),
        patch(
            "sase.monitor.start.start_monitor",
            return_value=monitor,
        ) as start_monitor,
    ):
        submitted = start_epic_launch_monitor(
            plan,
            project="sase",
            host_action_data={"agent_name": "sase-m6.6"},
            artifacts_dir=artifacts,
            cl_name=cl_name,
        )

    assert submitted is monitor
    return start_monitor.call_args.args[0]
