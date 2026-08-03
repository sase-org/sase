"""Strict owner-manifest path handling and decoding for v2 sidecars."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
)
from sase.agents_sync.v2_validation import (
    MAX_CONTAINERS,
    MAX_FILES,
    decode_owner_identity,
    decode_project_identity,
    exact_object,
    json_from_bytes,
    json_object,
    nonnegative_int,
    read_json,
    string_list,
    validate_digest,
    validate_component,
    validate_relative_path,
    validate_schema,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity, validate_agent_owner


def owner_manifest_path(owner: AgentOwnerIdentity) -> str:
    validate_agent_owner(owner)
    return (
        f"users/{validate_component(owner.username, label='username')}/machines/"
        f"{validate_component(owner.machine_name, label='machine')}/manifest.json"
    )


def read_owner_manifest(
    repo_root: Path,
    owner: AgentOwnerIdentity,
    project: V2ProjectIdentity,
) -> V2OwnerManifest:
    path = repo_root / owner_manifest_path(owner)
    if not path.is_file():
        return V2OwnerManifest(owner, project)
    manifest = decode_owner_manifest(read_json(path, "owner manifest"))
    if manifest.owner != owner:
        raise AgentsSyncFormatError("owner manifest path does not match its owner")
    if manifest.project != project:
        raise AgentsSyncFormatError("owner manifest project identity does not match")
    return manifest


def owner_manifest_from_bytes(payload: bytes) -> V2OwnerManifest:
    """Decode strict owner-manifest bytes from a fetched Git object."""

    return decode_owner_manifest(json_from_bytes(payload, "owner manifest"))


def read_all_owner_manifests(repo_root: Path) -> tuple[V2OwnerManifest, ...]:
    manifests: list[V2OwnerManifest] = []
    pattern = "users/*/machines/*/manifest.json"
    for path in sorted(repo_root.glob(pattern), key=lambda item: item.as_posix()):
        relative = path.relative_to(repo_root).as_posix()
        validate_relative_path(relative)
        manifest = decode_owner_manifest(read_json(path, relative))
        parts = PurePosixPath(relative).parts
        if (
            manifest.owner.username != parts[1]
            or manifest.owner.machine_name != parts[3]
        ):
            raise AgentsSyncFormatError(
                f"owner manifest identity does not match path {relative!r}"
            )
        manifests.append(manifest)
    return tuple(manifests)


def decode_owner_manifest(value: object) -> V2OwnerManifest:
    data = exact_object(
        value,
        "owner manifest",
        {"schema_version", "owner", "project", "hoods"},
    )
    validate_schema(data, "owner manifest")
    owner = decode_owner_identity(data["owner"], "owner manifest owner")
    project = decode_project_identity(data["project"])
    raw_hoods = json_object(data["hoods"], "owner manifest hoods")
    if len(raw_hoods) > MAX_CONTAINERS:
        raise AgentsSyncFormatError("owner manifest has too many hoods")
    hoods: list[tuple[str, V2OwnerHoodEntry]] = []
    for hood, raw_entry in sorted(raw_hoods.items()):
        validate_component(hood, label="hood")
        row = exact_object(
            raw_entry,
            f"hood {hood!r}",
            {"digest", "files", "run_count", "family_count"},
        )
        digest = validate_digest(row["digest"], f"hood {hood!r} digest")
        files = string_list(row["files"], f"hood {hood!r} files", MAX_FILES)
        for path in files:
            validate_relative_path(path)
        if tuple(sorted(set(files))) != files:
            raise AgentsSyncFormatError(
                f"hood {hood!r} files must be unique and sorted"
            )
        hoods.append(
            (
                hood,
                V2OwnerHoodEntry(
                    digest,
                    files,
                    nonnegative_int(row["run_count"], "run_count"),
                    nonnegative_int(row["family_count"], "family_count"),
                ),
            )
        )
    return V2OwnerManifest(owner, project, tuple(hoods))


__all__ = [
    "owner_manifest_from_bytes",
    "owner_manifest_path",
    "read_all_owner_manifests",
    "read_owner_manifest",
]
