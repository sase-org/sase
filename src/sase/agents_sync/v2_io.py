"""Strict v2 decoding, canonical digests, and transactional payload writes."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any

from sase.agents_sync.io import (
    AgentsSyncFormatError,
    atomic_write_bytes,
    canonical_json_bytes,
)
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2FileReference,
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2RelationshipRecord,
    V2RelationshipTarget,
    V2RunRecord,
    V2_SCHEMA_VERSION,
)
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    globalize_agent_name,
    validate_agent_owner,
    validate_agent_relationship_batch,
)

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_RUNS = 4_096
MAX_CONTAINERS = 2_048
MAX_RELATIONSHIPS = 16_384
MAX_FILES = 32_768
MAX_PAYLOAD_BYTES = 128 * 1024 * 1024

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STATES = {"active", "waiting", "completed", "failed", "stopped", "dismissed"}
_CONTAINER_KINDS = {"family", "clan"}
_RELATIONSHIP_KINDS = {"parent", "workflow_parent", "retry", "wait"}
_FILE_KINDS = {
    "meta",
    "state",
    "commits",
    "prompt",
    "chat",
    "embedded_workflows",
    "prompt_steps",
}
V2_METADATA_FIELDS = frozenset(
    {
        "agent_clan",
        "agent_clan_generation",
        "agent_family",
        "agent_family_role",
        "approve",
        "bead_id",
        "changespec_name",
        "cl_name",
        "clan_summary",
        "clan_tribe",
        "epic_bead_id",
        "hidden",
        "llm_provider",
        "model",
        "phase_bead_id",
        "plan",
        "reasoning_effort",
        "role_suffix",
        "tribe",
        "vcs_provider",
        "workflow_name",
    }
)


def v2_json_bytes(value: object) -> bytes:
    """Return the persisted canonical JSON representation."""

    return canonical_json_bytes(value) + b"\n"


def content_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_reference(path: str, payload: bytes) -> V2FileReference:
    validate_relative_path(path)
    return V2FileReference(path, content_digest(payload), len(payload))


def v2_schema_document() -> dict[str, object]:
    return {
        "schema_version": V2_SCHEMA_VERSION,
        "format": "sase-agents-sidecar",
        "authority": "owner-sharded",
        "relationship_schema_version": V2_SCHEMA_VERSION,
    }


def validate_component(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AgentsSyncFormatError(f"{label} must be a non-empty string")
    if value in {".", ".."} or value.startswith("."):
        raise AgentsSyncFormatError(f"unsafe {label}: {value!r}")
    if len(value.encode("utf-8")) > 255:
        raise AgentsSyncFormatError(f"{label} is too long")
    if "\x00" in value or "/" in value or "\\" in value:
        raise AgentsSyncFormatError(f"unsafe {label}: {value!r}")
    if Path(value).name != value:
        raise AgentsSyncFormatError(f"unsafe {label}: {value!r}")
    return value


def validate_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AgentsSyncFormatError("publication path must be a non-empty string")
    if "\\" in value or "\x00" in value or "//" in value:
        raise AgentsSyncFormatError(f"unsafe publication path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AgentsSyncFormatError(f"unsafe publication path: {value!r}")
    for part in path.parts:
        if part != ".gitkeep":
            validate_component(part, label="publication path component")
    return value


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
    manifest = _owner_manifest_from_json(_read_json(path, "owner manifest"))
    if manifest.owner != owner:
        raise AgentsSyncFormatError("owner manifest path does not match its owner")
    if manifest.project != project:
        raise AgentsSyncFormatError("owner manifest project identity does not match")
    return manifest


def read_all_owner_manifests(repo_root: Path) -> tuple[V2OwnerManifest, ...]:
    manifests: list[V2OwnerManifest] = []
    pattern = "users/*/machines/*/manifest.json"
    for path in sorted(repo_root.glob(pattern), key=lambda item: item.as_posix()):
        relative = path.relative_to(repo_root).as_posix()
        validate_relative_path(relative)
        manifest = _owner_manifest_from_json(_read_json(path, relative))
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


def _owner_manifest_from_json(value: object) -> V2OwnerManifest:
    data = _exact_object(
        value,
        "owner manifest",
        {"schema_version", "owner", "project", "hoods"},
    )
    _schema(data, "owner manifest")
    owner = _owner(data["owner"], "owner manifest owner")
    project = _project(data["project"])
    raw_hoods = _object(data["hoods"], "owner manifest hoods")
    if len(raw_hoods) > MAX_CONTAINERS:
        raise AgentsSyncFormatError("owner manifest has too many hoods")
    hoods: list[tuple[str, V2OwnerHoodEntry]] = []
    for hood, raw_entry in sorted(raw_hoods.items()):
        validate_component(hood, label="hood")
        row = _exact_object(
            raw_entry,
            f"hood {hood!r}",
            {"digest", "files", "run_count", "family_count"},
        )
        digest = _digest(row["digest"], f"hood {hood!r} digest")
        files = _string_list(row["files"], f"hood {hood!r} files", MAX_FILES)
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
                    _nonnegative_int(row["run_count"], "run_count"),
                    _nonnegative_int(row["family_count"], "family_count"),
                ),
            )
        )
    return V2OwnerManifest(owner, project, tuple(hoods))


def read_hood_snapshot(path: Path) -> V2HoodSnapshot:
    return _hood_snapshot_from_json(_read_json(path, "hood snapshot"))


def _hood_snapshot_from_json(value: object) -> V2HoodSnapshot:
    data = _exact_object(
        value,
        "hood snapshot",
        {
            "schema_version",
            "owner",
            "project",
            "hood",
            "structural_ancestors",
            "runs",
            "containers",
            "relationships",
        },
    )
    _schema(data, "hood snapshot")
    owner = _owner(data["owner"], "hood snapshot owner")
    project = _project(data["project"])
    hood = _exact_object(
        data["hood"], "hood snapshot hood", {"local_name", "global_name"}
    )
    local_hood = validate_component(hood["local_name"], label="local hood")
    global_hood = validate_component(hood["global_name"], label="global hood")
    if globalize_agent_name(local_hood, owner) != global_hood:
        raise AgentsSyncFormatError("hood global name is not canonical for its owner")
    structural_ancestors = _string_list(
        data["structural_ancestors"],
        "hood snapshot structural_ancestors",
        MAX_CONTAINERS,
    )
    for ancestor in structural_ancestors:
        validate_component(ancestor, label="structural ancestor")
    if tuple(sorted(set(structural_ancestors))) != structural_ancestors:
        raise AgentsSyncFormatError(
            "hood snapshot structural_ancestors must be unique and sorted"
        )
    runs = _runs(data["runs"], owner)
    containers = _containers(data["containers"], owner)
    relationships = _relationships(data["relationships"])
    snapshot = V2HoodSnapshot(
        owner,
        project,
        local_hood,
        global_hood,
        structural_ancestors,
        runs,
        containers,
        relationships,
    )
    try:
        validate_agent_relationship_batch(snapshot.relationship_batch())
    except (ValueError, RuntimeError) as exc:
        raise AgentsSyncFormatError(f"invalid hood relationships: {exc}") from exc
    return snapshot


def validate_snapshot(snapshot: V2HoodSnapshot) -> None:
    """Round-trip the strict decoder and Rust relationship validator."""

    _hood_snapshot_from_json(snapshot.to_json_dict())


def apply_payload_atomic(repo_root: Path, payload: Mapping[str, bytes]) -> bool:
    """Apply a complete prebuilt payload, restoring prior bytes on failure."""

    root = repo_root.resolve(strict=False)
    ordered = sorted(payload.items())
    if sum(len(value) for _path, value in ordered) > MAX_PAYLOAD_BYTES:
        raise AgentsSyncFormatError("publication payload exceeds the byte limit")
    resolved: list[tuple[str, Path, bytes]] = []
    for relative, content in ordered:
        validate_relative_path(relative)
        destination = repo_root / relative
        if not destination.resolve(strict=False).is_relative_to(root):
            raise AgentsSyncFormatError(f"publication escapes repository: {relative!r}")
        resolved.append((relative, destination, bytes(content)))
    changed = [
        item
        for item in resolved
        if not item[1].is_file() or item[1].read_bytes() != item[2]
    ]
    if not changed:
        return False

    stage = Path(tempfile.mkdtemp(prefix=".sase-v2-stage-", dir=repo_root))
    backups: dict[Path, bytes | None] = {}
    try:
        for relative, _destination, content in changed:
            staged = stage / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(content)
        for relative, destination, _content in changed:
            backups[destination] = (
                destination.read_bytes() if destination.is_file() else None
            )
            atomic_write_bytes(destination, (stage / relative).read_bytes())
    except Exception:
        for destination, original in reversed(tuple(backups.items())):
            if original is None:
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass
            else:
                atomic_write_bytes(destination, original)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return True


def _runs(value: object, owner: AgentOwnerIdentity) -> tuple[V2RunRecord, ...]:
    rows = _list(value, "hood snapshot runs", MAX_RUNS)
    runs = tuple(_run(row, owner, index) for index, row in enumerate(rows))
    if tuple(sorted(runs, key=lambda item: item.source_run_id)) != runs:
        raise AgentsSyncFormatError("hood snapshot runs must be stably sorted")
    return runs


def _run(value: object, owner: AgentOwnerIdentity, index: int) -> V2RunRecord:
    label = f"hood snapshot runs[{index}]"
    row = _exact_object(
        value,
        label,
        {
            "source_run_id",
            "local_name",
            "global_name",
            "state",
            "started_at",
            "finished_at",
            "dismissed_at",
            "metadata",
            "commits",
            "files",
        },
    )
    run_id = row["source_run_id"]
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        raise AgentsSyncFormatError(f"{label} has an invalid source_run_id")
    local_name = validate_component(row["local_name"], label=f"{label} local_name")
    global_name = validate_component(row["global_name"], label=f"{label} global_name")
    if globalize_agent_name(local_name, owner) != global_name:
        raise AgentsSyncFormatError(f"{label} global_name is not canonical")
    state = row["state"]
    if state not in _STATES:
        raise AgentsSyncFormatError(f"{label} has an invalid state")
    metadata = _object(row["metadata"], f"{label} metadata")
    unknown = set(metadata) - V2_METADATA_FIELDS
    if unknown:
        raise AgentsSyncFormatError(
            f"{label} metadata has unsupported fields: {', '.join(sorted(unknown))}"
        )
    _validate_json_value(metadata, f"{label} metadata")
    commits = _commits(row["commits"], label)
    raw_files = _object(row["files"], f"{label} files")
    if set(raw_files) - _FILE_KINDS:
        raise AgentsSyncFormatError(f"{label} has unsupported file kinds")
    files = tuple(
        (kind, _file_ref(raw, f"{label} file {kind}"))
        for kind, raw in sorted(raw_files.items())
    )
    return V2RunRecord(
        run_id,
        local_name,
        global_name,
        state,
        _optional_string(row["started_at"], f"{label} started_at"),
        _optional_string(row["finished_at"], f"{label} finished_at"),
        _optional_string(row["dismissed_at"], f"{label} dismissed_at"),
        tuple(sorted(metadata.items())),
        commits,
        files,
    )


def _containers(
    value: object, owner: AgentOwnerIdentity
) -> tuple[V2ContainerRecord, ...]:
    rows = _list(value, "hood snapshot containers", MAX_CONTAINERS)
    result: list[V2ContainerRecord] = []
    for index, value in enumerate(rows):
        label = f"hood snapshot containers[{index}]"
        row = _exact_object(
            value,
            label,
            {"kind", "global_name", "owner", "member_source_run_ids"},
        )
        if _owner(row["owner"], f"{label} owner") != owner:
            raise AgentsSyncFormatError(f"{label} belongs to another owner")
        kind = row["kind"]
        if kind not in _CONTAINER_KINDS:
            raise AgentsSyncFormatError(f"{label} has an invalid kind")
        global_name = validate_component(row["global_name"], label="container name")
        members = _string_list(
            row["member_source_run_ids"], f"{label} members", MAX_RUNS
        )
        result.append(V2ContainerRecord(kind, global_name, members))
    output = tuple(result)
    if tuple(sorted(output, key=lambda item: (item.kind, item.global_name))) != output:
        raise AgentsSyncFormatError("hood snapshot containers must be stably sorted")
    return output


def _relationships(value: object) -> tuple[V2RelationshipRecord, ...]:
    rows = _list(value, "hood snapshot relationships", MAX_RELATIONSHIPS)
    output: list[V2RelationshipRecord] = []
    for index, value in enumerate(rows):
        label = f"hood snapshot relationships[{index}]"
        row = _exact_object(
            value, label, {"kind", "source_run_id", "target", "required"}
        )
        kind = row["kind"]
        if kind not in _RELATIONSHIP_KINDS:
            raise AgentsSyncFormatError(f"{label} has an invalid kind")
        source = _run_id(row["source_run_id"], f"{label} source_run_id")
        required = row["required"]
        if type(required) is not bool:
            raise AgentsSyncFormatError(f"{label} required must be boolean")
        target_row = _object(row["target"], f"{label} target")
        target_kind = target_row.get("kind")
        if target_kind == "source_run_id":
            target_row = _exact_object(
                target_row, f"{label} target", {"kind", "source_run_id"}
            )
            target = V2RelationshipTarget(
                "source_run_id",
                source_run_id=_run_id(
                    target_row["source_run_id"], f"{label} target source_run_id"
                ),
            )
        elif target_kind == "global_name":
            target_row = _exact_object(
                target_row, f"{label} target", {"kind", "global_name", "owner"}
            )
            target = V2RelationshipTarget(
                "global_name",
                global_name=validate_component(
                    target_row["global_name"], label=f"{label} target global_name"
                ),
                owner=_owner(target_row["owner"], f"{label} target owner"),
            )
        else:
            raise AgentsSyncFormatError(f"{label} has an invalid target kind")
        output.append(V2RelationshipRecord(kind, source, target, required))
    return tuple(output)


def _file_ref(value: object, label: str) -> V2FileReference:
    row = _exact_object(value, label, {"path", "digest", "size_bytes"})
    return V2FileReference(
        validate_relative_path(row["path"]),
        _digest(row["digest"], f"{label} digest"),
        _nonnegative_int(row["size_bytes"], f"{label} size_bytes"),
    )


def _commits(value: object, label: str) -> tuple[CommitRecord, ...]:
    rows = _list(value, f"{label} commits", MAX_FILES)
    commits: list[CommitRecord] = []
    for index, value in enumerate(rows):
        row = _exact_object(
            value,
            f"{label} commits[{index}]",
            {"sha", "subject", "committed_at"},
        )
        sha = row["sha"]
        if not isinstance(sha, str) or not (7 <= len(sha) <= 64):
            raise AgentsSyncFormatError(f"{label} has an invalid commit SHA")
        if any(character not in "0123456789abcdef" for character in sha):
            raise AgentsSyncFormatError(f"{label} has an invalid commit SHA")
        subject = row["subject"]
        if not isinstance(subject, str) or "\x00" in subject:
            raise AgentsSyncFormatError(f"{label} has an invalid commit subject")
        commits.append(
            CommitRecord(
                sha,
                subject,
                _nonnegative_int(row["committed_at"], "committed_at"),
            )
        )
    output = tuple(commits)
    if tuple(sorted(output, key=lambda item: (item.committed_at, item.sha))) != output:
        raise AgentsSyncFormatError(f"{label} commits must be stably sorted")
    return output


def _read_json(path: Path, label: str) -> object:
    try:
        size = path.stat().st_size
        if size > MAX_JSON_BYTES:
            raise AgentsSyncFormatError(f"{label} exceeds the byte limit")
        return json.loads(path.read_text(encoding="utf-8"))
    except AgentsSyncFormatError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read {label} at {path}: {exc}") from exc


def _owner(value: object, label: str) -> AgentOwnerIdentity:
    row = _exact_object(value, label, {"username", "machine_name"})
    owner = AgentOwnerIdentity(
        validate_component(row["username"], label="username"),
        validate_component(row["machine_name"], label="machine"),
    )
    try:
        validate_agent_owner(owner)
    except (ValueError, RuntimeError) as exc:
        raise AgentsSyncFormatError(f"invalid {label}: {exc}") from exc
    return owner


def _project(value: object) -> V2ProjectIdentity:
    row = _exact_object(value, "project identity", {"key", "name"})
    key = validate_component(row["key"], label="project key")
    name = row["name"]
    if not isinstance(name, str) or not name or "\x00" in name:
        raise AgentsSyncFormatError("project name must be a non-empty string")
    return V2ProjectIdentity(key, name)


def _schema(data: Mapping[str, Any], label: str) -> None:
    if data.get("schema_version") != V2_SCHEMA_VERSION:
        raise AgentsSyncFormatError(
            f"unsupported {label} schema_version "
            f"{data.get('schema_version')!r}; expected {V2_SCHEMA_VERSION}"
        )


def _exact_object(value: object, label: str, keys: set[str]) -> dict[str, Any]:
    row = _object(value, label)
    if set(row) != keys:
        raise AgentsSyncFormatError(f"{label} has an invalid shape")
    return row


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AgentsSyncFormatError(f"{label} must be a JSON object")
    return value


def _list(value: object, label: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise AgentsSyncFormatError(f"{label} must be a list")
    if len(value) > maximum:
        raise AgentsSyncFormatError(f"{label} exceeds the count limit")
    return value


def _string_list(value: object, label: str, maximum: int) -> tuple[str, ...]:
    rows = _list(value, label, maximum)
    if not all(isinstance(item, str) and item for item in rows):
        raise AgentsSyncFormatError(f"{label} must contain non-empty strings")
    return tuple(rows)


def _run_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _RUN_ID_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"{label} is invalid")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise AgentsSyncFormatError(f"{label} must be a non-negative integer")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\x00" in value:
        raise AgentsSyncFormatError(f"{label} must be null or a non-empty string")
    return value


def _validate_json_value(value: object, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AgentsSyncFormatError(f"{label} contains a non-JSON value") from exc


__all__ = [
    "MAX_JSON_BYTES",
    "MAX_TEXT_BYTES",
    "V2_METADATA_FIELDS",
    "apply_payload_atomic",
    "content_digest",
    "file_reference",
    "owner_manifest_path",
    "read_all_owner_manifests",
    "read_hood_snapshot",
    "read_owner_manifest",
    "v2_json_bytes",
    "v2_schema_document",
    "validate_component",
    "validate_relative_path",
    "validate_snapshot",
]
