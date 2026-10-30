"""Scheduled bounded convergence for already-published run states."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.agents_sync.agent_state_refresh import run_agent_state_refresh
from sase.agents_sync.inventory_models import InventoryRun, ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_state_repair import StateRepairReport
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
    )


class _SeedBuilder:
    def __init__(self, sidecar: Path) -> None:
        self.sidecar = sidecar
        self.hoods: dict[str, list[V2RunRecord]] = {}

    def add_run(self, hood: str, local: str, source_run_id: str, state: str) -> None:
        finished_at = None if state in ("active", "waiting") else FINISHED
        payload = V2RunStatePayload(
            source_run_id,
            state,  # type: ignore[arg-type]
            STARTED,
            finished_at,
            finished_at if state == "dismissed" else None,
        )
        blob = v2_json_bytes(payload.to_json_dict())
        (self.sidecar / "agents" / _global(local)).mkdir(parents=True, exist_ok=True)
        (self.sidecar / "agents" / _global(local) / "state.json").write_bytes(blob)
        run = V2RunRecord(
            source_run_id,
            local,
            _global(local),
            state,  # type: ignore[arg-type]
            STARTED,
            finished_at,
            finished_at if state == "dismissed" else None,
            (),
            (),
            (("state", file_reference(f"agents/{_global(local)}/state.json", blob)),),
        )
        self.hoods.setdefault(hood, []).append(run)

    def write_manifest(self) -> None:
        entries: dict[str, V2OwnerHoodEntry] = {}
        for hood, runs in sorted(self.hoods.items()):
            ordered = tuple(sorted(runs, key=lambda item: item.source_run_id))
            snapshot = V2HoodSnapshot(
                OWNER,
                PROJECT,
                hood,
                _global(hood),
                (_global(hood),),
                ordered,
            )
            snapshot_bytes = v2_json_bytes(snapshot.to_json_dict())
            snapshot_path = (
                self.sidecar
                / "users"
                / "alice"
                / "machines"
                / "athena"
                / "hoods"
                / hood
                / "snapshot.json"
            )
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_bytes(snapshot_bytes)
            entries[hood] = V2OwnerHoodEntry(
                content_digest(snapshot_bytes), None, len(ordered), 0
            )
        manifest = V2OwnerManifest(OWNER, PROJECT, tuple(sorted(entries.items())))
        manifest_path = (
            self.sidecar / "users" / "alice" / "machines" / "athena" / "manifest.json"
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(v2_json_bytes(manifest.to_json_dict()))


def _commit_push(sidecar: Path) -> None:
    git(sidecar, "add", "-A")
    git(sidecar, "commit", "-m", "seed published states")
    git(sidecar, "push", "origin", "HEAD")


def _remote_state(remote: Path, global_name: str) -> str:
    verify = remote.parent / f"verify-{global_name.replace('.', '-')}"
    if verify.exists():
        subprocess.run(["rm", "-rf", str(verify)], check=True)
    subprocess.run(["git", "clone", "--quiet", str(remote), str(verify)], check=True)
    payload = json.loads((verify / "agents" / global_name / "state.json").read_text())
    return str(payload["state"])


def _setup(tmp_path: Path, *, runs: list[tuple[str, str, str, str]]):
    remote, _seed, sidecar = setup_repo(tmp_path)
    builder = _SeedBuilder(sidecar)
    for hood, local, source_run_id, state in runs:
        builder.add_run(hood, local, source_run_id, state)
    builder.write_manifest()
    _commit_push(sidecar)
    return remote, target(tmp_path, remote, sidecar)


def _loader(runs: list[InventoryRun]):
    def load(
        _target: ProjectTarget,
        _identity: AgentIdentitySnapshot,
        _hoods: frozenset[str],
    ) -> ProjectHoodInventory:
        return ProjectHoodInventory(OWNER, "proj", tuple(runs))

    return load


def _targets_for(targets: list[ProjectTarget]):
    def list_targets():
        return (targets, [])

    return list_targets


def _owner():
    return OWNER


def _repair_with(loader_runs: list[InventoryRun]):
    from sase.agents_sync.publication_state_repair import repair_project_run_states

    def repair_one(target: ProjectTarget, owner: AgentOwnerIdentity, **kwargs):
        return repair_project_run_states(
            target,
            owner,
            apply=True,
            state_limit=int(kwargs.get("state_limit", 100)),
            state_after=kwargs.get("state_after"),
            inventory_loader=_loader(loader_runs),
            work_budget_seconds=float(kwargs.get("work_budget_seconds", 90.0)),
        )

    return repair_one


def _stored_cursor(state_dir: Path, key: str) -> object:
    payload = json.loads(
        (state_dir / "agent_state_refresh.json").read_text(encoding="utf-8")
    )
    return payload["projects"][key]["cursor"]


def test_corrupt_and_unsupported_state_reset_safely(tmp_path: Path) -> None:
    _remote, sync_target = _setup(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    state_dir = tmp_path / "state"
    (state_dir / "agent_state_refresh.json").parent.mkdir(parents=True, exist_ok=True)
    (state_dir / "agent_state_refresh.json").write_text("{not json", encoding="utf-8")
    summary = run_agent_state_refresh(
        state_dir=state_dir,
        list_targets=_targets_for([sync_target]),
        require_owner=_owner,
        repair_one=_repair_with([_inv_run("run-1", "foo.job", "completed")]),
    )
    assert summary.errors == 0
    assert summary.changed == 1

    (state_dir / "agent_state_refresh.json").write_text(
        json.dumps({"schema_version": 999, "projects": {}}), encoding="utf-8"
    )
    followup = run_agent_state_refresh(
        state_dir=state_dir,
        list_targets=_targets_for([sync_target]),
        require_owner=_owner,
        repair_one=_repair_with([_inv_run("run-1", "foo.job", "completed")]),
    )
    assert followup.errors == 0


def test_no_enabled_projects_reports_cleanly(tmp_path: Path) -> None:
    summary = run_agent_state_refresh(
        state_dir=tmp_path,
        list_targets=lambda: ([], []),
        require_owner=_owner,
    )
    assert summary.projects == 0
    assert summary.reason == "no_enabled_projects"


def test_missing_owner_identity_is_check_error(tmp_path: Path) -> None:
    def no_owner():
        raise RuntimeError("no owner configured")

    summary = run_agent_state_refresh(
        state_dir=tmp_path,
        list_targets=lambda: ([], []),
        require_owner=no_owner,
    )
    assert summary.errors == 1
    assert summary.reason == "no_owner_identity"


def test_fair_rotation_and_backoff_across_projects(tmp_path: Path) -> None:
    import dataclasses

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    remote_a, base_a = _setup(dir_a, runs=[("foo", "foo.job", "run-1", "active")])
    remote_b, base_b = _setup(dir_b, runs=[("foo", "foo.job", "run-1", "active")])
    _ = (remote_a, remote_b)
    target_a = dataclasses.replace(base_a, project_key="proj-a", project="Project A")
    target_b = dataclasses.replace(base_b, project_key="proj-b", project="Project B")
    calls: list[str] = []

    def failing(target: ProjectTarget, owner: AgentOwnerIdentity, **kwargs):
        calls.append(target.project_key)
        return StateRepairReport(
            target.project_key, target.project, "apply", error="boom"
        )

    targets = [target_a, target_b]
    summary = run_agent_state_refresh(
        state_dir=tmp_path / "state",
        now_ms=1_000,
        list_targets=_targets_for(targets),
        require_owner=_owner,
        repair_one=failing,
    )
    assert summary.selected_project == targets[0].project_key
    assert summary.reason == "project_failed"

    # Failed project backs off; the next tick selects the other project.
    selected: list[str] = []

    def ok(target: ProjectTarget, owner: AgentOwnerIdentity, **kwargs):
        selected.append(target.project_key)
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            examined=1,
            already_current=1,
            next_cursor="cursor-1",
            pass_complete=True,
        )

    second = run_agent_state_refresh(
        state_dir=tmp_path / "state",
        now_ms=2_000,
        list_targets=_targets_for(targets),
        require_owner=_owner,
        repair_one=ok,
    )
    assert second.selected_project != targets[0].project_key
    assert selected == [second.selected_project]


def test_success_advances_cursor_and_end_of_pass_resets(tmp_path: Path) -> None:
    _remote, sync_target = _setup(
        tmp_path,
        runs=[
            ("aaa", "aaa.job", "run-aaa", "active"),
            ("mmm", "mmm.job", "run-mmm", "active"),
        ],
    )
    evidence = [
        _inv_run("run-aaa", "aaa.job", "completed"),
        _inv_run("run-mmm", "mmm.job", "completed"),
    ]
    state_dir = tmp_path / "state"
    key = f"{sync_target.project_key}:alice@athena"
    first = run_agent_state_refresh(
        state_dir=state_dir,
        now_ms=1_000,
        list_targets=_targets_for([sync_target]),
        require_owner=_owner,
        repair_one=_repair_with(evidence),
        state_limit=1,
    )
    assert first.changed == 1
    assert first.pass_complete is False
    assert first.next_cursor is not None
    assert _stored_cursor(state_dir, key) == first.next_cursor

    # Scheduler restart reloads the same cursor from disk.
    assert _stored_cursor(state_dir, key) == first.next_cursor

    second = run_agent_state_refresh(
        state_dir=state_dir,
        now_ms=2_000,
        list_targets=_targets_for([sync_target]),
        require_owner=_owner,
        repair_one=_repair_with(evidence),
        state_limit=1,
    )
    assert second.changed == 1
    assert second.pass_complete is True
    assert _stored_cursor(state_dir, key) is None


def test_scheduled_convergence_without_another_commit(tmp_path: Path) -> None:
    remote, sync_target = _setup(
        tmp_path,
        runs=[
            ("aaa", "aaa.job", "run-aaa", "active"),
            ("mmm", "mmm.job", "run-mmm", "active"),
            ("zzz", "zzz.job", "run-zzz", "waiting"),
        ],
    )
    state_dir = tmp_path / "state"
    evidence = [
        _inv_run("run-aaa", "aaa.job", "waiting"),
        _inv_run("run-mmm", "mmm.job", "completed"),
        _inv_run("run-zzz", "zzz.job", "failed"),
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
            list_targets=_targets_for([sync_target]),
            require_owner=_owner,
            repair_one=_repair_with(evidence),
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
        list_targets=_targets_for([sync_target]),
        require_owner=_owner,
        repair_one=_repair_with(evidence),
    )
    assert final.changed == 0
    assert final.pass_complete is True


class _KilledTick(BaseException):
    pass


def test_killed_tick_backs_off_and_rotates(tmp_path: Path) -> None:
    import dataclasses

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _remote_a, base_a = _setup(dir_a, runs=[("foo", "foo.job", "run-1", "active")])
    _remote_b, base_b = _setup(dir_b, runs=[("foo", "foo.job", "run-1", "active")])
    target_a = dataclasses.replace(base_a, project_key="proj-a", project="Project A")
    target_b = dataclasses.replace(base_b, project_key="proj-b", project="Project B")
    targets = [target_a, target_b]
    state_dir = tmp_path / "state"

    def killing(target: object, owner: object, **kwargs: object) -> StateRepairReport:
        raise _KilledTick("sigkill")

    with pytest.raises(_KilledTick):
        run_agent_state_refresh(
            state_dir=state_dir,
            now_ms=1_000,
            list_targets=_targets_for(targets),
            require_owner=_owner,
            repair_one=killing,  # type: ignore[arg-type]
        )

    payload = json.loads(
        (state_dir / "agent_state_refresh.json").read_text(encoding="utf-8")
    )
    key = f"{targets[0].project_key}:alice@athena"
    assert payload["projects"][key]["failure_count"] == 1
    assert payload["projects"][key]["retry_after_ms"] > 1_000
    assert payload["projects"][key]["cursor"] is None
    assert payload["last_selected"]["project"] == targets[0].project_key

    selected: list[str] = []

    def ok(target: object, owner: object, **kwargs: object) -> StateRepairReport:
        selected.append(target.project_key)
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            examined=1,
            already_current=1,
            next_cursor="cursor-1",
            pass_complete=True,
        )

    second = run_agent_state_refresh(
        state_dir=state_dir,
        now_ms=2_000,
        list_targets=_targets_for(targets),
        require_owner=_owner,
        repair_one=ok,  # type: ignore[arg-type]
    )
    assert second.selected_project != targets[0].project_key
    assert selected == [second.selected_project]


def test_frozen_window_retries_with_backoff(tmp_path: Path) -> None:
    import dataclasses

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _remote_a, base_a = _setup(dir_a, runs=[("foo", "foo.job", "run-1", "active")])
    _remote_b, base_b = _setup(dir_b, runs=[("foo", "foo.job", "run-1", "active")])
    target_a = dataclasses.replace(base_a, project_key="proj-a", project="Project A")
    target_b = dataclasses.replace(base_b, project_key="proj-b", project="Project B")
    targets = [target_a, target_b]
    state_dir = tmp_path / "state"

    def frozen(target: object, owner: object, **kwargs: object) -> StateRepairReport:
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            examined=1,
            next_cursor=None,
            pass_complete=False,
        )

    first = run_agent_state_refresh(
        state_dir=state_dir,
        now_ms=1_000,
        list_targets=_targets_for(targets),
        require_owner=_owner,
        repair_one=frozen,  # type: ignore[arg-type]
    )
    assert first.reason == "window_not_advanced"
    assert first.errors == 0
    assert any("did not advance" in item for item in first.diagnostics)

    payload = json.loads(
        (state_dir / "agent_state_refresh.json").read_text(encoding="utf-8")
    )
    key = f"{first.selected_project}:alice@athena"
    assert payload["projects"][key]["failure_count"] == 1
    assert payload["projects"][key]["retry_after_ms"] > 1_000
    assert payload["projects"][key]["cursor"] is None

    selected: list[str] = []

    def ok(target: object, owner: object, **kwargs: object) -> StateRepairReport:
        selected.append(target.project_key)
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            examined=1,
            already_current=1,
            next_cursor="cursor-1",
            pass_complete=True,
        )

    second = run_agent_state_refresh(
        state_dir=state_dir,
        now_ms=2_000,
        list_targets=_targets_for(targets),
        require_owner=_owner,
        repair_one=ok,  # type: ignore[arg-type]
    )
    assert second.selected_project != first.selected_project
    assert selected == [second.selected_project]
