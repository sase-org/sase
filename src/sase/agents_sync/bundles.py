"""Discover, export, validate, and integrate portable completed-agent bundles."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from sase.agent.names import claim_imported_registered_name
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.io import (
    AgentsSyncFormatError,
    PORTABLE_META_FIELDS,
    atomic_write_bytes,
    atomic_write_json,
    compute_bundle_digest,
    portable_metadata_from_json,
    read_bundle,
    validate_qualified_name,
    write_bundle,
    write_manifest,
)
from sase.agents_sync.models import (
    AgentBundle,
    AgentsManifest,
    CommitRecord,
    ExportCounts,
    IntegrationCounts,
    ManifestEntry,
    PortableAgentMetadata,
    ProjectTarget,
)
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    canonical_agent_artifact_path,
    iter_agent_artifact_dirs,
    parse_agent_artifact_path,
)
from sase.core.machine_hood_facade import (
    MachineHoodIdentity,
    qualify_local_agent_name,
)
from sase.core.paths import sase_home
from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags


def export_local_bundles(
    target: ProjectTarget,
    repo_root: Path,
    manifest: AgentsManifest,
    machine: str,
    *,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> tuple[AgentsManifest, ExportCounts]:
    """Create or refresh stale locally owned bundles, then update manifest."""

    bundles, skipped, diagnostics = _build_local_bundles(
        target,
        machine,
        git_runner=git_runner,
        incremental_only=False,
    )
    entries = manifest.by_name()
    exported = 0
    refreshed = 0
    unchanged = 0
    updated_at = (now or datetime.now(UTC)).isoformat()
    for name, bundle in sorted(bundles.items()):
        existing = entries.get(name)
        if existing is not None and existing.machine != machine:
            raise AgentsSyncFormatError(
                f"local bundle {name!r} collides with foreign manifest ownership"
            )
        if existing is not None and existing.digest == bundle.digest:
            unchanged += 1
            continue
        write_bundle(repo_root, bundle)
        entries[name] = ManifestEntry(
            name=name,
            machine=machine,
            digest=bundle.digest,
            artifact_timestamp=bundle.metadata.artifact_timestamp,
            updated_at=updated_at,
        )
        if existing is None:
            exported += 1
        else:
            refreshed += 1

    updated = AgentsManifest(
        tuple(sorted(entries.values(), key=lambda item: item.name))
    )
    if updated != manifest:
        write_manifest(repo_root / "manifest.json", updated)
    return updated, ExportCounts(
        exported=exported,
        refreshed=refreshed,
        unchanged=unchanged,
        skipped=skipped,
        diagnostics=tuple(diagnostics),
    )


def integrate_foreign_bundles(
    target: ProjectTarget,
    repo_root: Path,
    manifest: AgentsManifest,
    machine: str,
) -> IntegrationCounts:
    """Validate every foreign bundle before materializing any local artifact."""

    validated: list[tuple[ManifestEntry, AgentBundle]] = []
    for entry in manifest.entries:
        if entry.machine == machine:
            continue
        validated.append((entry, read_bundle(repo_root, entry)))

    integrated = 0
    refreshed = 0
    unchanged = 0
    for entry, bundle in validated:
        existing = _find_imported_artifact(target, entry)
        if existing is not None:
            existing_meta = _read_json_object(existing / "agent_meta.json") or {}
            if existing_meta.get("imported_digest") == entry.digest:
                unchanged += 1
                continue
            _refresh_imported_artifact(existing, bundle, entry)
            refreshed += 1
            continue
        _create_imported_artifact(target, bundle, entry)
        integrated += 1
    return IntegrationCounts(integrated, refreshed, unchanged)


def _build_local_bundles(
    target: ProjectTarget,
    machine: str,
    *,
    git_runner: GitRunner = run_git,
    incremental_only: bool,
) -> tuple[dict[str, AgentBundle], int, list[str]]:
    """Build verified local transport bundles without writing the sidecar."""

    identity = MachineHoodIdentity(machine, (machine,))
    associations: dict[str, dict[str, CommitRecord]] = defaultdict(dict)
    artifacts: dict[str, tuple[Path, dict[str, Any], dict[str, Any]]] = {}
    diagnostics: list[str] = []
    skipped = 0
    root_cache: dict[str, Path | None] = {}

    for artifact_dir in iter_agent_artifact_dirs(
        target.project_key,
        ACE_RUN_WORKFLOW_DIR,
        newest_first=False,
    ):
        done = _read_json_object(artifact_dir / "done.json")
        meta = _read_json_object(artifact_dir / "agent_meta.json")
        if done is None or meta is None:
            continue
        if done.get("outcome") != "completed":
            continue
        if meta.get("imported_from_machine") is not None:
            continue
        raw_name = meta.get("name") or done.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            continue
        name = qualify_local_agent_name(raw_name, identity)
        try:
            validate_qualified_name(name, machine)
        except AgentsSyncFormatError as exc:
            diagnostics.append(f"{artifact_dir}: {exc}")
            skipped += 1
            continue
        artifacts[name] = (artifact_dir, meta, done)
        for marker in _commit_markers(artifact_dir):
            sha = _text(marker.get("result")) or _text(marker.get("commit_result"))
            cwd = _text(marker.get("cwd"))
            if sha is None or cwd is None:
                continue
            repo_root = _repository_root(Path(cwd), git_runner, root_cache)
            if repo_root is None or not _is_primary_root(repo_root, target):
                continue
            commit = _commit_record(repo_root, sha, git_runner)
            if commit is None:
                diagnostics.append(
                    f"{artifact_dir}: commit marker {sha!r} is not readable"
                )
                continue
            associations[name][commit.sha] = commit

    if not incremental_only:
        for name, commit in _historical_commit_associations(
            target, machine, git_runner
        ):
            associations[name][commit.sha] = commit

    bundles: dict[str, AgentBundle] = {}
    for name, (artifact_dir, meta, done) in sorted(artifacts.items()):
        commits = tuple(
            sorted(
                associations.get(name, {}).values(),
                key=lambda item: (item.committed_at, item.sha),
            )
        )
        if not commits:
            continue
        chat_path = _transcript_path(meta, done)
        if chat_path is None:
            diagnostics.append(f"{artifact_dir}: transcript is missing or unreadable")
            skipped += 1
            continue
        try:
            chat_bytes = chat_path.read_bytes()
        except OSError as exc:
            diagnostics.append(f"{artifact_dir}: could not read transcript: {exc}")
            skipped += 1
            continue
        metadata = _portable_metadata(artifact_dir, meta, name, machine)
        if metadata is None:
            diagnostics.append(f"{artifact_dir}: artifact timestamp/layout is invalid")
            skipped += 1
            continue
        digest = compute_bundle_digest(metadata, commits, chat_bytes)
        bundles[name] = AgentBundle(metadata, commits, chat_bytes, digest)
    return bundles, skipped, diagnostics


def count_unexported_local_agents(
    target: ProjectTarget,
    manifest: AgentsManifest,
    machine: str,
    *,
    git_runner: GitRunner = run_git,
) -> int:
    """Count incremental-marker bundles absent or stale in the local manifest."""

    bundles, _skipped, _diagnostics = _build_local_bundles(
        target,
        machine,
        git_runner=git_runner,
        incremental_only=True,
    )
    entries = manifest.by_name()
    return sum(
        1
        for name, bundle in bundles.items()
        if (entry := entries.get(name)) is None
        or entry.machine != machine
        or entry.digest != bundle.digest
    )


def _portable_metadata(
    artifact_dir: Path,
    meta: Mapping[str, Any],
    name: str,
    machine: str,
) -> PortableAgentMetadata | None:
    info = parse_agent_artifact_path(artifact_dir)
    if info is None or len(info.timestamp) != 14 or not info.timestamp.isdigit():
        return None
    fields = {
        key: meta[key]
        for key in PORTABLE_META_FIELDS
        if key in meta and meta[key] is not None
    }
    raw = {
        "schema_version": 1,
        "name": name,
        "machine": machine,
        "artifact_timestamp": info.timestamp,
        "artifact_layout_version": info.layout_version,
        **fields,
    }
    try:
        return portable_metadata_from_json(raw)
    except AgentsSyncFormatError:
        return None


def _commit_markers(artifact_dir: Path) -> list[dict[str, Any]]:
    results = _read_json(artifact_dir / "commit_results.json")
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]
    result = _read_json_object(artifact_dir / "commit_result.json")
    return [result] if result is not None else []


def _repository_root(
    cwd: Path,
    git_runner: GitRunner,
    cache: dict[str, Path | None],
) -> Path | None:
    key = str(cwd.expanduser().resolve(strict=False))
    if key in cache:
        return cache[key]
    if not cwd.is_dir():
        cache[key] = None
        return None
    result = git_runner(
        cwd,
        ["rev-parse", "--show-toplevel"],
        op="agents_sync.primary_root",
    )
    root = (
        Path(result.stdout.strip()).resolve(strict=False)
        if result.returncode == 0 and result.stdout.strip()
        else None
    )
    cache[key] = root
    return root


def _is_primary_root(root: Path, target: ProjectTarget) -> bool:
    normalized = root.resolve(strict=False)
    return any(normalized == candidate for candidate in target.primary_roots)


def _commit_record(
    repo_root: Path, sha: str, git_runner: GitRunner
) -> CommitRecord | None:
    result = git_runner(
        repo_root,
        ["show", "-s", "--format=%ct%x00%s", sha],
        op="agents_sync.commit_record",
    )
    if result.returncode != 0:
        return None
    pieces = result.stdout.rstrip("\n").split("\x00", 1)
    if len(pieces) != 2:
        return None
    try:
        committed_at = int(pieces[0])
    except ValueError:
        return None
    normalized_sha = _resolve_sha(repo_root, sha, git_runner)
    if normalized_sha is None:
        return None
    return CommitRecord(normalized_sha, pieces[1], committed_at)


def _resolve_sha(repo_root: Path, sha: str, git_runner: GitRunner) -> str | None:
    result = git_runner(
        repo_root,
        ["rev-parse", "--verify", f"{sha}^{{commit}}"],
        op="agents_sync.resolve_sha",
    )
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and value else None


def _historical_commit_associations(
    target: ProjectTarget,
    machine: str,
    git_runner: GitRunner,
) -> list[tuple[str, CommitRecord]]:
    result = git_runner(
        target.primary_checkout,
        ["log", "--format=%H%x00%ct%x00%s%x00%B%x00"],
        op="agents_sync.history",
    )
    if result.returncode != 0:
        return []
    chunks = result.stdout.split("\x00")
    associations: list[tuple[str, CommitRecord]] = []
    identity = MachineHoodIdentity(machine, (machine,))
    for index in range(0, len(chunks) - 3, 4):
        sha = chunks[index].lstrip("\r\n").strip().lower()
        committed_raw = chunks[index + 1].strip()
        subject = chunks[index + 2].rstrip("\r\n")
        message = chunks[index + 3].rstrip("\r\n")
        try:
            committed_at = int(committed_raw)
            tags = parse_trailing_commit_tags(message)
        except (ValueError, TypeError, RuntimeError):
            continue
        raw_name = tags.get("AGENT")
        commit_machine = tags.get("MACHINE")
        if not raw_name or (commit_machine and commit_machine != machine):
            continue
        name = qualify_local_agent_name(raw_name, identity)
        try:
            validate_qualified_name(name, machine)
        except AgentsSyncFormatError:
            continue
        associations.append((name, CommitRecord(sha, subject, committed_at)))
    return associations


def _transcript_path(meta: Mapping[str, Any], done: Mapping[str, Any]) -> Path | None:
    for value in (meta.get("chat_path"), done.get("response_path")):
        if not isinstance(value, str) or not value:
            continue
        path = Path(value).expanduser()
        if path.is_file():
            return path
    return None


def _find_imported_artifact(target: ProjectTarget, entry: ManifestEntry) -> Path | None:
    for artifact_dir in iter_agent_artifact_dirs(
        target.project_key,
        ACE_RUN_WORKFLOW_DIR,
        newest_first=True,
    ):
        meta = _read_json_object(artifact_dir / "agent_meta.json")
        if meta is None:
            continue
        if (
            meta.get("name") == entry.name
            and meta.get("imported_from_machine") == entry.machine
        ):
            return artifact_dir
    return None


def _create_imported_artifact(
    target: ProjectTarget,
    bundle: AgentBundle,
    entry: ManifestEntry,
) -> None:
    artifact_dir = _available_artifact_path(target, entry.artifact_timestamp)
    artifact_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=".agents-sync-import-", dir=artifact_dir.parent)
    )
    chat_path = _imported_chat_path(entry)
    try:
        meta, done = _imported_markers(bundle, entry, chat_path)
        atomic_write_json(stage / "agent_meta.json", meta)
        atomic_write_json(stage / "done.json", done)
        atomic_write_bytes(chat_path, bundle.chat_bytes)
        claim_imported_registered_name(
            entry.name,
            entry.machine,
            artifact_dir,
            digest=entry.digest,
        )
        os.replace(stage, artifact_dir)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        if not artifact_dir.exists():
            try:
                chat_path.unlink()
            except FileNotFoundError:
                pass
        raise
    update_agent_artifact_index_for_marker_mutation(artifact_dir)


def _refresh_imported_artifact(
    artifact_dir: Path,
    bundle: AgentBundle,
    entry: ManifestEntry,
) -> None:
    existing_meta = _read_json_object(artifact_dir / "agent_meta.json") or {}
    raw_chat_path = existing_meta.get("chat_path")
    chat_path = (
        Path(raw_chat_path).expanduser()
        if isinstance(raw_chat_path, str) and raw_chat_path
        else _imported_chat_path(entry)
    )
    claim_imported_registered_name(
        entry.name,
        entry.machine,
        artifact_dir,
        digest=entry.digest,
    )
    meta, done = _imported_markers(bundle, entry, chat_path)
    atomic_write_bytes(chat_path, bundle.chat_bytes)
    atomic_write_json(artifact_dir / "done.json", done)
    atomic_write_json(artifact_dir / "agent_meta.json", meta)
    update_agent_artifact_index_for_marker_mutation(artifact_dir)


def _imported_markers(
    bundle: AgentBundle,
    entry: ManifestEntry,
    chat_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    local_chat_path = _local_path_string(chat_path)
    fields = dict(bundle.metadata.fields)
    meta = {
        **fields,
        "schema_version": 1,
        "name": entry.name,
        "artifact_layout_version": bundle.metadata.artifact_layout_version,
        "chat_path": local_chat_path,
        "imported_from_machine": entry.machine,
        "imported_digest": entry.digest,
    }
    done = {
        "schema_version": 1,
        "name": entry.name,
        "timestamp": entry.artifact_timestamp,
        "artifacts_timestamp": entry.artifact_timestamp,
        "outcome": "completed",
        "response_path": local_chat_path,
        "imported_from_machine": entry.machine,
        "imported_digest": entry.digest,
        "model": fields.get("model"),
        "llm_provider": fields.get("llm_provider"),
        "vcs_provider": fields.get("vcs_provider"),
        "cl_name": fields.get("changespec_name") or fields.get("cl_name"),
        "hidden": fields.get("hidden") is True,
        "approve": fields.get("approve") is True,
        "finished_at": (
            float(bundle.commits[-1].committed_at) if bundle.commits else None
        ),
    }
    return meta, done


def _available_artifact_path(target: ProjectTarget, timestamp: str) -> Path:
    current = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    for _ in range(86_400):
        candidate = canonical_agent_artifact_path(
            target.project_key,
            ACE_RUN_WORKFLOW_DIR,
            current.strftime("%Y%m%d%H%M%S"),
        )
        if not candidate.exists():
            return candidate
        current += timedelta(seconds=1)
    raise RuntimeError("could not find a free imported artifact timestamp")


def _imported_chat_path(entry: ManifestEntry) -> Path:
    timestamp = datetime.strptime(entry.artifact_timestamp, "%Y%m%d%H%M%S")
    shard = timestamp.strftime("%Y%m")
    chat_timestamp = timestamp.strftime("%y%m%d_%H%M%S")
    safe_name = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in entry.name
    )
    return sase_home() / "chats" / shard / f"imported-{safe_name}-{chat_timestamp}.md"


def _local_path_string(path: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(Path.home().resolve())}"
    except ValueError:
        return str(path)


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    value = _read_json(path)
    return value if isinstance(value, dict) else None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "count_unexported_local_agents",
    "export_local_bundles",
    "integrate_foreign_bundles",
]
