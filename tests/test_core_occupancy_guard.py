"""Tests for sase.core.occupancy_guard (guard phase of sase-q0)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from sase.core.occupancy_guard import (
    OccupancyCaller,
    WorkspaceOccupiedError,
    ensure_workspace_not_occupied,
)
from sase.running_field import WorkspaceClaim
from sase.workspace_provider.occupant import new_occupant_record, write_occupant_record


def _create_project_file_with_running(
    tmp_path: Path,
    running_claims: list[WorkspaceClaim] | None = None,
) -> str:
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".sase"
    ) as f:
        f.write("# Test Project\n\n")
        if running_claims:
            f.write("RUNNING:\n")
            for claim in running_claims:
                f.write(claim.to_line() + "\n")
        f.write("NAME: Test Feature\n")
        f.write("DESCRIPTION:\n")
        f.write("  Test description\n")
        f.write("PARENT: None\n")
        f.write("PR: None\n")
        f.write("STATUS: Ready\n")
        return f.name


def _caller(pid: int, workspace_num: int = 17) -> OccupancyCaller:
    return OccupancyCaller(
        pid=pid,
        workspace_num=workspace_num,
        project="sase",
        workflow="ace(run)-260818_120000",
        artifacts_timestamp="20260818T120000",
    )


def _dead_pid() -> int:
    """Return a pid that is guaranteed not to be alive right now."""
    proc = os.fork() if hasattr(os, "fork") else None
    if proc is None:
        pytest.skip("os.fork unavailable on this platform")
    if proc == 0:  # pragma: no cover - child branch
        os._exit(0)
    os.waitpid(proc, 0)
    return proc


class TestEnsureWorkspaceNotOccupied:
    def test_proceeds_when_no_occupant_record(self, tmp_path: Path) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        project_file = _create_project_file_with_running(tmp_path)

        ensure_workspace_not_occupied(
            str(checkout), project_file=project_file, caller=_caller(os.getpid())
        )

    def test_proceeds_when_occupant_is_caller(self, tmp_path: Path) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        project_file = _create_project_file_with_running(tmp_path)
        pid = os.getpid()
        write_occupant_record(
            str(checkout),
            new_occupant_record(
                pid=pid, workflow="w", project="sase", workspace_num=17
            ),
        )

        ensure_workspace_not_occupied(
            str(checkout), project_file=project_file, caller=_caller(pid)
        )

    def test_proceeds_when_occupant_pid_is_dead(self, tmp_path: Path) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        project_file = _create_project_file_with_running(tmp_path)
        dead_pid = _dead_pid()
        write_occupant_record(
            str(checkout),
            new_occupant_record(
                pid=dead_pid, workflow="w", project="sase", workspace_num=17
            ),
        )

        ensure_workspace_not_occupied(
            str(checkout), project_file=project_file, caller=_caller(os.getpid())
        )

    def test_refuses_when_occupant_is_live_other_pid(self, tmp_path: Path) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        other_pid = os.getppid()
        project_file = _create_project_file_with_running(
            tmp_path,
            [
                WorkspaceClaim(
                    workspace_num=17,
                    workflow="w",
                    cl_name="demo",
                    pid=other_pid,
                    artifacts_timestamp="ts",
                )
            ],
        )
        write_occupant_record(
            str(checkout),
            new_occupant_record(
                pid=other_pid,
                workflow="w",
                project="sase",
                workspace_num=17,
                agent_name="rival-agent",
            ),
        )

        with pytest.raises(WorkspaceOccupiedError, match="rival-agent"):
            ensure_workspace_not_occupied(
                str(checkout), project_file=project_file, caller=_caller(os.getpid())
            )

    def test_proceeds_on_missing_occupant_file_when_checkout_absent(
        self, tmp_path: Path
    ) -> None:
        """A missing occupant marker is always "unoccupied", even for a
        checkout directory that does not even exist yet — pre-guard
        checkouts must never be bricked."""
        checkout = tmp_path / "never-created"
        project_file = _create_project_file_with_running(tmp_path)

        ensure_workspace_not_occupied(
            str(checkout), project_file=project_file, caller=_caller(os.getpid())
        )
