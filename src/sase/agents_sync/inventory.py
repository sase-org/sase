"""Indexed, project-scoped inventory for owner-sharded v2 publication."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from sase.agents_sync.bundles import (
    commit_markers,
    commit_record,
    is_primary_root,
    repository_root,
)
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.v2_io import (
    MAX_JSON_BYTES,
    MAX_TEXT_BYTES,
    V2_METADATA_FIELDS,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    agent_local_hood,
    agent_name_in_hood,
    globalize_agent_name,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
)
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_projects_dir
from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags


@dataclass(frozen=True, slots=True)
class _InventoryRelationship:
    kind: str
    target: str
    target_kind: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class InventoryRun:
    source_run_id: str
    local_name: str
    global_name: str
    state: str
    started_at: str | None
    finished_at: str | None
    dismissed_at: str | None
    metadata: tuple[tuple[str, Any], ...]
    commits: tuple[CommitRecord, ...]
    prompt_bytes: bytes | None
    chat_bytes: bytes | None
    family_name: str | None
    clan_name: str | None
    relationships: tuple[_InventoryRelationship, ...]
    timestamp: str


@dataclass(frozen=True, slots=True)
class ProjectHoodInventory:
    owner: AgentOwnerIdentity
    project_key: str
    runs: tuple[InventoryRun, ...]
    diagnostics: tuple[str, ...] = ()

    def hood_runs(self, hood: str) -> tuple[InventoryRun, ...]:
        return tuple(
            run for run in self.runs if agent_name_in_hood(run.local_name, hood)
        )

    def eligible_hoods(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {agent_local_hood(run.local_name) for run in self.runs if run.commits}
            )
        )


def build_project_hood_inventory(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    *,
    git_runner: GitRunner = run_git,
) -> ProjectHoodInventory:
    """Load all locally owned process records selected by persistent indexes."""

    if identity.owner is None:
        raise AgentsSyncFormatError("v2 publication requires an owner identity")
    owner = identity.owner
    history = _historical_associations(target, identity, git_runner)
    records, diagnostics = _indexed_records(target)
    runs: list[InventoryRun] = []
    root_cache: dict[str, Path | None] = {}
    for record in records:
        try:
            run = _run_from_artifact(
                target,
                record,
                identity,
                history,
                root_cache,
                git_runner,
            )
        except AgentsSyncFormatError as exc:
            diagnostics.append(f"{record.artifact_dir}: {exc}")
            continue
        if run is not None:
            runs.append(run)

    for raw, source_label in _dismissed_records(target):
        try:
            run = _run_from_dismissed(
                raw,
                source_label,
                target.project_key,
                identity,
                history,
            )
        except AgentsSyncFormatError as exc:
            diagnostics.append(f"{source_label}: {exc}")
            continue
        if run is not None:
            runs.append(run)

    # A canonical global name identifies one durable run. Prefer live/indexed
    # state over its dismissed archive copy, then the most informative/newest
    # record, while unioning commit associations.
    by_global: dict[str, InventoryRun] = {}
    for run in sorted(runs, key=_run_preference):
        existing = by_global.get(run.global_name)
        if existing is None:
            by_global[run.global_name] = run
            continue
        commits = {commit.sha: commit for commit in (*existing.commits, *run.commits)}
        preferred = run
        by_global[run.global_name] = replace(
            preferred,
            commits=tuple(
                sorted(commits.values(), key=lambda item: (item.committed_at, item.sha))
            ),
            prompt_bytes=preferred.prompt_bytes or existing.prompt_bytes,
            chat_bytes=preferred.chat_bytes or existing.chat_bytes,
        )
    return ProjectHoodInventory(
        owner,
        target.project_key,
        tuple(sorted(by_global.values(), key=lambda item: item.source_run_id)),
        tuple(diagnostics),
    )


def _indexed_records(
    target: ProjectTarget,
) -> tuple[tuple[AgentArtifactRecordWire, ...], list[str]]:
    projects_root = sase_projects_dir()
    options = AgentArtifactScanOptionsWire(
        include_prompt_step_markers=True,
        include_raw_prompt_snippets=False,
        only_workflow_dirs=("ace-run",),
        max_records=None,
        newest_first=False,
        include_done_markers=True,
        include_workflow_state=True,
        include_waiting=True,
        only_projects=(target.project_key,),
        include_project_states=("all",),
    )
    diagnostics: list[str] = []
    index = default_agent_artifact_index_path()
    try:
        if index.is_file():
            snapshot = query_agent_artifact_index(
                index,
                projects_root,
                AgentArtifactIndexQueryWire(
                    include_active=True,
                    include_recent_completed=False,
                    include_full_history=True,
                    active_limit=None,
                    recent_completed_limit=None,
                    include_hidden=True,
                ),
                options,
            )
        else:
            snapshot = scan_agent_artifacts(projects_root, options)
    except (OSError, RuntimeError, ValueError, ImportError, AttributeError) as exc:
        raise AgentsSyncFormatError(
            f"could not query the agent artifact index: {exc}"
        ) from exc
    if snapshot.stats.json_decode_errors or snapshot.stats.os_errors:
        diagnostics.append(
            "artifact index scan reported "
            f"{snapshot.stats.json_decode_errors} JSON and "
            f"{snapshot.stats.os_errors} filesystem errors"
        )
    return tuple(snapshot.records), diagnostics


def _run_from_artifact(
    target: ProjectTarget,
    record: AgentArtifactRecordWire,
    identity: AgentIdentitySnapshot,
    history: dict[str, tuple[CommitRecord, ...]],
    root_cache: dict[str, Path | None],
    git_runner: GitRunner,
) -> InventoryRun | None:
    artifact = Path(record.artifact_dir)
    projects_root = sase_projects_dir().resolve(strict=False)
    if not artifact.resolve(strict=False).is_relative_to(projects_root):
        raise AgentsSyncFormatError("indexed artifact path escapes the projects root")
    meta = _read_json_object(artifact / "agent_meta.json")
    done = _read_json_object(artifact / "done.json", required=False)
    if meta is None:
        return None
    if _is_imported(meta, done):
        return None
    raw_name = _text(meta.get("name")) or _text((done or {}).get("name"))
    if raw_name is None:
        return None
    local_name = _canonical_local_name(raw_name, identity)
    owner = _require_owner(identity)
    timestamp = record.timestamp
    source_run_id = _source_run_id(
        target.project_key,
        record.workflow_dir_name,
        _text(meta.get("artifact_agent_id")) or timestamp,
    )
    commits = {item.sha: item for item in history.get(local_name, ())}
    for marker in commit_markers(artifact):
        sha = _text(marker.get("result")) or _text(marker.get("commit_result"))
        cwd = _text(marker.get("cwd"))
        if sha is None or cwd is None:
            continue
        root = repository_root(Path(cwd), git_runner, root_cache)
        if root is None or not is_primary_root(root, target):
            continue
        commit = commit_record(root, sha, git_runner)
        if commit is not None:
            commits[commit.sha] = commit
    prompt = _read_text_bytes(artifact / "raw_xprompt.md")
    chat = _read_referenced_text(
        meta.get("chat_path"),
        (done or {}).get("response_path"),
    )
    state = _artifact_state(record, done)
    metadata = _portable_metadata(meta)
    family = _canonical_optional_name(meta.get("agent_family"), identity)
    clan = _canonical_optional_name(meta.get("agent_clan"), identity)
    relationships = _artifact_relationships(meta, record, identity)
    return InventoryRun(
        source_run_id,
        local_name,
        globalize_agent_name(local_name, owner),
        state,
        _time_text(meta.get("run_started_at")) or timestamp,
        _time_text((done or {}).get("finished_at")),
        None,
        metadata,
        tuple(sorted(commits.values(), key=lambda item: (item.committed_at, item.sha))),
        prompt,
        chat,
        family,
        clan,
        relationships,
        timestamp,
    )


def _dismissed_records(
    target: ProjectTarget,
) -> tuple[tuple[dict[str, Any], str], ...]:
    try:
        from sase.ace.dismissed_agents import load_dismissed_bundle_summaries

        summaries = load_dismissed_bundle_summaries(
            project_name=target.project_key,
            limit=None,
        )
    except (OSError, RuntimeError, ValueError, ImportError):
        return ()
    selected: list[tuple[dict[str, Any], str]] = []
    for summary in summaries:
        path = Path(str(summary.bundle_path))
        raw = _read_json_object(path, required=False)
        if raw is not None:
            selected.append((raw, str(path)))
    return tuple(selected)


def _run_from_dismissed(
    raw: dict[str, Any],
    source_label: str,
    project_key: str,
    identity: AgentIdentitySnapshot,
    history: dict[str, tuple[CommitRecord, ...]],
) -> InventoryRun | None:
    if _is_imported(raw, raw):
        return None
    raw_name = _text(raw.get("agent_name")) or _text(raw.get("cl_name"))
    if raw_name is None:
        return None
    local_name = _canonical_local_name(raw_name, identity)
    owner = _require_owner(identity)
    raw_suffix = _text(raw.get("raw_suffix")) or _text(raw.get("start_time"))
    if raw_suffix is None:
        raw_suffix = hashlib.sha256(source_label.encode()).hexdigest()[:24]
    source_run_id = _source_run_id(project_key, "ace-run", raw_suffix)
    metadata = _portable_metadata(raw)
    prompt = _inline_text(raw, ("raw_xprompt", "raw_prompt", "prompt"))
    chat = _read_referenced_text(raw.get("response_path"), raw.get("chat_path"))
    family = _canonical_optional_name(raw.get("agent_family"), identity)
    clan = _canonical_optional_name(raw.get("agent_clan"), identity)
    relationships = _dismissed_relationships(raw, identity)
    return InventoryRun(
        source_run_id,
        local_name,
        globalize_agent_name(local_name, owner),
        "dismissed",
        _time_text(raw.get("run_start_time") or raw.get("start_time")),
        _time_text(raw.get("stop_time")),
        _time_text(raw.get("stop_time")),
        metadata,
        history.get(local_name, ()),
        prompt,
        chat,
        family,
        clan,
        relationships,
        raw_suffix,
    )


def _historical_associations(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    git_runner: GitRunner,
) -> dict[str, tuple[CommitRecord, ...]]:
    result = git_runner(
        target.primary_checkout,
        ["log", "--format=%H%x00%ct%x00%s%x00%B%x00"],
        op="agents_sync.v2_history",
    )
    if result.returncode != 0:
        return {}
    commits: dict[str, dict[str, CommitRecord]] = defaultdict(dict)
    chunks = result.stdout.split("\x00")
    for index in range(0, len(chunks) - 3, 4):
        sha = chunks[index].lstrip("\r\n").strip().lower()
        subject = chunks[index + 2].rstrip("\r\n")
        try:
            committed_at = int(chunks[index + 1].strip())
            tags = parse_trailing_commit_tags(chunks[index + 3].rstrip("\r\n"))
        except (ValueError, TypeError, RuntimeError):
            continue
        raw_name = tags.get("AGENT")
        if not raw_name or not _footer_is_current_owner(
            raw_name, tags.get("MACHINE"), identity
        ):
            continue
        try:
            local_name = _canonical_local_name(raw_name, identity)
        except AgentsSyncFormatError:
            continue
        commits[local_name][sha] = CommitRecord(sha, subject, committed_at)
    return {
        name: tuple(
            sorted(rows.values(), key=lambda item: (item.committed_at, item.sha))
        )
        for name, rows in commits.items()
    }


def _footer_is_current_owner(
    name: str,
    footer_machine: str | None,
    identity: AgentIdentitySnapshot,
) -> bool:
    owner = _require_owner(identity)
    global_prefix = f"{owner.username}.{owner.machine_name}."
    if name.startswith(global_prefix):
        return footer_machine in {None, owner.machine_name}
    parts = name.split(".")
    if len(parts) >= 3 and footer_machine and parts[1] == footer_machine:
        return False
    if footer_machine == owner.machine_name:
        return True
    # Legacy footers stored a bare name with a host that was not the configured
    # machine identity. Accept only spellings without an explicit owner prefix.
    return not (footer_machine and name.startswith(f"{footer_machine}."))


def _artifact_relationships(
    meta: dict[str, Any],
    record: AgentArtifactRecordWire,
    identity: AgentIdentitySnapshot,
) -> tuple[_InventoryRelationship, ...]:
    rows: list[_InventoryRelationship] = []
    parent_name = _text(meta.get("parent_agent_name"))
    if parent_name:
        rows.append(
            _InventoryRelationship(
                "parent", _canonical_local_name(parent_name, identity), "name"
            )
        )
    parent_timestamp = _text(meta.get("parent_agent_timestamp"))
    if parent_timestamp:
        rows.append(_InventoryRelationship("parent", parent_timestamp, "timestamp"))
    workflow_parent = _text(meta.get("parent_timestamp"))
    if workflow_parent:
        rows.append(
            _InventoryRelationship("workflow_parent", workflow_parent, "timestamp")
        )
    retry = _text(meta.get("retry_of_timestamp"))
    if retry:
        rows.append(_InventoryRelationship("retry", retry, "timestamp"))
    waiting = (
        record.waiting.waiting_for
        if record.waiting is not None
        else meta.get("wait_for") or ()
    )
    if isinstance(waiting, list):
        for name in waiting:
            if isinstance(name, str) and name:
                rows.append(
                    _InventoryRelationship(
                        "wait", _canonical_local_name(name, identity), "name"
                    )
                )
    return _dedupe_relationships(rows)


def _dismissed_relationships(
    raw: dict[str, Any], identity: AgentIdentitySnapshot
) -> tuple[_InventoryRelationship, ...]:
    rows: list[_InventoryRelationship] = []
    for kind, key in (
        ("workflow_parent", "parent_timestamp"),
        ("retry", "retry_of_timestamp"),
    ):
        target = _text(raw.get(key))
        if target:
            rows.append(_InventoryRelationship(kind, target, "timestamp"))
    waiting = raw.get("waiting_for") or ()
    if isinstance(waiting, list):
        for name in waiting:
            if isinstance(name, str) and name:
                rows.append(
                    _InventoryRelationship(
                        "wait", _canonical_local_name(name, identity), "name"
                    )
                )
    return _dedupe_relationships(rows)


def _artifact_state(
    record: AgentArtifactRecordWire, done: dict[str, Any] | None
) -> str:
    if record.waiting is not None or record.pending_question is not None:
        return "waiting"
    if done is None:
        return "active"
    outcome = _text(done.get("outcome")) or "failed"
    if outcome == "completed":
        return "stopped" if done.get("repeat_stopped") is True else "completed"
    return "failed"


def _portable_metadata(raw: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    metadata = {
        key: raw[key]
        for key in V2_METADATA_FIELDS
        if key in raw and raw[key] is not None
    }
    try:
        json.dumps(metadata, allow_nan=False)
    except (TypeError, ValueError):
        metadata = {
            key: value
            for key, value in metadata.items()
            if isinstance(value, (str, int, float, bool, list, dict))
        }
    return tuple(sorted(metadata.items()))


def _read_json_object(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise AgentsSyncFormatError(f"{path.name} exceeds the byte limit")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise AgentsSyncFormatError(f"missing {path.name}") from None
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise AgentsSyncFormatError(f"{path.name} must be a JSON object")
    return value


def _read_text_bytes(path: Path) -> bytes | None:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_TEXT_BYTES:
            raise AgentsSyncFormatError(f"{path.name} exceeds the byte limit")
        payload = path.read_bytes()
        payload.decode("utf-8")
        return payload
    except AgentsSyncFormatError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read {path.name}: {exc}") from exc


def _read_referenced_text(*values: object) -> bytes | None:
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        payload = _read_text_bytes(Path(value).expanduser())
        if payload is not None:
            return payload
    return None


def _inline_text(raw: dict[str, Any], keys: tuple[str, ...]) -> bytes | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value:
            payload = value.encode("utf-8")
            if len(payload) > MAX_TEXT_BYTES:
                raise AgentsSyncFormatError(f"{key} exceeds the byte limit")
            return payload
    return None


def _canonical_local_name(name: str, identity: AgentIdentitySnapshot) -> str:
    normalized = normalize_owned_agent_name(name, identity)
    normalized = normalize_agent_archive_name(normalized)
    if (
        not normalized
        or "/" in normalized
        or "\\" in normalized
        or "\x00" in normalized
    ):
        raise AgentsSyncFormatError(f"unsafe local agent name: {name!r}")
    return normalized


def _canonical_optional_name(
    value: object, identity: AgentIdentitySnapshot
) -> str | None:
    name = _text(value)
    return _canonical_local_name(name, identity) if name else None


def _source_run_id(project: str, workflow: str, durable: str) -> str:
    digest = hashlib.sha256(
        "\x00".join((project, workflow, durable)).encode("utf-8")
    ).hexdigest()
    return f"run-{digest[:32]}"


def _time_text(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _is_imported(meta: dict[str, Any], done: dict[str, Any] | None) -> bool:
    values = (meta, done or {})
    return any(
        any(
            row.get(key) is not None
            for key in (
                "imported_from_machine",
                "imported_digest",
                "imported_source_owner",
                "source_owner",
            )
        )
        for row in values
    )


def _dedupe_relationships(
    rows: list[_InventoryRelationship],
) -> tuple[_InventoryRelationship, ...]:
    return tuple(
        sorted(
            set(rows),
            key=lambda item: (item.kind, item.target_kind, item.target),
        )
    )


def _run_preference(run: InventoryRun) -> tuple[int, int, str]:
    return (
        run.state != "dismissed",
        sum(
            (
                bool(run.commits),
                run.prompt_bytes is not None,
                run.chat_bytes is not None,
                run.finished_at is not None,
            )
        ),
        run.timestamp,
    )


def _require_owner(identity: AgentIdentitySnapshot) -> AgentOwnerIdentity:
    if identity.owner is None:
        raise AgentsSyncFormatError("owner identity is not configured")
    return identity.owner


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "InventoryRun",
    "ProjectHoodInventory",
    "build_project_hood_inventory",
]
