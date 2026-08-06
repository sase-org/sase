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
    compatible_object,
    decode_owner_identity,
    decode_project_identity,
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


def owner_hood_directory_names(
    repo_root: Path,
    owner: AgentOwnerIdentity,
) -> tuple[str, ...]:
    """Names of the owner's on-disk hood directories that contain a snapshot."""

    hoods_dir = (
        repo_root / f"users/{owner.username}/machines/{owner.machine_name}/hoods"
    )
    if not hoods_dir.is_dir():
        return ()
    return tuple(
        sorted(
            child.name
            for child in hoods_dir.iterdir()
            if (child / "snapshot.json").is_file()
        )
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
    manifests, _diagnostics = _read_all_owner_manifests(repo_root, strict=True)
    return manifests


def read_all_owner_manifests_lenient(
    repo_root: Path,
) -> tuple[tuple[V2OwnerManifest, ...], tuple[str, ...]]:
    return _read_all_owner_manifests(repo_root, strict=False)


def _read_all_owner_manifests(
    repo_root: Path,
    *,
    strict: bool,
) -> tuple[tuple[V2OwnerManifest, ...], tuple[str, ...]]:
    manifests: list[V2OwnerManifest] = []
    diagnostics: list[str] = []
    pattern = "users/*/machines/*/manifest.json"
    for path in sorted(repo_root.glob(pattern), key=lambda item: item.as_posix()):
        relative = path.relative_to(repo_root).as_posix()
        try:
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
        except AgentsSyncFormatError as exc:
            if strict:
                raise
            diagnostics.append(f"{relative}: skipped v2 owner manifest: {exc}")
            continue
        manifests.append(manifest)
    return tuple(manifests), tuple(diagnostics)


def decode_owner_manifest(value: object) -> V2OwnerManifest:
    data = compatible_object(
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
        row = compatible_object(
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
    "owner_hood_directory_names",
    "owner_manifest_from_bytes",
    "owner_manifest_path",
    "read_all_owner_manifests",
    "read_all_owner_manifests_lenient",
    "read_owner_manifest",
]
