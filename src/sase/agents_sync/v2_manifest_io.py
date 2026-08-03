"""Strict owner-manifest path handling and decoding for v2 sidecars."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_models import (
    V2CompatibilityAlias,
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
    json_list,
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
    data = json_object(value, "owner manifest")
    required = {"schema_version", "owner", "project", "hoods"}
    optional = {"compatibility_aliases"}
    if not required <= set(data) or set(data) - (required | optional):
        raise AgentsSyncFormatError("owner manifest has an invalid shape")
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
    aliases = _compatibility_aliases(data.get("compatibility_aliases", []))
    return V2OwnerManifest(owner, project, tuple(hoods), aliases)


def _compatibility_aliases(value: object) -> tuple[V2CompatibilityAlias, ...]:
    rows = json_list(value, "owner manifest compatibility_aliases", MAX_CONTAINERS)
    aliases: list[V2CompatibilityAlias] = []
    sources: set[str] = set()
    graph: dict[str, str] = {}
    for index, raw in enumerate(rows):
        label = f"owner manifest compatibility_aliases[{index}]"
        row = exact_object(
            raw,
            label,
            {"source_global_name", "target_global_name", "page_kind"},
        )
        source = validate_component(
            row["source_global_name"],
            label=f"{label} source_global_name",
        )
        target = validate_component(
            row["target_global_name"],
            label=f"{label} target_global_name",
        )
        if source == target:
            raise AgentsSyncFormatError(f"{label} must not alias to itself")
        if source in sources:
            raise AgentsSyncFormatError(
                f"duplicate compatibility alias source: {source!r}"
            )
        page_kind = row["page_kind"]
        if page_kind not in {"agent", "family"}:
            raise AgentsSyncFormatError(f"{label} has an invalid page_kind")
        sources.add(source)
        graph[source] = target
        aliases.append(V2CompatibilityAlias(source, target, page_kind))
    _reject_alias_cycles(graph)
    return tuple(
        sorted(aliases, key=lambda item: (item.page_kind, item.source_global_name))
    )


def _reject_alias_cycles(graph: dict[str, str]) -> None:
    for source in sorted(graph):
        seen: set[str] = set()
        current = source
        while current in graph:
            if current in seen:
                raise AgentsSyncFormatError(
                    f"compatibility aliases contain a cycle through {current!r}"
                )
            seen.add(current)
            current = graph[current]


__all__ = [
    "owner_manifest_from_bytes",
    "owner_manifest_path",
    "read_all_owner_manifests",
    "read_owner_manifest",
]
