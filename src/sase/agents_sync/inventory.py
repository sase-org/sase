"""Indexed, project-scoped inventory for owner-sharded v2 publication."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import hashlib
from pathlib import Path
from typing import Any

from sase.agents_sync.bundles import (
    commit_markers,
    commit_record,
    is_primary_root,
    repository_root,
)
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.inventory_io import (
    canonical_local_name as _canonical_local_name,
    canonical_optional_name as _canonical_optional_name,
    dedupe_relationships as _dedupe_relationships,
    embedded_workflows_payload as _embedded_workflows_payload,
    inline_text as _inline_text,
    is_imported as _is_imported,
    portable_metadata as _portable_metadata,
    prompt_steps_payload as _prompt_steps_payload,
    read_json_object as _read_json_object,
    read_referenced_text as _read_referenced_text,
    read_text_bytes as _read_text_bytes,
    require_owner as _require_owner,
    source_run_id as _source_run_id,
    text as _text,
    time_text as _time_text,
)
from sase.agents_sync.inventory_models import (
    InventoryRelationship,
    InventoryRun,
    ProjectHoodInventory,
)
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    globalize_agent_name,
    parse_agent_family_name,
)
from sase.core.dismissed_agents_facade import load_dismissed_bundle_summaries
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

# Preserve the existing test/support import while keeping the shared model public
# in its defining module.
_InventoryRelationship = InventoryRelationship


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
    primary_remote_url = _primary_remote_url(target, git_runner)
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
            embedded_workflows_bytes=(
                preferred.embedded_workflows_bytes or existing.embedded_workflows_bytes
            ),
            prompt_steps_bytes=(
                preferred.prompt_steps_bytes or existing.prompt_steps_bytes
            ),
        )
    _add_commit_only_runs(
        by_global,
        history,
        target.project_key,
        owner,
        diagnostics,
    )
    normalized_runs = tuple(
        _normalize_historical_family_metadata(run, diagnostics)
        for run in by_global.values()
    )
    unique_runs = _disambiguate_source_run_ids(
        normalized_runs,
        target.project_key,
        diagnostics,
    )
    return ProjectHoodInventory(
        owner,
        target.project_key,
        tuple(sorted(unique_runs, key=lambda item: item.source_run_id)),
        tuple(diagnostics),
        primary_remote_url,
        target.primary_repo_name,
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
    embedded_workflows = _embedded_workflows_payload(
        artifact / "embedded_workflows.json"
    )
    prompt_steps = _prompt_steps_payload(artifact)
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
        embedded_workflows,
        prompt_steps,
        source_label=str(artifact),
    )


def _dismissed_records(
    target: ProjectTarget,
) -> tuple[tuple[dict[str, Any], str], ...]:
    try:
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
    step_output = raw.get("step_output")
    if (
        isinstance(step_output, dict)
        and step_output.get("imported_source_run_id") is not None
    ):
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
        source_label=source_label,
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


def _primary_remote_url(
    target: ProjectTarget,
    git_runner: GitRunner,
) -> str | None:
    """Read the primary checkout's origin without making publication fragile."""

    try:
        result = git_runner(
            target.primary_checkout,
            ["config", "--get", "remote.origin.url"],
            op="agents_sync.v2_primary_remote",
        )
    except Exception:  # noqa: BLE001 - optional local Git metadata boundary.
        return None
    remote_url = result.stdout.strip()
    return remote_url if result.returncode == 0 and remote_url else None


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
) -> tuple[InventoryRelationship, ...]:
    rows: list[InventoryRelationship] = []
    parent_name = _text(meta.get("parent_agent_name"))
    if parent_name:
        rows.append(
            InventoryRelationship(
                "parent", _canonical_local_name(parent_name, identity), "name"
            )
        )
    parent_timestamp = _text(meta.get("parent_agent_timestamp"))
    if parent_timestamp:
        rows.append(InventoryRelationship("parent", parent_timestamp, "timestamp"))
    workflow_parent = _text(meta.get("parent_timestamp"))
    if workflow_parent:
        rows.append(
            InventoryRelationship("workflow_parent", workflow_parent, "timestamp")
        )
    retry = _text(meta.get("retry_of_timestamp"))
    if retry:
        rows.append(InventoryRelationship("retry", retry, "timestamp"))
    waiting = (
        record.waiting.waiting_for
        if record.waiting is not None
        else meta.get("wait_for") or ()
    )
    rows.extend(_wait_relationships(waiting, identity))
    return _dedupe_relationships(rows)


def _wait_relationships(
    waiting: object,
    identity: AgentIdentitySnapshot,
) -> list[InventoryRelationship]:
    if not isinstance(waiting, list):
        return []
    return [
        InventoryRelationship(
            "wait",
            _canonical_local_name(name, identity),
            "name",
        )
        for name in waiting
        if isinstance(name, str) and name and not name.startswith("@")
    ]


def _dismissed_relationships(
    raw: dict[str, Any], identity: AgentIdentitySnapshot
) -> tuple[InventoryRelationship, ...]:
    rows: list[InventoryRelationship] = []
    for kind, key in (
        ("workflow_parent", "parent_timestamp"),
        ("retry", "retry_of_timestamp"),
    ):
        target = _text(raw.get(key))
        if target:
            rows.append(InventoryRelationship(kind, target, "timestamp"))
    waiting = raw.get("waiting_for") or ()
    rows.extend(_wait_relationships(waiting, identity))
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


def _add_commit_only_runs(
    by_global: dict[str, InventoryRun],
    history: dict[str, tuple[CommitRecord, ...]],
    project_key: str,
    owner: AgentOwnerIdentity,
    diagnostics: list[str],
) -> None:
    """Represent linked primary commits even after their local artifact is gone."""

    for local_name, commits in sorted(history.items()):
        global_name = globalize_agent_name(local_name, owner)
        if global_name in by_global:
            continue
        source_label = f"primary commit history for {global_name}"
        started_at = _time_text(commits[0].committed_at)
        finished_at = _time_text(commits[-1].committed_at)
        by_global[global_name] = InventoryRun(
            _source_run_id(project_key, "primary-commit-history", local_name),
            local_name,
            global_name,
            "completed",
            started_at,
            finished_at,
            None,
            (),
            commits,
            None,
            None,
            None,
            None,
            (),
            str(commits[-1].committed_at),
            source_label=source_label,
        )
        diagnostics.append(
            f"{source_label}: synthesized publication record because no local "
            "artifact remains"
        )


def _normalize_historical_family_metadata(
    run: InventoryRun,
    diagnostics: list[str],
) -> InventoryRun:
    """Make stale family metadata agree with canonical name classification."""

    try:
        parsed = parse_agent_family_name(run.local_name)
    except Exception as exc:  # noqa: BLE001 - defensive history boundary.
        source = run.source_label or run.source_run_id
        diagnostics.append(
            f"{source}: could not normalize historical family metadata: {exc}"
        )
        return run
    raw_family = run.family_name
    canonical_family = (
        parsed.family_name
        if parsed.member_role is not None
        else raw_family
        if raw_family == parsed.family_name
        else None
    )
    metadata = dict(run.metadata)
    if canonical_family is None:
        metadata.pop("agent_family", None)
        metadata.pop("agent_family_role", None)
        metadata.pop("role_suffix", None)
    else:
        metadata["agent_family"] = canonical_family
        if parsed.member_role is not None:
            metadata["agent_family_role"] = parsed.member_role
            metadata["role_suffix"] = parsed.member_role
    if raw_family is not None and raw_family != canonical_family:
        source = run.source_label or run.source_run_id
        diagnostics.append(
            f"{source}: historical agent_family {raw_family!r} disagrees with "
            f"canonical name {run.local_name!r}; using "
            f"{canonical_family or 'solo classification'!r}"
        )
    return replace(
        run,
        family_name=canonical_family,
        metadata=tuple(sorted(metadata.items())),
    )


def _disambiguate_source_run_ids(
    runs: tuple[InventoryRun, ...],
    project_key: str,
    diagnostics: list[str],
) -> tuple[InventoryRun, ...]:
    """Give distinct historical runs unique stable IDs when old timestamps collide."""

    grouped: dict[str, list[InventoryRun]] = defaultdict(list)
    for run in runs:
        grouped[run.source_run_id].append(run)
    used = {
        source_run_id
        for source_run_id, candidates in grouped.items()
        if len(candidates) == 1
    }
    replacements: dict[str, str] = {}
    for source_run_id, candidates in sorted(grouped.items()):
        if len(candidates) == 1:
            continue
        labels = tuple(
            sorted(
                candidate.source_label or candidate.global_name
                for candidate in candidates
            )
        )
        diagnostics.append(
            f"historical source run ID {source_run_id!r} was shared by "
            f"{len(candidates)} records and was deterministically disambiguated: "
            + ", ".join(labels)
        )
        for candidate in sorted(candidates, key=lambda item: item.global_name):
            salt = 0
            while True:
                replacement = _source_run_id(
                    project_key,
                    "historical-source-collision",
                    f"{source_run_id}\0{candidate.global_name}\0{salt}",
                )
                if replacement not in used:
                    break
                salt += 1
            replacements[candidate.global_name] = replacement
            used.add(replacement)
    return tuple(
        replace(run, source_run_id=replacements[run.global_name])
        if run.global_name in replacements
        else run
        for run in runs
    )


__all__ = [
    "InventoryRun",
    "ProjectHoodInventory",
    "build_project_hood_inventory",
]
