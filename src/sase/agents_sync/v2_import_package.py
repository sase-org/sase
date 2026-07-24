"""Strict, mutation-free discovery of owner-sharded v2 import packages."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from sase.agents_sync.io import AgentsSyncFormatError, read_manifest
from sase.agents_sync.models import AgentsManifest
from sase.agents_sync.v2_io import (
    MAX_JSON_BYTES,
    MAX_PAYLOAD_BYTES,
    MAX_TEXT_BYTES,
    content_digest,
    read_hood_snapshot,
    read_owner_manifest,
    validate_component,
    validate_relative_path,
)
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2RunCommitsPayload,
    V2RunMetadataPayload,
    V2RunRecord,
    V2RunStatePayload,
)
from sase.agents_sync.v2_run_io import (
    run_commits_from_json,
    run_metadata_from_json,
    run_state_from_json,
)
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    rewrite_agent_relationship_batch,
    validate_agent_owner,
)

_REQUIRED_RUN_FILES = frozenset({"meta", "state", "commits"})
_RUN_FILE_NAMES = {
    "meta": "meta.json",
    "state": "state.json",
    "commits": "commits.json",
    "prompt": "prompt.md",
    "chat": "chat.md",
    "embedded_workflows": "embedded_workflows.json",
    "prompt_steps": "prompt_steps.json",
}


@dataclass(frozen=True, slots=True)
class ValidatedV2RunPayload:
    """One snapshot run plus every verified referenced payload."""

    record: V2RunRecord
    metadata: V2RunMetadataPayload
    state: V2RunStatePayload
    commits: V2RunCommitsPayload
    files: tuple[tuple[str, bytes], ...]

    def file_bytes(self, kind: str) -> bytes | None:
        return dict(self.files).get(kind)


@dataclass(frozen=True, slots=True)
class ValidatedV2HoodPackage:
    """A complete owner hood that is safe to preflight for local import."""

    manifest: V2OwnerManifest
    hood: str
    entry: V2OwnerHoodEntry
    snapshot: V2HoodSnapshot
    runs: tuple[ValidatedV2RunPayload, ...]

    @property
    def owner(self) -> AgentOwnerIdentity:
        return self.manifest.owner

    @property
    def transaction_identity(self) -> tuple[str, str, str, str]:
        owner = self.owner
        return (owner.username, owner.machine_name, self.hood, self.entry.digest)


@dataclass(frozen=True, slots=True)
class _AgentImportDiscovery:
    """Validated v2 packages and separately decoded legacy v1 candidates."""

    v2_packages: tuple[ValidatedV2HoodPackage, ...] = ()
    legacy_manifest: AgentsManifest = AgentsManifest()
    diagnostics: tuple[str, ...] = ()


def discover_agent_imports(
    repo_root: Path,
    project: V2ProjectIdentity,
) -> _AgentImportDiscovery:
    """Discover every independently valid v2 hood and the legacy v1 manifest.

    A malformed owner manifest or hood is reported as one quarantine diagnostic
    and does not prevent unrelated owners from being returned.
    """

    packages: list[ValidatedV2HoodPackage] = []
    diagnostics: list[str] = []
    pattern = "users/*/machines/*/manifest.json"
    for path in sorted(repo_root.glob(pattern), key=lambda item: item.as_posix()):
        try:
            relative = path.relative_to(repo_root).as_posix()
            parts = relative.split("/")
            owner = AgentOwnerIdentity(
                validate_component(parts[1], label="username"),
                validate_component(parts[3], label="machine"),
            )
            validate_agent_owner(owner)
            manifest = read_owner_manifest(repo_root, owner, project)
        except (AgentsSyncFormatError, ValueError, RuntimeError, OSError) as exc:
            diagnostics.append(f"{path}: quarantined v2 owner manifest: {exc}")
            continue
        for hood, entry in manifest.hoods:
            try:
                packages.append(
                    _validate_v2_hood_package(repo_root, manifest, hood, entry)
                )
            except (AgentsSyncFormatError, ValueError, RuntimeError, OSError) as exc:
                diagnostics.append(
                    f"{owner.username}.{owner.machine_name}.{hood}: "
                    f"quarantined v2 hood: {exc}"
                )

    legacy = AgentsManifest()
    legacy_path = repo_root / "manifest.json"
    if legacy_path.is_file():
        try:
            legacy = read_manifest(legacy_path)
        except AgentsSyncFormatError as exc:
            diagnostics.append(f"manifest.json: quarantined legacy v1 manifest: {exc}")
    return _AgentImportDiscovery(
        tuple(
            sorted(
                packages,
                key=lambda package: (
                    package.owner.username,
                    package.owner.machine_name,
                    package.hood,
                ),
            )
        ),
        legacy,
        tuple(diagnostics),
    )


def _validate_v2_hood_package(
    repo_root: Path,
    manifest: V2OwnerManifest,
    hood: str,
    entry: V2OwnerHoodEntry,
) -> ValidatedV2HoodPackage:
    """Load and verify one complete hood without mutating local state."""

    validate_component(hood, label="hood")
    snapshot_path = _snapshot_path(manifest.owner, hood)
    snapshot_bytes = _read_bounded_file(
        repo_root,
        snapshot_path,
        maximum=MAX_JSON_BYTES,
        label="hood snapshot",
    )
    if content_digest(snapshot_bytes) != entry.digest:
        raise AgentsSyncFormatError("hood snapshot digest does not match manifest")
    snapshot = read_hood_snapshot(repo_root / snapshot_path)
    if (
        snapshot.owner != manifest.owner
        or snapshot.project != manifest.project
        or snapshot.local_hood != hood
    ):
        raise AgentsSyncFormatError("hood snapshot identity does not match manifest")
    if len(snapshot.runs) != entry.run_count:
        raise AgentsSyncFormatError("hood run_count does not match snapshot")
    family_count = sum(row.kind == "family" for row in snapshot.containers)
    if family_count != entry.family_count:
        raise AgentsSyncFormatError("hood family_count does not match snapshot")

    source_ids = [run.source_run_id for run in snapshot.runs]
    global_names = [run.global_name for run in snapshot.runs]
    if len(set(source_ids)) != len(source_ids):
        raise AgentsSyncFormatError("hood contains duplicate source run IDs")
    if len(set(global_names)) != len(global_names):
        raise AgentsSyncFormatError("hood contains duplicate global agent names")

    expected_files = _expected_manifest_files(snapshot)
    if entry.files != expected_files:
        raise AgentsSyncFormatError("manifest file set does not match hood snapshot")

    total_bytes = len(snapshot_bytes)
    seen_paths = {snapshot_path}
    verified_runs: list[ValidatedV2RunPayload] = []
    for run in snapshot.runs:
        verified, payload_bytes = _validate_run(repo_root, snapshot, run, seen_paths)
        total_bytes += payload_bytes
        if total_bytes > MAX_PAYLOAD_BYTES:
            raise AgentsSyncFormatError("hood aggregate payload exceeds the byte limit")
        verified_runs.append(verified)

    # Browsing files are declared by the manifest but are not run references.
    referenced = {
        reference.path for run in snapshot.runs for _kind, reference in run.files
    }
    for relative in entry.files:
        if relative == snapshot_path or relative in referenced:
            continue
        payload = _read_bounded_file(
            repo_root,
            relative,
            maximum=MAX_TEXT_BYTES,
            label="declared hood file",
        )
        _decode_utf8(payload, relative)
        total_bytes += len(payload)
        if total_bytes > MAX_PAYLOAD_BYTES:
            raise AgentsSyncFormatError("hood aggregate payload exceeds the byte limit")

    # Force the Rust rewriter to validate the complete destination map contract
    # while IDs are still harmless in-memory placeholders.
    rewrite_agent_relationship_batch(
        snapshot.relationship_batch(),
        {source_id: f"validated-{index}" for index, source_id in enumerate(source_ids)},
    )
    return ValidatedV2HoodPackage(
        manifest,
        hood,
        entry,
        snapshot,
        tuple(verified_runs),
    )


def _validate_run(
    repo_root: Path,
    snapshot: V2HoodSnapshot,
    run: V2RunRecord,
    seen_paths: set[str],
) -> tuple[ValidatedV2RunPayload, int]:
    files = dict(run.files)
    missing = _REQUIRED_RUN_FILES - set(files)
    if missing:
        raise AgentsSyncFormatError(
            f"run {run.source_run_id!r} is missing required files: "
            + ", ".join(sorted(missing))
        )
    if len(files) != len(run.files):
        raise AgentsSyncFormatError(f"run {run.source_run_id!r} repeats a file kind")

    payloads: list[tuple[str, bytes]] = []
    total_bytes = 0
    expected_root = f"agents/{run.global_name}"
    for kind, reference in run.files:
        expected_name = _RUN_FILE_NAMES.get(kind)
        if expected_name is None:
            raise AgentsSyncFormatError(f"unsupported run file kind {kind!r}")
        expected_path = f"{expected_root}/{expected_name}"
        if reference.path != expected_path:
            raise AgentsSyncFormatError(
                f"run file {kind!r} has unexpected path {reference.path!r}"
            )
        if reference.path in seen_paths:
            raise AgentsSyncFormatError(
                f"hood repeats referenced path {reference.path!r}"
            )
        seen_paths.add(reference.path)
        maximum = (
            MAX_JSON_BYTES
            if kind
            in {
                "meta",
                "state",
                "commits",
                "embedded_workflows",
                "prompt_steps",
            }
            else MAX_TEXT_BYTES
        )
        payload = _read_bounded_file(
            repo_root,
            reference.path,
            maximum=maximum,
            label=f"run {kind} payload",
        )
        if len(payload) != reference.size_bytes:
            raise AgentsSyncFormatError(
                f"declared size mismatch for {reference.path!r}"
            )
        if content_digest(payload) != reference.digest:
            raise AgentsSyncFormatError(f"file digest mismatch for {reference.path!r}")
        _decode_utf8(payload, reference.path)
        payloads.append((kind, payload))
        total_bytes += len(payload)

    json_kinds = {
        "meta",
        "state",
        "commits",
        "embedded_workflows",
        "prompt_steps",
    }
    decoded = {
        kind: _decode_json(payload, kind)
        for kind, payload in payloads
        if kind in json_kinds
    }
    metadata = run_metadata_from_json(decoded["meta"])
    state = run_state_from_json(decoded["state"])
    commits = run_commits_from_json(decoded["commits"])
    if (
        metadata.owner != snapshot.owner
        or metadata.project != snapshot.project
        or metadata.source_run_id != run.source_run_id
        or metadata.local_name != run.local_name
        or metadata.global_name != run.global_name
        or metadata.metadata != run.metadata
    ):
        raise AgentsSyncFormatError("meta.json disagrees with its snapshot run")
    if (
        state.source_run_id != run.source_run_id
        or state.state != run.state
        or state.started_at != run.started_at
        or state.finished_at != run.finished_at
        or state.dismissed_at != run.dismissed_at
    ):
        raise AgentsSyncFormatError("state.json disagrees with its snapshot run")
    if commits.source_run_id != run.source_run_id or commits.commits != run.commits:
        raise AgentsSyncFormatError("commits.json disagrees with its snapshot run")
    if "embedded_workflows" in decoded:
        _validate_embedded_workflows(decoded["embedded_workflows"])
    if "prompt_steps" in decoded:
        _validate_prompt_steps(decoded["prompt_steps"])
    return (
        ValidatedV2RunPayload(
            run,
            metadata,
            state,
            commits,
            tuple(payloads),
        ),
        total_bytes,
    )


def _validate_prompt_steps(value: object) -> None:
    if not isinstance(value, list) or len(value) > 4_096:
        raise AgentsSyncFormatError("prompt_steps.json must be a bounded list")
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != {"file_name", "marker"}:
            raise AgentsSyncFormatError(
                f"prompt_steps.json entry {index} has an invalid shape"
            )
        name = raw["file_name"]
        if (
            not isinstance(name, str)
            or not name.startswith("prompt_step_")
            or not name.endswith(".json")
            or Path(name).name != name
            or name in seen
        ):
            raise AgentsSyncFormatError(
                f"prompt_steps.json entry {index} has an invalid file_name"
            )
        seen.add(name)
        marker = raw["marker"]
        if not isinstance(marker, dict):
            raise AgentsSyncFormatError(
                f"prompt_steps.json entry {index} marker must be an object"
            )


def _validate_embedded_workflows(value: object) -> None:
    if not isinstance(value, list) or len(value) > 4_096:
        raise AgentsSyncFormatError(
            "embedded_workflows.json must be a bounded JSON list"
        )
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != {"name", "args", "tags"}:
            raise AgentsSyncFormatError(
                f"embedded_workflows.json entry {index} has an invalid shape"
            )
        if (
            not isinstance(raw["name"], str)
            or not raw["name"]
            or not isinstance(raw["args"], dict)
            or not isinstance(raw["tags"], list)
            or not all(isinstance(tag, str) for tag in raw["tags"])
        ):
            raise AgentsSyncFormatError(
                f"embedded_workflows.json entry {index} has invalid fields"
            )


def _expected_manifest_files(snapshot: V2HoodSnapshot) -> tuple[str, ...]:
    owner = snapshot.owner
    files = {
        _snapshot_path(owner, snapshot.local_hood),
        (
            f"users/{owner.username}/machines/{owner.machine_name}/"
            f"hoods/{snapshot.local_hood}/README.md"
        ),
    }
    for run in snapshot.runs:
        files.add(f"agents/{run.global_name}/README.md")
        files.update(reference.path for _kind, reference in run.files)
    files.update(
        f"families/{container.global_name}.md"
        for container in snapshot.containers
        if container.kind == "family"
    )
    return tuple(sorted(files))


def _snapshot_path(owner: AgentOwnerIdentity, hood: str) -> str:
    return (
        f"users/{owner.username}/machines/{owner.machine_name}/"
        f"hoods/{hood}/snapshot.json"
    )


def _read_bounded_file(
    repo_root: Path,
    relative: str,
    *,
    maximum: int,
    label: str,
) -> bytes:
    validate_relative_path(relative)
    root = repo_root.resolve(strict=False)
    path = repo_root / relative
    if not path.resolve(strict=False).is_relative_to(root):
        raise AgentsSyncFormatError(f"{label} escapes the sidecar root")
    try:
        if path.stat().st_size > maximum:
            raise AgentsSyncFormatError(f"{relative!r} exceeds the byte limit")
        return path.read_bytes()
    except AgentsSyncFormatError:
        raise
    except OSError as exc:
        raise AgentsSyncFormatError(f"could not read {relative!r}: {exc}") from exc


def _decode_utf8(payload: bytes, label: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgentsSyncFormatError(f"{label!r} is not valid UTF-8") from exc


def _decode_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(_decode_utf8(payload, f"{label}.json"))
    except json.JSONDecodeError as exc:
        raise AgentsSyncFormatError(f"{label}.json is invalid JSON") from exc


__all__ = [
    "ValidatedV2HoodPackage",
    "ValidatedV2RunPayload",
    "discover_agent_imports",
]
