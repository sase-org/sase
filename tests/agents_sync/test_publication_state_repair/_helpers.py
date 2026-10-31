"""Shared builders for publication state-repair tests.

Split from ``tests.agents_sync.test_publication_state_repair``; the names here are
public so the sibling test modules can import them without touching a
``_``-prefixed symbol across files.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.agents_sync.inventory_models import InventoryRun, ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
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


def global_name(local: str, owner: AgentOwnerIdentity = OWNER) -> str:
    return f"{owner.username}.{owner.machine_name}.{local}"


def inv_run(
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
        global_name(local, owner),
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


class SeedBuilder:
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
        (self.sidecar / "agents" / global_name(local, self.owner)).mkdir(
            parents=True, exist_ok=True
        )
        (
            self.sidecar / "agents" / global_name(local, self.owner) / "state.json"
        ).write_bytes(blob)
        run = V2RunRecord(
            source_run_id,
            local,
            global_name(local, self.owner),
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
                        f"agents/{global_name(local, self.owner)}/state.json", blob
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
                global_name(hood, self.owner),
                (global_name(hood, self.owner),),
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


def commit_push(sidecar: Path, message: str = "seed published states") -> None:
    git(sidecar, "add", "-A")
    git(sidecar, "commit", "-m", message)
    git(sidecar, "push", "origin", "HEAD")


def remote_head(remote: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=remote,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def remote_state(remote: Path, global_run_name: str) -> str:
    verify = remote.parent / f"verify-{global_run_name.replace('.', '-')}"
    if verify.exists():
        subprocess.run(["rm", "-rf", str(verify)], check=True)
    subprocess.run(["git", "clone", "--quiet", str(remote), str(verify)], check=True)
    payload = json.loads(
        (verify / "agents" / global_run_name / "state.json").read_text()
    )
    return str(payload["state"])


def make_loader(runs: list[InventoryRun], seen: list[frozenset[str]]):
    def load(
        _target: ProjectTarget,
        _identity: AgentIdentitySnapshot,
        hoods: frozenset[str],
    ) -> ProjectHoodInventory:
        seen.append(hoods)
        return ProjectHoodInventory(OWNER, "proj", tuple(runs))

    return load


def setup_repair(
    tmp_path: Path, *, runs: list[tuple[str, str, str, str]]
) -> tuple[Path, ProjectTarget]:
    """Seed one owner hood per ``(hood, local, source_run_id, state)`` row."""

    remote, _seed, sidecar = setup_repo(tmp_path)
    builder = SeedBuilder(sidecar)
    for hood, local, source_run_id, state in runs:
        builder.add_run(hood, local, source_run_id, state)
    builder.write_manifest()
    commit_push(sidecar)
    return remote, target(tmp_path, remote, sidecar)
