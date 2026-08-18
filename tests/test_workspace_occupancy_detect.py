"""Detect-phase regression tests for workspace exclusivity (sase-q0.4).

These tests drive the real ProjectSpec lock: concurrent allocation must never
hand the same workspace number to two agents, and the incident shape (A holds
N, B takes a deferred claim) must both skip N and refuse destructive prep if
B somehow landed on N anyway.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import threading
from unittest.mock import patch

import pytest

from sase.core.occupancy_guard import WorkspaceOccupiedError
from sase.running_field import (
    WorkspaceClaim,
    claim_next_axe_workspace,
    get_claimed_workspaces,
)
from sase.workspace_provider.occupant import new_occupant_record, write_occupant_record


def _write_project_file(
    tmp_path: Path, running_claims: list[WorkspaceClaim] | None = None
) -> str:
    project_file = tmp_path / "project.sase"
    lines = ["# Test Project\n"]
    if running_claims:
        lines.append("RUNNING:\n")
        for claim in running_claims:
            lines.append(claim.to_line() + "\n")
    lines.extend(["NAME: Test Feature\n", "STATUS: Ready\n"])
    project_file.write_text("".join(lines), encoding="utf-8")
    return str(project_file)


def test_concurrent_launcher_and_deferred_claims_never_share_a_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simultaneous launcher + deferred bursts must not double-claim a number."""
    project_file = _write_project_file(tmp_path)
    ledger_file = str(tmp_path / "workspace_claims.jsonl")
    monkeypatch.setattr("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file)

    def fake_workspace_dir(
        workspace_num: int, _project: str, *, clean: bool = True
    ) -> tuple[str, None]:
        checkout = tmp_path / f"ws{workspace_num}"
        checkout.mkdir(exist_ok=True)
        return str(checkout), None

    launcher_count = 4
    deferred_count = 4
    total = launcher_count + deferred_count
    start = threading.Barrier(total)

    def launcher_claim(index: int) -> int:
        start.wait()
        return claim_next_axe_workspace(
            project_file,
            f"ace(run)-launcher-{index}",
            os.getpid(),
            cl_name=f"launcher-{index}",
            artifacts_timestamp=f"260818_13000{index}",
            caller_tag="launcher-preclaim",
        )

    def deferred_claim(index: int) -> int:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        start.wait()
        num, _dir = claim_deferred_workspace(
            project_file,
            "test-project",
            f"ace(run)-deferred-{index}",
            f"deferred-{index}",
            f"260818_13100{index}",
        )
        return num

    with (
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            side_effect=fake_workspace_dir,
        ),
        patch("sase.axe.run_agent_phases.os.chdir"),
        patch("sase.linked_repos.apply_linked_repo_env"),
        patch(
            "sase.linked_repos.resolve_linked_repos_for_project",
            return_value=(),
        ),
        patch("sase.sdd.env.set_sdd_dir_env"),
        ThreadPoolExecutor(max_workers=total) as pool,
    ):
        launcher_futures = [
            pool.submit(launcher_claim, i) for i in range(launcher_count)
        ]
        deferred_futures = [
            pool.submit(deferred_claim, i) for i in range(deferred_count)
        ]
        claimed = [future.result() for future in launcher_futures + deferred_futures]

    assert len(claimed) == total
    assert len(set(claimed)) == total
    rows = get_claimed_workspaces(project_file)
    numbered = [claim.workspace_num for claim in rows if claim.workspace_num > 0]
    assert sorted(numbered) == sorted(claimed)
    assert len(numbered) == len(set(numbered))
    assert len(set(numbered)) == len(claimed)


def test_deferred_claim_skips_held_workspace_and_guard_blocks_stolen_prep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Incident shape: A holds N; B's deferred claim does not get N.

    If B somehow did land on N, the occupancy guard must still refuse
    destructive preparation before any git mutation.
    """
    from sase.axe.run_agent_phases import claim_deferred_workspace
    from sase.axe.run_agent_runner_setup import prepare_workspace_if_needed

    occupant_pid = os.getppid()
    held = WorkspaceClaim(
        17,
        "ace(run)-260818_125956",
        "06e--plan",
        pid=occupant_pid,
        artifacts_timestamp="260818_125956",
    )
    project_file = _write_project_file(tmp_path, running_claims=[held])
    ledger_file = str(tmp_path / "workspace_claims.jsonl")
    monkeypatch.setattr("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file)

    held_checkout = tmp_path / "ws17"
    held_checkout.mkdir()
    write_occupant_record(
        str(held_checkout),
        new_occupant_record(
            pid=occupant_pid,
            workflow="ace(run)-260818_125956",
            project="sase",
            workspace_num=17,
            artifacts_timestamp="260818_125956",
            agent_name="06e--plan",
            cl_name="06e--plan",
        ),
    )

    def fake_workspace_dir(
        workspace_num: int, _project: str, *, clean: bool = True
    ) -> tuple[str, None]:
        assert workspace_num != 17
        checkout = tmp_path / f"ws{workspace_num}"
        checkout.mkdir(exist_ok=True)
        return str(checkout), None

    with (
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            side_effect=fake_workspace_dir,
        ),
        patch("sase.axe.run_agent_phases.os.chdir"),
        patch("sase.linked_repos.apply_linked_repo_env"),
        patch(
            "sase.linked_repos.resolve_linked_repos_for_project",
            return_value=(),
        ),
        patch("sase.sdd.env.set_sdd_dir_env"),
    ):
        workspace_num, workspace_dir = claim_deferred_workspace(
            project_file,
            "sase",
            "ace(run)-260818_130227",
            "sase-pv.4",
            "260818_130227",
        )

    assert workspace_num != 17
    assert workspace_dir == str(tmp_path / f"ws{workspace_num}")
    claimed_nums = {
        claim.workspace_num for claim in get_claimed_workspaces(project_file)
    }
    assert 17 in claimed_nums
    assert workspace_num in claimed_nums

    with (
        patch("sase.axe.run_agent_runner_setup.prepare_workspace") as prepare,
        pytest.raises(WorkspaceOccupiedError, match="06e--plan"),
    ):
        prepare_workspace_if_needed(
            workspace_dir=str(held_checkout),
            workspace_num=17,
            cl_name="sase-pv.4",
            update_target="origin/master",
            project_name="sase",
            project_file=project_file,
            workflow_name="ace(run)-260818_130227",
            artifacts_timestamp="260818_130227",
            is_home_mode=False,
            retry_handoff=None,
        )
    prepare.assert_not_called()
