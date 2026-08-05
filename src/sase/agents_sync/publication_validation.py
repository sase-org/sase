"""Validation and path helpers for agent sidecar publication."""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_io import (
    content_digest,
    read_all_owner_manifests_lenient,
    read_hood_snapshot,
    v2_json_bytes,
)
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2RunRecord,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity


def previous_snapshot(
    repo_root: Path,
    owner: AgentOwnerIdentity,
    hood: str,
    entry: V2OwnerHoodEntry | None,
) -> V2HoodSnapshot | None:
    if entry is None:
        return None
    path = repo_root / snapshot_path(owner, hood)
    payload = path.read_bytes()
    if content_digest(payload) != entry.digest:
        raise AgentsSyncFormatError(
            f"existing snapshot digest mismatch for hood {hood!r}"
        )
    snapshot = read_hood_snapshot(path)
    if snapshot.owner != owner or snapshot.local_hood != hood:
        raise AgentsSyncFormatError(
            f"existing snapshot identity mismatch for hood {hood!r}"
        )
    return snapshot


def load_validated_publication(
    repo_root: Path,
    *,
    override_manifest: V2OwnerManifest | None = None,
    override_snapshots: dict[tuple[str, str, str], V2HoodSnapshot] | None = None,
    override_payload: dict[str, bytes] | None = None,
) -> tuple[
    tuple[V2OwnerManifest, ...],
    dict[tuple[str, str, str], V2HoodSnapshot],
    tuple[str, ...],
]:
    all_manifests, diagnostics = read_all_owner_manifests_lenient(repo_root)
    manifests = {
        (item.owner.username, item.owner.machine_name): item for item in all_manifests
    }
    if override_manifest is not None:
        manifests[
            (
                override_manifest.owner.username,
                override_manifest.owner.machine_name,
            )
        ] = override_manifest
    snapshots: dict[tuple[str, str, str], V2HoodSnapshot] = {}
    overrides = override_snapshots or {}
    payload = override_payload or {}
    for manifest in manifests.values():
        for hood, entry in manifest.hoods:
            key = (manifest.owner.username, manifest.owner.machine_name, hood)
            snapshot = overrides.get(key)
            path = snapshot_path(manifest.owner, hood)
            raw = (
                v2_json_bytes(snapshot.to_json_dict())
                if snapshot is not None
                else _payload_bytes(repo_root, payload, path)
            )
            if content_digest(raw) != entry.digest:
                raise AgentsSyncFormatError(
                    f"snapshot digest mismatch for {'.'.join(key)!r}"
                )
            if snapshot is None:
                snapshot = read_hood_snapshot(repo_root / path)
            if (
                snapshot.owner != manifest.owner
                or snapshot.project != manifest.project
                or snapshot.local_hood != hood
            ):
                raise AgentsSyncFormatError(
                    f"snapshot identity mismatch for {'.'.join(key)!r}"
                )
            expected = hood_file_set(snapshot)
            if expected != entry.files:
                raise AgentsSyncFormatError(
                    f"manifest file set mismatch for {'.'.join(key)!r}"
                )
            for run in snapshot.runs:
                verify_run_files(repo_root, run, payload)
            snapshots[key] = snapshot
    return (
        tuple(
            sorted(
                manifests.values(),
                key=lambda item: (
                    item.owner.username,
                    item.owner.machine_name,
                ),
            )
        ),
        snapshots,
        diagnostics,
    )


def verify_run_files(
    repo_root: Path,
    run: V2RunRecord,
    payload: dict[str, bytes] | None = None,
) -> None:
    for _kind, reference in run.files:
        content = _payload_bytes(repo_root, payload or {}, reference.path)
        if (
            len(content) != reference.size_bytes
            or content_digest(content) != reference.digest
        ):
            raise AgentsSyncFormatError(f"file digest mismatch for {reference.path!r}")


def _payload_bytes(repo_root: Path, payload: dict[str, bytes], path: str) -> bytes:
    if path in payload:
        return payload[path]
    try:
        return (repo_root / path).read_bytes()
    except OSError as exc:
        raise AgentsSyncFormatError(f"could not read referenced file {path!r}") from exc


def hood_file_set(snapshot: V2HoodSnapshot) -> tuple[str, ...]:
    files = {
        snapshot_path(snapshot.owner, snapshot.local_hood),
        _hood_readme_path(snapshot.owner, snapshot.local_hood),
    }
    for run in snapshot.runs:
        files.update(reference.path for _kind, reference in run.files)
        files.add(f"agents/{run.global_name}/README.md")
    files.update(
        f"families/{container.global_name}.md"
        for container in snapshot.containers
        if container.kind == "family"
    )
    return tuple(sorted(files))


def snapshot_path(owner: AgentOwnerIdentity, hood: str) -> str:
    return (
        f"users/{owner.username}/machines/{owner.machine_name}/"
        f"hoods/{hood}/snapshot.json"
    )


def _hood_readme_path(owner: AgentOwnerIdentity, hood: str) -> str:
    return (
        f"users/{owner.username}/machines/{owner.machine_name}/hoods/{hood}/README.md"
    )
