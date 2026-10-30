"""Bounded report-and-apply repair for already-published run states."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from pathlib import Path

import pytest

from sase.agents_sync.git import run_git
from sase.agents_sync.inventory_models import InventoryRun, ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_state_repair import (
    STATE_REPAIR_MAX_HOODS,
    repair_project_run_states,
)
from sase.agents_sync.v2_io import content_digest, file_reference, v2_json_bytes
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2RunRecord,
    V2RunStatePayload,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests.agents_sync.git_sync_fixtures import git, setup_repo, target

OWNER = AgentOwnerIdentity("alice", "athena")
PROJECT = V2ProjectIdentity("proj", "Project")
STARTED = "2026-07-23T12:00:00+00:00"
FINISHED = "2026-07-23T12:01:00+00:00"


def _global(local: str, owner: AgentOwnerIdentity = OWNER) -> str:
    return f"{owner.username}.{owner.machine_name}.{local}"


def _inv_run(
    source_run_id: str,
    local: str,
    state: str,
    *,
    owner: AgentOwnerIdentity = OWNER,
    finished: str | None = None,
    label: str = "artifact",
) -> InventoryRun:
    return InventoryRun(
        source_run_id,
        local,
        _global(local, owner),
        state,
        STARTED,
        finished,
        finished if state == "dismissed" else None,
        (),
        (),
        None,
        None,
        None,
        None,
        (),
        "20260723120000",
        source_label=label,
    )


class _SeedBuilder:
    """Write consistent published snapshots, state files, and manifests."""

    def __init__(
        self,
        sidecar: Path,
        owner: AgentOwnerIdentity = OWNER,
        project: V2ProjectIdentity = PROJECT,
    ) -> None:
        self.sidecar = sidecar
        self.owner = owner
        self.project = project
        self.hoods: dict[str, list[V2RunRecord]] = {}

    def add_run(
        self,
        hood: str,
        local: str,
        source_run_id: str,
        state: str,
        *,
        finished: str | None = None,
    ) -> V2RunRecord:
        finished_at = finished or (None if state in ("active", "waiting") else FINISHED)
        payload = V2RunStatePayload(
            source_run_id,
            state,  # type: ignore[arg-type]
            STARTED,
            finished_at,
            finished_at if state == "dismissed" else None,
        )
        blob = v2_json_bytes(payload.to_json_dict())
        (self.sidecar / "agents" / _global(local, self.owner)).mkdir(
            parents=True, exist_ok=True
        )
        (
            self.sidecar / "agents" / _global(local, self.owner) / "state.json"
        ).write_bytes(blob)
        run = V2RunRecord(
            source_run_id,
            local,
            _global(local, self.owner),
            state,  # type: ignore[arg-type]
            STARTED,
            finished_at,
            finished_at if state == "dismissed" else None,
            (),
            (),
            (
                (
                    "state",
                    file_reference(
                        f"agents/{_global(local, self.owner)}/state.json", blob
                    ),
                ),
            ),
        )
        self.hoods.setdefault(hood, []).append(run)
        return run

    def add_corrupt_hood(self, hood: str, raw: bytes = b"{not json") -> None:
        path = (
            self.sidecar
            / "users"
            / self.owner.username
            / "machines"
            / self.owner.machine_name
            / "hoods"
            / hood
            / "snapshot.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def write_manifest(self, corrupt: dict[str, str] | None = None) -> None:
        entries: dict[str, V2OwnerHoodEntry] = {}
        for hood, runs in sorted(self.hoods.items()):
            ordered = tuple(sorted(runs, key=lambda item: item.source_run_id))
            snapshot = V2HoodSnapshot(
                self.owner,
                self.project,
                hood,
                _global(hood, self.owner),
                (_global(hood, self.owner),),
                ordered,
            )
            snapshot_bytes = v2_json_bytes(snapshot.to_json_dict())
            snapshot_path = (
                self.sidecar
                / "users"
                / self.owner.username
                / "machines"
                / self.owner.machine_name
                / "hoods"
                / hood
                / "snapshot.json"
            )
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_bytes(snapshot_bytes)
            entries[hood] = V2OwnerHoodEntry(
                content_digest(snapshot_bytes), None, len(ordered), 0
            )
        for hood, digest in (corrupt or {}).items():
            entries[hood] = V2OwnerHoodEntry(digest, None, 0, 0)
        manifest = V2OwnerManifest(
            self.owner, self.project, tuple(sorted(entries.items()))
        )
        manifest_path = (
            self.sidecar
            / "users"
            / self.owner.username
            / "machines"
            / self.owner.machine_name
            / "manifest.json"
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(v2_json_bytes(manifest.to_json_dict()))


def _commit_push(sidecar: Path, message: str = "seed published states") -> None:
    git(sidecar, "add", "-A")
    git(sidecar, "commit", "-m", message)
    git(sidecar, "push", "origin", "HEAD")


def _remote_head(remote: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=remote,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _remote_state(remote: Path, global_name: str) -> str:
    verify = remote.parent / f"verify-{global_name.replace('.', '-')}"
    if verify.exists():
        subprocess.run(["rm", "-rf", str(verify)], check=True)
    subprocess.run(["git", "clone", "--quiet", str(remote), str(verify)], check=True)
    payload = json.loads((verify / "agents" / global_name / "state.json").read_text())
    return str(payload["state"])


def _loader(runs: list[InventoryRun], seen: list[frozenset[str]]):
    def load(
        _target: ProjectTarget,
        _identity: AgentIdentitySnapshot,
        hoods: frozenset[str],
    ) -> ProjectHoodInventory:
        seen.append(hoods)
        return ProjectHoodInventory(OWNER, "proj", tuple(runs))

    return load


def _setup(
    tmp_path: Path, *, runs: list[tuple[str, str, str, str]]
) -> tuple[Path, ProjectTarget]:
    """Seed one owner hood per ``(hood, local, source_run_id, state)`` row."""

    remote, _seed, sidecar = setup_repo(tmp_path)
    builder = _SeedBuilder(sidecar)
    for hood, local, source_run_id, state in runs:
        builder.add_run(hood, local, source_run_id, state)
    builder.write_manifest()
    _commit_push(sidecar)
    return remote, target(tmp_path, remote, sidecar)


def test_preview_is_read_only_and_scoped(tmp_path: Path) -> None:
    remote, sync_target = _setup(
        tmp_path,
        runs=[
            ("aaa", "aaa.job", "run-aaa", "active"),
            ("zzz", "zzz.job", "run-zzz", "active"),
        ],
    )
    before = _remote_head(remote)
    seen: list[frozenset[str]] = []
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=False,
        state_limit=1,
        inventory_loader=_loader([_inv_run("run-aaa", "aaa.job", "completed")], seen),
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
    assert _remote_head(remote) == before


def test_completed_repair_converges_remote_snapshot_manifest_and_pages(
    tmp_path: Path,
) -> None:
    remote, sync_target = _setup(tmp_path, runs=[("foo", "foo.job", "run-1", "active")])
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([_inv_run("run-1", "foo.job", "completed")], []),
    )

    assert report.error is None
    assert (report.examined, report.changed) == (1, 1)
    assert report.committed and report.pushed
    assert report.next_cursor is not None and report.pass_complete is True
    assert _remote_state(remote, "alice.athena.foo.job") == "completed"
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
    remote, sync_target = _setup(
        tmp_path, runs=[("foo", "foo.job", "run-1", "waiting")]
    )
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([_inv_run("run-1", "foo.job", "failed")], []),
    )

    assert report.error is None and report.changed == 1
    assert _remote_state(remote, "alice.athena.foo.job") == "failed"


def test_dismissed_evidence_repairs_to_dismissed(tmp_path: Path) -> None:
    remote, sync_target = _setup(tmp_path, runs=[("foo", "foo.job", "run-1", "active")])
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([_inv_run("run-1", "foo.job", "dismissed")], []),
    )

    assert report.error is None and report.changed == 1
    assert _remote_state(remote, "alice.athena.foo.job") == "dismissed"


def test_live_runs_stay_live_with_no_write_cursor_advance(tmp_path: Path) -> None:
    remote, sync_target = _setup(
        tmp_path, runs=[("foo", "foo.job", "run-1", "waiting")]
    )
    before = _remote_head(remote)
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([_inv_run("run-1", "foo.job", "waiting")], []),
    )

    assert report.error is None
    assert (report.examined, report.changed, report.live) == (1, 0, 1)
    assert report.committed is False and report.pushed is False
    assert report.next_cursor is not None and report.pass_complete is True
    assert _remote_head(remote) == before
    assert _remote_state(remote, "alice.athena.foo.job") == "waiting"


def test_unresolvable_rows_leave_state_unchanged(tmp_path: Path) -> None:
    remote, sync_target = _setup(tmp_path, runs=[("foo", "foo.job", "run-1", "active")])
    before = _remote_head(remote)
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([], []),
    )

    assert report.error is None
    assert (report.examined, report.unresolved) == (1, 1)
    assert report.changed == 0
    assert _remote_head(remote) == before
    assert _remote_state(remote, "alice.athena.foo.job") == "active"


def test_no_new_hood_enrollment(tmp_path: Path) -> None:
    remote, sync_target = _setup(tmp_path, runs=[("foo", "foo.job", "run-1", "active")])
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader(
            [
                _inv_run("run-1", "foo.job", "completed"),
                _inv_run("run-new", "bar.job", "completed"),
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
    assert _remote_state(remote, "alice.athena.foo.job") == "completed"


def test_foreign_owner_preservation(tmp_path: Path) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    alice = _SeedBuilder(sidecar)
    alice.add_run("foo", "foo.job", "run-1", "active")
    alice.write_manifest()
    bob_owner = AgentOwnerIdentity("bob", "zeus")
    bob = _SeedBuilder(sidecar, owner=bob_owner)
    bob.add_run("other", "other", "run-9", "active")
    bob.write_manifest()
    _commit_push(sidecar)
    bob_snapshot_before = (
        sidecar
        / "users"
        / "bob"
        / "machines"
        / "zeus"
        / "hoods"
        / "other"
        / "snapshot.json"
    ).read_bytes()
    sync_target = target(tmp_path, remote, sidecar)

    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([_inv_run("run-1", "foo.job", "completed")], []),
    )

    assert report.error is None and report.changed == 1
    assert (
        sidecar
        / "users"
        / "bob"
        / "machines"
        / "zeus"
        / "hoods"
        / "other"
        / "snapshot.json"
    ).read_bytes() == bob_snapshot_before
    assert _remote_state(remote, "alice.athena.foo.job") == "completed"
    assert _remote_state(remote, "bob.zeus.other") == "active"


def test_published_terminal_preserved_against_stale_active(tmp_path: Path) -> None:
    remote, sync_target = _setup(
        tmp_path, runs=[("foo", "foo.job", "run-1", "completed")]
    )
    before = _remote_head(remote)
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([_inv_run("run-1", "foo.job", "active")], []),
    )

    assert report.error is None
    assert (report.changed, report.already_current) == (0, 1)
    assert _remote_head(remote) == before
    assert _remote_state(remote, "alice.athena.foo.job") == "completed"


def test_reused_name_different_identity_never_borrows(tmp_path: Path) -> None:
    remote, sync_target = _setup(tmp_path, runs=[("foo", "foo.job", "run-1", "active")])
    before = _remote_head(remote)
    conflicting = _inv_run("run-1", "fooo", "completed")
    assert conflicting.global_name == "alice.athena.fooo"
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([conflicting], []),
    )

    assert report.error is None
    assert (report.changed, report.unresolved) == (0, 1)
    assert _remote_head(remote) == before
    assert _remote_state(remote, "alice.athena.foo.job") == "active"


def test_non_fast_forward_push_recomputes_and_retries(tmp_path: Path) -> None:
    remote, sync_target = _setup(tmp_path, runs=[("foo", "foo.job", "run-1", "active")])
    intruder = tmp_path / "intruder"
    git(tmp_path, "clone", str(remote), str(intruder))
    git(intruder, "config", "user.name", "Intruder")
    git(intruder, "config", "user.email", "intruder@example.test")
    push_calls = 0

    def rejecting_runner(
        cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        nonlocal push_calls
        if args == ["push"]:
            push_calls += 1
            if push_calls == 1:
                (intruder / "remote.txt").write_text("remote\n")
                git(intruder, "add", "remote.txt")
                git(intruder, "commit", "-m", "remote race")
                git(intruder, "push")
        return run_git(cwd, args, network=network, op=op)

    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([_inv_run("run-1", "foo.job", "completed")], []),
        git_runner=rejecting_runner,
    )

    assert report.error is None
    assert report.push_attempts == 2
    assert report.pushed and report.changed == 1
    assert _remote_state(remote, "alice.athena.foo.job") == "completed"
    assert not (sync_target.sidecar_path / ".git" / "rebase-merge").exists()
    assert not (sync_target.sidecar_path / ".git" / "rebase-apply").exists()


def test_lock_busy_is_benign_skip(tmp_path: Path) -> None:
    remote, sync_target = _setup(tmp_path, runs=[("foo", "foo.job", "run-1", "active")])
    before = _remote_head(remote)
    lock_path = sync_target.sidecar_path / ".git" / "sase-agents-sync.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        report = repair_project_run_states(
            sync_target,
            OWNER,
            apply=True,
            inventory_loader=_loader([_inv_run("run-1", "foo.job", "completed")], []),
            lock_timeout_seconds=0,
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert report.error is None
    assert report.skip_reason == "agents sync lock is busy"
    assert report.next_cursor is None
    assert _remote_head(remote) == before


def test_push_failure_then_retry_converges(tmp_path: Path) -> None:
    remote, sync_target = _setup(tmp_path, runs=[("foo", "foo.job", "run-1", "active")])
    before = _remote_head(remote)

    def failing_runner(
        cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        if args == ["push"]:
            return subprocess.CompletedProcess(
                ["git", "push"],
                1,
                "",
                " ! [remote rejected] main -> main (pre-receive hook declined)\n"
                "error: failed to push some refs",
            )
        return run_git(cwd, args, network=network, op=op)

    loader = _loader([_inv_run("run-1", "foo.job", "completed")], [])
    failed = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=loader,
        git_runner=failing_runner,
    )
    assert failed.error is not None
    assert failed.next_cursor is None
    assert _remote_head(remote) == before

    retried = repair_project_run_states(
        sync_target, OWNER, apply=True, inventory_loader=loader
    )
    assert retried.error is None
    assert _remote_state(remote, "alice.athena.foo.job") == "completed"


def test_withheld_run_does_not_block_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, sync_target = _setup(
        tmp_path,
        runs=[
            ("foo", "foo.keep", "run-1", "active"),
            ("foo", "foo.victim", "run-2", "active"),
        ],
    )
    import sase.agents_sync.publication_state_repair as repair_module

    original = repair_module._state_bytes_publishable

    def scoped_block(
        state_bytes: bytes,
        destination: str,
        scope: object,
        t: ProjectTarget,
        diags: list[str],
        global_name: str,
    ) -> bool:
        if global_name == "alice.athena.foo.victim":
            diags.append(f"{global_name}: state payload blocked; withheld")
            return False
        return original(state_bytes, destination, scope, t, diags, global_name)

    monkeypatch.setattr(repair_module, "_state_bytes_publishable", scoped_block)
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader(
            [
                _inv_run("run-1", "foo.keep", "completed"),
                _inv_run("run-2", "foo.victim", "completed"),
            ],
            [],
        ),
    )

    assert report.error is None
    assert (report.changed, report.withheld) == (1, 1)
    assert report.pushed
    assert _remote_state(remote, "alice.athena.foo.keep") == "completed"
    assert _remote_state(remote, "alice.athena.foo.victim") == "active"


def test_corrupt_hood_does_not_block_sibling(tmp_path: Path) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    builder = _SeedBuilder(sidecar)
    builder.add_run("foo", "foo.job", "run-1", "active")
    builder.write_manifest(corrupt={"bar": "0" * 64})
    builder.add_corrupt_hood("bar")
    _commit_push(sidecar)
    sync_target = target(tmp_path, remote, sidecar)

    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([_inv_run("run-1", "foo.job", "completed")], []),
    )

    assert report.error is None
    assert report.changed == 1 and report.failed >= 1
    assert any("bar" in diagnostic for diagnostic in report.diagnostics)
    assert _remote_state(remote, "alice.athena.foo.job") == "completed"


def test_byte_budget_freezes_cursor(tmp_path: Path) -> None:
    remote, sync_target = _setup(tmp_path, runs=[("foo", "foo.job", "run-1", "active")])
    before = _remote_head(remote)
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=_loader([_inv_run("run-1", "foo.job", "completed")], []),
        payload_budget_bytes=10,
    )

    assert report.changed == 0
    assert report.next_cursor is None
    assert any("byte limit" in diagnostic for diagnostic in report.diagnostics)
    assert _remote_head(remote) == before


def test_second_pass_is_noop(tmp_path: Path) -> None:
    remote, sync_target = _setup(tmp_path, runs=[("foo", "foo.job", "run-1", "active")])
    loader = _loader([_inv_run("run-1", "foo.job", "completed")], [])
    first = repair_project_run_states(
        sync_target, OWNER, apply=True, inventory_loader=loader
    )
    assert first.changed == 1

    steady = _loader([_inv_run("run-1", "foo.job", "completed")], [])
    second = repair_project_run_states(
        sync_target, OWNER, apply=True, inventory_loader=steady
    )
    assert second.error is None
    assert (second.changed, second.already_current) == (0, 1)
    assert second.committed is False

    preview = repair_project_run_states(
        sync_target, OWNER, apply=False, inventory_loader=steady
    )
    assert (preview.changed, preview.already_current) == (0, 1)


def test_cursor_pagination_and_invalid_cursor(tmp_path: Path) -> None:
    _remote, sync_target = _setup(
        tmp_path,
        runs=[
            ("foo", "foo.a", "run-1", "active"),
            ("foo", "foo.b", "run-2", "active"),
            ("foo", "foo.c", "run-3", "active"),
        ],
    )
    loader = _loader(
        [
            _inv_run("run-1", "foo.a", "completed"),
            _inv_run("run-2", "foo.b", "completed"),
            _inv_run("run-3", "foo.c", "completed"),
        ],
        [],
    )
    first = repair_project_run_states(
        sync_target, OWNER, apply=False, state_limit=2, inventory_loader=loader
    )
    assert first.examined == 2 and first.pass_complete is False
    assert first.next_cursor is not None

    second = repair_project_run_states(
        sync_target,
        OWNER,
        apply=False,
        state_limit=2,
        state_after=first.next_cursor,
        inventory_loader=loader,
    )
    assert second.examined == 1 and second.pass_complete is True

    invalid = repair_project_run_states(
        sync_target, OWNER, apply=False, state_after="bogus", inventory_loader=loader
    )
    assert invalid.error is not None

    too_small = repair_project_run_states(
        sync_target, OWNER, apply=False, state_limit=0, inventory_loader=loader
    )
    assert too_small.error is not None
    too_large = repair_project_run_states(
        sync_target, OWNER, apply=False, state_limit=501, inventory_loader=loader
    )
    assert too_large.error is not None


def test_window_hood_cap(tmp_path: Path) -> None:
    _remote, sync_target = _setup(
        tmp_path,
        runs=[
            (f"hood-{suffix}", f"hood-{suffix}.job", f"run-{suffix}", "active")
            for suffix in ("a", "b", "c", "d", "e", "f")
        ],
    )
    loader = _loader(
        [
            _inv_run(f"run-{suffix}", f"hood-{suffix}.job", "completed")
            for suffix in ("a", "b", "c", "d", "e", "f")
        ],
        [],
    )
    report = repair_project_run_states(
        sync_target, OWNER, apply=False, inventory_loader=loader
    )

    assert report.examined == STATE_REPAIR_MAX_HOODS
    assert len({row.local_hood for row in report.window}) == STATE_REPAIR_MAX_HOODS
    assert report.pass_complete is False
    assert report.next_cursor is not None


def test_collect_reads_owner_manifest_constant_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.agents_sync.publication_state_repair as repair_module
    import sase.agents_sync.v2_io as v2_io

    def seed(count: int, name: str) -> ProjectTarget:
        workdir = tmp_path / name
        workdir.mkdir()
        remote, _seed, sidecar = setup_repo(workdir)
        builder = _SeedBuilder(sidecar)
        for index in range(count):
            hood = f"hood-{index}"
            builder.add_run(hood, f"{hood}.job", f"run-{index}", "active")
        builder.write_manifest()
        _commit_push(sidecar)
        return target(workdir, remote, sidecar)

    small_target = seed(2, "small")
    large_target = seed(6, "large")

    original = v2_io.read_owner_manifest
    reads = 0

    def counting(*args, **kwargs):
        nonlocal reads
        reads += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(v2_io, "read_owner_manifest", counting)

    small_loader = _loader(
        [
            _inv_run(f"run-{index}", f"hood-{index}.job", "completed")
            for index in range(2)
        ],
        [],
    )
    repair_module.repair_project_run_states(
        small_target, OWNER, apply=False, inventory_loader=small_loader
    )
    small_reads = reads

    reads = 0
    large_loader = _loader(
        [
            _inv_run(f"run-{index}", f"hood-{index}.job", "completed")
            for index in range(6)
        ],
        [],
    )
    repair_module.repair_project_run_states(
        large_target, OWNER, apply=False, inventory_loader=large_loader
    )
    large_reads = reads

    assert small_reads == large_reads
    assert small_reads <= 2
