from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.agents_sync.agent_state_refresh import run_agent_state_refresh
from tests.agents_sync._agent_state_refresh_test_support import (
    inventory_run,
    owner_identity,
    repair_with,
    setup_refresh_repo,
    targets_for,
)


def _remote_state(remote: Path, global_name: str) -> str:
    verify = remote.parent / f"verify-{global_name.replace('.', '-')}"
    if verify.exists():
        subprocess.run(["rm", "-rf", str(verify)], check=True)
    subprocess.run(["git", "clone", "--quiet", str(remote), str(verify)], check=True)
    payload = json.loads((verify / "agents" / global_name / "state.json").read_text())
    return str(payload["state"])


def test_scheduled_convergence_without_another_commit(tmp_path: Path) -> None:
    remote, sync_target = setup_refresh_repo(
        tmp_path,
        runs=[
            ("aaa", "aaa.job", "run-aaa", "active"),
            ("mmm", "mmm.job", "run-mmm", "active"),
            ("zzz", "zzz.job", "run-zzz", "waiting"),
        ],
    )
    state_dir = tmp_path / "state"
    evidence = [
        inventory_run("run-aaa", "aaa.job", "waiting"),
        inventory_run("run-mmm", "mmm.job", "completed"),
        inventory_run("run-zzz", "zzz.job", "failed"),
    ]
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=remote,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # Irreparable early rows must not starve later rows: page one row at a
    # time through the scheduled path, restarting the scheduler between ticks.
    for _ in range(3):
        summary = run_agent_state_refresh(
            state_dir=state_dir,
            list_targets=targets_for([sync_target]),
            require_owner=owner_identity,
            repair_one=repair_with(evidence),
            state_limit=1,
        )
        assert summary.errors == 0

    assert _remote_state(remote, "alice.athena.mmm.job") == "completed"
    assert _remote_state(remote, "alice.athena.zzz.job") == "failed"
    assert _remote_state(remote, "alice.athena.aaa.job") == "active"

    snapshot = json.loads(
        (
            sync_target.sidecar_path
            / "users"
            / "alice"
            / "machines"
            / "athena"
            / "hoods"
            / "mmm"
            / "snapshot.json"
        ).read_text()
    )
    assert snapshot["runs"][0]["state"] == "completed"
    manifest = json.loads(
        (
            sync_target.sidecar_path
            / "users"
            / "alice"
            / "machines"
            / "athena"
            / "manifest.json"
        ).read_text()
    )
    assert manifest["hoods"]["mmm"]["run_count"] == 1
    assert (
        sync_target.sidecar_path / "agents" / "alice.athena.mmm.job" / "README.md"
    ).is_file()
    # No full sync or commit workflow ran: the seed commit is still HEAD plus
    # exactly the scheduled repair commits, and the Sibling live run stays live.
    after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=remote,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert before != after

    # A second full pass is a no-op: terminal rows are already current.
    final = run_agent_state_refresh(
        state_dir=state_dir,
        list_targets=targets_for([sync_target]),
        require_owner=owner_identity,
        repair_one=repair_with(evidence),
    )
    assert final.changed == 0
    assert final.pass_complete is True
