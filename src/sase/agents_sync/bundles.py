"""Discover, export, validate, and integrate portable completed-agent bundles."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from sase.agent.names import claim_imported_registered_name
from sase.agents_sync.git import GitRunner
from sase.agents_sync.incoming_cache_legacy import legacy_group_machine_hood
from sase.agents_sync.inventory_io import is_imported
from sase.agents_sync.io import (
    AgentsSyncFormatError,
    atomic_write_bytes,
    atomic_write_json,
    read_bundle,
)
from sase.agents_sync.models import (
    AgentBundle,
    AgentsManifest,
    CommitRecord,
    IntegrationCounts,
    ManifestEntry,
    ProjectTarget,
)
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    canonical_agent_artifact_path,
    iter_agent_artifact_dirs,
)
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    LegacyV1GroupOwnershipClassification,
    LegacyV1GroupOwnershipEvidence,
    classify_legacy_v1_group_ownership,
)
from sase.core.commit_sha_facade import commit_shas_equivalent
from sase.core.machine_hood_facade import machine_qualify_v1_transport_agent_name
from sase.core.paths import sase_home


def integrate_foreign_bundles(
    target: ProjectTarget,
    repo_root: Path,
    manifest: AgentsManifest,
    owner: AgentOwnerIdentity,
    *,
    owner_v2_hoods: Collection[str] = (),
) -> IntegrationCounts:
    """Validate every selected v1 bundle before materializing local history.

    The whole legacy hood is owner-observed when shared v1 ownership evidence
    proves it. Owner-observed groups are recorded unchanged and never reach
    imported artifact creation.
    """

    validated: list[tuple[ManifestEntry, AgentBundle]] = []
    for entry in manifest.entries:
        validated.append((entry, read_bundle(repo_root, entry)))

    group_machine, group_hood = legacy_group_machine_hood(manifest)
    v2_hood_published = group_hood in owner_v2_hoods
    artifact_rows = (
        ()
        if v2_hood_published and group_machine == owner.machine_name
        else _v1_artifact_rows(target)
    )
    rows_by_timestamp: dict[
        str,
        list[tuple[Path, dict[str, Any], dict[str, Any]]],
    ] = defaultdict(list)
    imported_by_identity: dict[
        tuple[str, str],
        tuple[Path, dict[str, Any]],
    ] = {}
    for artifact, meta, done in artifact_rows:
        rows_by_timestamp[artifact.name].append((artifact, meta, done))
        name = meta.get("name")
        machine_name = meta.get("imported_from_machine")
        if isinstance(name, str) and isinstance(machine_name, str):
            imported_by_identity.setdefault(
                (name, machine_name),
                (artifact, meta),
            )

    proven_entry_count = sum(
        _find_proven_current_v1_artifact(
            target,
            entry,
            bundle,
            owner.machine_name,
            candidates=tuple(rows_by_timestamp.get(entry.artifact_timestamp, ())),
        )
        is not None
        for entry, bundle in validated
        if entry.machine == owner.machine_name
    )
    group_ownership = classify_legacy_v1_group_ownership(
        group_machine,
        owner,
        LegacyV1GroupOwnershipEvidence(
            v2_hood_published,
            proven_entry_count,
            len(validated),
        ),
    )
    if group_ownership is LegacyV1GroupOwnershipClassification.OWNER_OBSERVED:
        return IntegrationCounts(
            unchanged=len(validated),
            owner_observed_groups=1,
        )

    integrated = 0
    refreshed = 0
    unchanged = 0
    diagnostics: list[str] = []
    self_owned = group_machine == owner.machine_name
    for entry, bundle in validated:
        if self_owned:
            local_artifact = _local_self_artifact(
                entry,
                owner.machine_name,
                rows_by_timestamp.get(entry.artifact_timestamp, ()),
            )
            if local_artifact is not None:
                unchanged += 1
                diagnostics.append(
                    f"{group_hood}: {entry.name} already present locally at "
                    f"{local_artifact}; skipped self-import"
                )
                continue
        imported = imported_by_identity.get((entry.name, entry.machine))
        if imported is not None:
            existing, existing_meta = imported
            if existing_meta.get("imported_digest") == entry.digest:
                unchanged += 1
                continue
            _refresh_imported_artifact(
                existing,
                bundle,
                entry,
                owner=owner,
                group_ownership=group_ownership,
            )
            imported_by_identity[(entry.name, entry.machine)] = (
                existing,
                {**existing_meta, "imported_digest": entry.digest},
            )
            refreshed += 1
            continue
        _create_imported_artifact(
            target,
            bundle,
            entry,
            owner=owner,
            group_ownership=group_ownership,
        )
        integrated += 1
    return IntegrationCounts(
        integrated, refreshed, unchanged, diagnostics=tuple(diagnostics)
    )


def _find_proven_current_v1_artifact(
    target: ProjectTarget,
    entry: ManifestEntry,
    bundle: AgentBundle,
    machine: str,
    *,
    candidates: tuple[tuple[Path, dict[str, Any], dict[str, Any]], ...] | None = None,
) -> Path | None:
    """Return a local artifact only when name, timestamp, and commit agree."""

    source_shas = {commit.sha.lower() for commit in bundle.commits}
    if not source_shas:
        return None
    rows = _v1_artifact_rows(target) if candidates is None else candidates
    for artifact_dir, meta, done in rows:
        if artifact_dir.name != entry.artifact_timestamp:
            continue
        if is_imported(meta, done):
            continue
        raw_name = _text(meta.get("name")) or _text(done.get("name"))
        if raw_name is None:
            continue
        if machine_qualify_v1_transport_agent_name(raw_name, machine) != entry.name:
            continue
        local_shas = {
            sha.lower()
            for marker in commit_markers(artifact_dir)
            if (
                sha := _text(marker.get("result"))
                or _text(marker.get("commit_result"))
                or _text(marker.get("sha"))
            )
            is not None
        }
        if any(
            commit_shas_equivalent(source_sha, local_sha)
            for source_sha in source_shas
            for local_sha in local_shas
        ):
            return artifact_dir
    return None


def _local_self_artifact(
    entry: ManifestEntry,
    machine_name: str,
    candidates: Collection[tuple[Path, dict[str, Any], dict[str, Any]]],
) -> Path | None:
    """Return a local, non-imported artifact this machine already has for entry.

    Matches on artifact timestamp and machine-qualified name only, with no
    commit-SHA requirement, so it also catches cases where the v1 evidence
    proof path could not establish a match.
    """

    for artifact_dir, meta, done in candidates:
        if is_imported(meta, done):
            continue
        raw_name = _text(meta.get("name")) or _text(done.get("name"))
        if raw_name is None:
            continue
        if (
            machine_qualify_v1_transport_agent_name(raw_name, machine_name)
            != entry.name
        ):
            continue
        return artifact_dir
    return None


def v1_artifact_rows(
    target: ProjectTarget,
) -> tuple[tuple[Path, dict[str, Any], dict[str, Any]], ...]:
    """Return the local artifact evidence rows used by legacy-v1 ownership.

    ``done.json`` is optional: dismissing an agent unlinks it along with the
    other loader markers, so ``agent_meta.json`` is the authoritative marker
    of a real artifact. A missing or unparseable ``done.json`` yields an
    empty dict for that row rather than dropping the row.
    """

    return _v1_artifact_rows(target)


def _v1_artifact_rows(
    target: ProjectTarget,
) -> tuple[tuple[Path, dict[str, Any], dict[str, Any]], ...]:
    rows: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    for artifact in iter_agent_artifact_dirs(
        target.project_key,
        ACE_RUN_WORKFLOW_DIR,
        newest_first=False,
    ):
        meta = _read_json_object(artifact / "agent_meta.json")
        if meta is None:
            continue
        done = _read_json_object(artifact / "done.json") or {}
        rows.append((artifact, meta, done))
    return tuple(rows)


def commit_markers(artifact_dir: Path) -> list[dict[str, Any]]:
    results = _read_json(artifact_dir / "commit_results.json")
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]
    result = _read_json_object(artifact_dir / "commit_result.json")
    return [result] if result is not None else []


def repository_root(
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


def is_primary_root(root: Path, target: ProjectTarget) -> bool:
    normalized = root.resolve(strict=False)
    return any(normalized == candidate for candidate in target.primary_roots)


def commit_record(
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


def _create_imported_artifact(
    target: ProjectTarget,
    bundle: AgentBundle,
    entry: ManifestEntry,
    *,
    owner: AgentOwnerIdentity,
    group_ownership: LegacyV1GroupOwnershipClassification,
) -> None:
    _guard_owner_observed_legacy_import(entry, owner, group_ownership)
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
            target_owner=owner,
            group_ownership=group_ownership,
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
    *,
    owner: AgentOwnerIdentity,
    group_ownership: LegacyV1GroupOwnershipClassification,
) -> None:
    _guard_owner_observed_legacy_import(entry, owner, group_ownership)
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
        target_owner=owner,
        group_ownership=group_ownership,
    )
    meta, done = _imported_markers(bundle, entry, chat_path)
    atomic_write_bytes(chat_path, bundle.chat_bytes)
    atomic_write_json(artifact_dir / "done.json", done)
    atomic_write_json(artifact_dir / "agent_meta.json", meta)
    update_agent_artifact_index_for_marker_mutation(artifact_dir)


def _guard_owner_observed_legacy_import(
    entry: ManifestEntry,
    owner: AgentOwnerIdentity,
    group_ownership: LegacyV1GroupOwnershipClassification,
) -> None:
    if (
        group_ownership is LegacyV1GroupOwnershipClassification.OWNER_OBSERVED
        and entry.machine == owner.machine_name
    ):
        raise AgentsSyncFormatError(
            "refusing to import an owner-observed legacy v1 agent"
        )


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
        "imported_owner_kind": "username_unknown_v1",
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
        "imported_owner_kind": "username_unknown_v1",
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
    "integrate_foreign_bundles",
    "v1_artifact_rows",
]
