"""Shared builders for publication state-repair tests.

Split from ``tests.agents_sync.test_publication_state_repair``; the names here are
public so the sibling test modules can import them without touching a
``_``-prefixed symbol across files.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.agents_sync.inventory_models import InventoryRun, ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_io import content_digest, file_reference, v2_json_bytes
from sase.agents_sync.v2_models import (
    V2FileReference,
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
        extra_files: dict[str, bytes] | None = None,
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
        agent_dir = self.sidecar / "agents" / global_name(local, self.owner)
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "state.json").write_bytes(blob)
        files: list[tuple[str, V2FileReference]] = [
            (
                "state",
                file_reference(
                    f"agents/{global_name(local, self.owner)}/state.json", blob
                ),
            )
        ]
        for kind, content in (extra_files or {}).items():
            relative = f"agents/{global_name(local, self.owner)}/{kind}.md"
            path = self.sidecar / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            files.append((kind, file_reference(relative, content)))
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
            tuple(files),
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
    tmp_path: Path,
    *,
    runs: list[tuple[str, str, str, str]],
    extra_files: dict[str, dict[str, bytes]] | None = None,
) -> tuple[Path, ProjectTarget]:
    """Seed one owner hood per ``(hood, local, source_run_id, state)`` row."""

    remote, _seed, sidecar = setup_repo(tmp_path)
    builder = SeedBuilder(sidecar)
    extras = extra_files or {}
    for hood, local, source_run_id, state in runs:
        builder.add_run(
            hood,
            local,
            source_run_id,
            state,
            extra_files=extras.get(local),
        )
    builder.write_manifest()
    commit_push(sidecar)
    return remote, target(tmp_path, remote, sidecar)


def install_repair_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".sase"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return home


def repair_run_id(timestamp: str, project_key: str = "proj") -> str:
    from sase.agents_sync.inventory_io import source_run_id

    return source_run_id(project_key, "ace-run", timestamp)


def write_repair_artifact(
    home: Path,
    *,
    timestamp: str,
    name: str,
    outcome: str | None,
    extra_done: dict[str, object] | None = None,
    extra_meta: dict[str, object] | None = None,
    extra_files: dict[str, str] | None = None,
    project_key: str = "proj",
) -> Path:
    artifact = home / "projects" / project_key / "artifacts" / "ace-run" / timestamp
    artifact.mkdir(parents=True, exist_ok=True)
    (home / "projects" / project_key / f"{project_key}.sase").write_text(
        "name: Project\n"
    )
    meta: dict[str, object] = {
        "name": name,
        "artifact_agent_id": timestamp,
        "run_started_at": STARTED,
        "project": project_key,
    }
    if extra_meta:
        meta.update(extra_meta)
    (artifact / "agent_meta.json").write_text(
        json.dumps(meta),
        encoding="utf-8",
    )
    if outcome is not None:
        payload: dict[str, object] = {
            "name": name,
            "outcome": outcome,
            "finished_at": FINISHED,
        }
        if extra_done:
            payload.update(extra_done)
        (artifact / "done.json").write_text(json.dumps(payload), encoding="utf-8")
    for relative, content in (extra_files or {}).items():
        path = artifact / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return artifact


def rebuild_repair_artifact_index(home: Path) -> Path:
    from sase.core.agent_scan_facade import (
        default_agent_artifact_index_path,
        rebuild_agent_artifact_index,
    )

    index = default_agent_artifact_index_path()
    rebuild_agent_artifact_index(index, home / "projects")
    return index


def track_path_reads(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    reads: list[Path] = []
    original_bytes = Path.read_bytes
    original_text = Path.read_text

    def read_bytes(self: Path, *args: object, **kwargs: object) -> bytes:
        reads.append(Path(self))
        return original_bytes(self, *args, **kwargs)

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        reads.append(Path(self))
        return original_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)
    return reads
