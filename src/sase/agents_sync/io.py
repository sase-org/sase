"""Strict validation, stable digests, and atomic files for agent bundles."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from sase.agents_sync.models import (
    AgentBundle,
    AgentsManifest,
    BUNDLE_SCHEMA_VERSION,
    CommitRecord,
    MANIFEST_SCHEMA_VERSION,
    ManifestEntry,
    PortableAgentMetadata,
    sorted_fields,
)

_MACHINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_TIMESTAMP_RE = re.compile(r"^\d{14}$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_DISMISSED_PREFIX_RE = re.compile(r"^\d{6}\.(.+)$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

PORTABLE_META_FIELDS = frozenset(
    {
        "agent_clan",
        "agent_clan_generation",
        "agent_family",
        "agent_family_parallel",
        "agent_family_role",
        "approve",
        "bead_id",
        "changespec_name",
        "cl_name",
        "clan_summary",
        "clan_tribe",
        "epic_bead_id",
        "exec_llm_provider",
        "hidden",
        "llm_provider",
        "model",
        "phase_bead_id",
        "plan",
        "reasoning_effort",
        "role_suffix",
        "run_started_at",
        "stopped_at",
        "tribe",
        "vcs_provider",
        "wait_completed_at",
        "workflow_name",
    }
)

_META_REQUIRED = frozenset(
    {
        "schema_version",
        "name",
        "machine",
        "artifact_timestamp",
        "artifact_layout_version",
    }
)
_MANIFEST_ENTRY_FIELDS = frozenset(
    {
        "schema_version",
        "name",
        "machine",
        "digest",
        "artifact_timestamp",
        "updated_at",
    }
)


class AgentsSyncFormatError(ValueError):
    """Raised when untrusted sidecar data violates a persisted contract."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the canonical UTF-8 JSON representation used for digests."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _compute_bundle_digest(
    metadata: PortableAgentMetadata | Mapping[str, Any],
    commits: Sequence[CommitRecord] | Mapping[str, Any],
    chat_bytes: bytes,
) -> str:
    """Hash canonical metadata/commits JSON and exact transcript bytes."""

    meta_json = (
        metadata.to_json_dict()
        if isinstance(metadata, PortableAgentMetadata)
        else dict(metadata)
    )
    commits_json: Mapping[str, Any]
    if isinstance(commits, Mapping):
        commits_json = commits
    else:
        commits_json = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "commits": [record.to_json_dict() for record in commits],
        }
    digest = hashlib.sha256()
    for label, payload in (
        (b"meta.json", canonical_json_bytes(meta_json)),
        (b"commits.json", canonical_json_bytes(commits_json)),
        (b"chat.md", chat_bytes),
    ):
        digest.update(len(label).to_bytes(4, "big"))
        digest.update(label)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _validate_path_component(value: object, *, label: str) -> str:
    """Return a safe single path component or raise a format error."""

    if not isinstance(value, str) or not value:
        raise AgentsSyncFormatError(f"{label} must be a non-empty string")
    if value in {".", ".."} or value.startswith("."):
        raise AgentsSyncFormatError(f"unsafe {label}: {value!r}")
    if "\x00" in value or "/" in value or "\\" in value:
        raise AgentsSyncFormatError(f"unsafe {label}: {value!r}")
    if Path(value).name != value:
        raise AgentsSyncFormatError(f"unsafe {label}: {value!r}")
    return value


def validate_machine(value: object) -> str:
    machine = _validate_path_component(value, label="machine")
    if _MACHINE_RE.fullmatch(machine) is None:
        raise AgentsSyncFormatError(f"invalid machine name: {machine!r}")
    return machine


def validate_qualified_name(value: object, machine: str) -> str:
    """Validate an exact machine-qualified durable agent name."""

    name = _validate_path_component(value, label="agent name")
    core_name = name
    dismissed_match = _DISMISSED_PREFIX_RE.fullmatch(name)
    if dismissed_match is not None:
        core_name = dismissed_match.group(1)
    if not core_name.startswith(f"{machine}.") or core_name == f"{machine}.":
        raise AgentsSyncFormatError(
            f"agent name {name!r} does not belong to machine {machine!r}"
        )
    return name


def _portable_metadata_from_json(value: object) -> PortableAgentMetadata:
    data = _object(value, "meta.json")
    allowed = _META_REQUIRED | PORTABLE_META_FIELDS
    unknown = set(data) - allowed
    missing = _META_REQUIRED - set(data)
    if missing:
        raise AgentsSyncFormatError(
            f"meta.json is missing required fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise AgentsSyncFormatError(
            f"meta.json has unsupported fields: {', '.join(sorted(unknown))}"
        )
    _require_schema(data, "meta.json", BUNDLE_SCHEMA_VERSION)
    machine = validate_machine(data["machine"])
    name = validate_qualified_name(data["name"], machine)
    artifact_timestamp = _timestamp(data["artifact_timestamp"], "artifact_timestamp")
    layout = data["artifact_layout_version"]
    if type(layout) is not int or layout not in {1, 2}:
        raise AgentsSyncFormatError(
            "artifact_layout_version must be one of the supported versions 1 or 2"
        )
    fields = {key: data[key] for key in PORTABLE_META_FIELDS if key in data}
    _validate_json_value(fields, "meta.json")
    return PortableAgentMetadata(
        name=name,
        machine=machine,
        artifact_timestamp=artifact_timestamp,
        artifact_layout_version=layout,
        fields=sorted_fields(fields),
    )


def _commits_from_json(value: object) -> tuple[CommitRecord, ...]:
    data = _object(value, "commits.json")
    if set(data) != {"schema_version", "commits"}:
        raise AgentsSyncFormatError(
            "commits.json must contain only schema_version and commits"
        )
    _require_schema(data, "commits.json", BUNDLE_SCHEMA_VERSION)
    rows = data["commits"]
    if not isinstance(rows, list):
        raise AgentsSyncFormatError("commits.json commits must be a list")
    commits: list[CommitRecord] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        row = _object(raw, f"commits.json commits[{index}]")
        if set(row) != {"sha", "subject", "committed_at"}:
            raise AgentsSyncFormatError(
                f"commits.json commits[{index}] has an invalid shape"
            )
        sha = row["sha"]
        subject = row["subject"]
        committed_at = row["committed_at"]
        if not isinstance(sha, str) or _SHA_RE.fullmatch(sha) is None:
            raise AgentsSyncFormatError(f"invalid commit SHA at index {index}")
        if not isinstance(subject, str) or "\x00" in subject:
            raise AgentsSyncFormatError(f"invalid commit subject at index {index}")
        if type(committed_at) is not int or committed_at < 0:
            raise AgentsSyncFormatError(f"invalid commit time at index {index}")
        normalized_sha = sha.lower()
        if normalized_sha in seen:
            raise AgentsSyncFormatError(f"duplicate commit SHA: {sha}")
        seen.add(normalized_sha)
        commits.append(CommitRecord(normalized_sha, subject, committed_at))
    if commits != sorted(commits, key=lambda item: (item.committed_at, item.sha)):
        raise AgentsSyncFormatError("commits.json commits must be stably sorted")
    return tuple(commits)


def _manifest_from_json(value: object) -> AgentsManifest:
    data = _object(value, "manifest.json")
    if set(data) != {"schema_version", "agents"}:
        raise AgentsSyncFormatError(
            "manifest.json must contain only schema_version and agents"
        )
    _require_schema(data, "manifest.json", MANIFEST_SCHEMA_VERSION)
    raw_agents = data["agents"]
    if not isinstance(raw_agents, dict):
        raise AgentsSyncFormatError("manifest.json agents must be an object")
    entries: list[ManifestEntry] = []
    for directory_name, raw in raw_agents.items():
        safe_directory = _validate_path_component(
            directory_name, label="manifest agent directory"
        )
        row = _object(raw, f"manifest entry {safe_directory!r}")
        if set(row) != _MANIFEST_ENTRY_FIELDS:
            raise AgentsSyncFormatError(
                f"manifest entry {safe_directory!r} has an invalid shape"
            )
        _require_schema(
            row, f"manifest entry {safe_directory!r}", BUNDLE_SCHEMA_VERSION
        )
        machine = validate_machine(row["machine"])
        name = validate_qualified_name(row["name"], machine)
        if name != safe_directory:
            raise AgentsSyncFormatError(
                f"manifest key {safe_directory!r} does not match entry name {name!r}"
            )
        digest = row["digest"]
        if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
            raise AgentsSyncFormatError(
                f"manifest entry {name!r} has an invalid digest"
            )
        updated_at = row["updated_at"]
        if not isinstance(updated_at, str) or not updated_at:
            raise AgentsSyncFormatError(
                f"manifest entry {name!r} has an invalid updated_at"
            )
        entries.append(
            ManifestEntry(
                name=name,
                machine=machine,
                digest=digest,
                artifact_timestamp=_timestamp(
                    row["artifact_timestamp"], "artifact_timestamp"
                ),
                updated_at=updated_at,
            )
        )
    return AgentsManifest(tuple(sorted(entries, key=lambda item: item.name)))


def read_manifest(path: Path) -> AgentsManifest:
    return _manifest_from_json(_read_json(path, "manifest.json"))


def manifest_from_bytes(payload: bytes) -> AgentsManifest:
    """Decode a strict legacy manifest captured from an immutable Git object."""

    try:
        value = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not decode manifest.json: {exc}") from exc
    return _manifest_from_json(value)


def read_bundle(repo_root: Path, entry: ManifestEntry) -> AgentBundle:
    """Read and fully verify one manifest-advertised bundle."""

    bundle_dir = repo_root / "agents" / entry.name
    if bundle_dir.parent != repo_root / "agents":
        raise AgentsSyncFormatError(f"unsafe bundle path for {entry.name!r}")
    metadata_raw = _read_json(bundle_dir / "meta.json", "meta.json")
    commits_raw = _read_json(bundle_dir / "commits.json", "commits.json")
    try:
        chat_bytes = (bundle_dir / "chat.md").read_bytes()
    except OSError as exc:
        raise AgentsSyncFormatError(
            f"could not read chat.md for {entry.name!r}: {exc}"
        ) from exc
    metadata = _portable_metadata_from_json(metadata_raw)
    commits = _commits_from_json(commits_raw)
    if metadata.name != entry.name or metadata.machine != entry.machine:
        raise AgentsSyncFormatError(
            f"bundle identity for {entry.name!r} does not match its manifest entry"
        )
    if metadata.artifact_timestamp != entry.artifact_timestamp:
        raise AgentsSyncFormatError(
            f"bundle timestamp for {entry.name!r} does not match its manifest entry"
        )
    digest = _compute_bundle_digest(metadata, commits, chat_bytes)
    if digest != entry.digest:
        raise AgentsSyncFormatError(
            f"bundle digest mismatch for {entry.name!r}: expected {entry.digest}"
        )
    return AgentBundle(metadata, commits, chat_bytes, digest)


def atomic_write_json(path: Path, value: object) -> None:
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    atomic_write_bytes(path, payload)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write bytes through a same-directory temporary file and ``os.replace``."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    replaced = False
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        replaced = True
    finally:
        if temp_path is not None and not replaced:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read {label} at {path}: {exc}") from exc


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AgentsSyncFormatError(f"{label} must be a JSON object")
    return value


def _require_schema(data: Mapping[str, Any], label: str, expected: int) -> None:
    version = data.get("schema_version")
    if type(version) is not int or version != expected:
        raise AgentsSyncFormatError(
            f"unsupported {label} schema_version {version!r}; expected {expected}"
        )


def _timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or _TIMESTAMP_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"{label} must be a 14-digit timestamp")
    return value


def _validate_json_value(value: object, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AgentsSyncFormatError(f"{label} contains a non-JSON value") from exc


__all__ = [
    "AgentsSyncFormatError",
    "PORTABLE_META_FIELDS",
    "atomic_write_bytes",
    "atomic_write_json",
    "canonical_json_bytes",
    "manifest_from_bytes",
    "read_bundle",
    "read_manifest",
    "validate_machine",
    "validate_qualified_name",
]
