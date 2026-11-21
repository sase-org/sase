"""Shared fixtures for the agent state refresh test modules."""

from __future__ import annotations

from pathlib import Path

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


def _global_name(local: str, owner: AgentOwnerIdentity = OWNER) -> str:
    return f"{owner.username}.{owner.machine_name}.{local}"


def inventory_run(
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
        _global_name(local, owner),
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
        (self.sidecar / "agents" / _global_name(local)).mkdir(
            parents=True, exist_ok=True
        )
        (self.sidecar / "agents" / _global_name(local) / "state.json").write_bytes(blob)
        run = V2RunRecord(
            source_run_id,
            local,
            _global_name(local),
            state,  # type: ignore[arg-type]
            STARTED,
            finished_at,
            finished_at if state == "dismissed" else None,
            (),
            (),
            (
                (
                    "state",
                    file_reference(f"agents/{_global_name(local)}/state.json", blob),
                ),
            ),
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
                _global_name(hood),
                (_global_name(hood),),
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


def setup_refresh_repo(tmp_path: Path, *, runs: list[tuple[str, str, str, str]]):
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


def targets_for(targets: list[ProjectTarget]):
    def list_targets():
        return (targets, [])

    return list_targets


def owner_identity():
    return OWNER


def repair_with(loader_runs: list[InventoryRun]):
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
