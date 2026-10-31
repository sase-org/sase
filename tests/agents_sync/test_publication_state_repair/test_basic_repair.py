"""Basic preview and state-transition repairs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.agents_sync.publication_state_repair import repair_project_run_states

from tests.agents_sync.test_publication_state_repair._helpers import (
    OWNER,
    inv_run,
    make_loader,
    remote_head,
    remote_state,
    setup_repair,
)


def test_preview_is_read_only_and_scoped(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path,
        runs=[
            ("aaa", "aaa.job", "run-aaa", "active"),
            ("zzz", "zzz.job", "run-zzz", "active"),
        ],
    )
    before = remote_head(remote)
    seen: list[frozenset[str]] = []
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=False,
        state_limit=1,
        inventory_loader=make_loader(
            [inv_run("run-aaa", "aaa.job", "completed")], seen
        ),
    )

    assert report.mode == "preview"
    assert report.examined == 1
    assert report.changed == 1
    assert report.committed is False and report.pushed is False
    # Scoped evidence reads cover only the selected window hood.
    assert seen == [frozenset({"aaa"})]
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=sync_target.sidecar_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    assert remote_head(remote) == before


def test_completed_repair_converges_remote_snapshot_manifest_and_pages(
    tmp_path: Path,
) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([inv_run("run-1", "foo.job", "completed")], []),
    )

    assert report.error is None
    assert (report.examined, report.changed) == (1, 1)
    assert report.committed and report.pushed
    assert report.next_cursor is not None and report.pass_complete is True
    assert remote_state(remote, "alice.athena.foo.job") == "completed"
    snapshot = json.loads(
        (
            sync_target.sidecar_path
            / "users"
            / "alice"
            / "machines"
            / "athena"
            / "hoods"
            / "foo"
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
    assert manifest["hoods"]["foo"]["run_count"] == 1
    assert (
        sync_target.sidecar_path / "agents" / "alice.athena.foo.job" / "README.md"
    ).is_file()
    # Hidden-clone ownership: the primary checkout is never written.
    assert list(sync_target.primary_checkout.iterdir()) == []


def test_failed_evidence_repairs_to_failed(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "waiting")]
    )
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([inv_run("run-1", "foo.job", "failed")], []),
    )

    assert report.error is None and report.changed == 1
    assert remote_state(remote, "alice.athena.foo.job") == "failed"


def test_dismissed_evidence_repairs_to_dismissed(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([inv_run("run-1", "foo.job", "dismissed")], []),
    )

    assert report.error is None and report.changed == 1
    assert remote_state(remote, "alice.athena.foo.job") == "dismissed"


def test_live_runs_stay_live_with_no_write_cursor_advance(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "waiting")]
    )
    before = remote_head(remote)
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([inv_run("run-1", "foo.job", "waiting")], []),
    )

    assert report.error is None
    assert (report.examined, report.changed, report.live) == (1, 0, 1)
    assert report.committed is False and report.pushed is False
    assert report.next_cursor is not None and report.pass_complete is True
    assert remote_head(remote) == before
    assert remote_state(remote, "alice.athena.foo.job") == "waiting"


def test_unresolvable_rows_leave_state_unchanged(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    before = remote_head(remote)
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([], []),
    )

    assert report.error is None
    assert (report.examined, report.unresolved) == (1, 1)
    assert report.changed == 0
    assert remote_head(remote) == before
    assert remote_state(remote, "alice.athena.foo.job") == "active"


def test_no_new_hood_enrollment(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader(
            [
                inv_run("run-1", "foo.job", "completed"),
                inv_run("run-new", "bar.job", "completed"),
            ],
            [],
        ),
    )

    assert report.error is None and report.changed == 1
    assert not (
        sync_target.sidecar_path
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "bar"
    ).exists()
    assert remote_state(remote, "alice.athena.foo.job") == "completed"
