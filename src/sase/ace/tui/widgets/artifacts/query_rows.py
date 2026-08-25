"""Immutable row adapters for profile-driven Artifacts query corpora."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
import time
from typing import Any

from sase.ace.query_profile import CompiledQueryProfile
from sase.agents.catalog import AgentCatalogRow
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    compile_artifact_query_index,
)
from sase.core.vcs_log_facade import classify_commit_types
from sase.project_display_names import ProjectRefDisplaySnapshot
from sase.vcs_log.models import VcsLogResult

from .agents_data import AgentsSnapshot
from .beads_data import BeadsSnapshot
from .beads_filtering import BeadFilterIndex, build_bead_filter_index
from .files_data import FilesSnapshot, LogicalFile
from .plans_data import PlansSnapshot
from .plans_filtering import (
    PlanFilterIndex,
    build_plan_filter_index,
)


def build_beads_query_index(
    snapshot: BeadsSnapshot,
    *,
    pane_id: str,
    generation: int,
    profile: CompiledQueryProfile,
) -> tuple[BeadFilterIndex, ArtifactQueryIndex]:
    """Build the Beads compatibility index and Rust query index together."""

    filter_index = build_bead_filter_index(snapshot)
    return (
        filter_index,
        compile_artifact_query_index(
            pane_id=pane_id,
            generation=generation,
            profile=profile,
            entries=(_bead_query_entry(record) for record in filter_index),
        ),
    )


def build_plans_query_index(
    snapshot: PlansSnapshot,
    *,
    pane_id: str,
    generation: int,
    profile: CompiledQueryProfile,
) -> tuple[PlanFilterIndex, ArtifactQueryIndex]:
    """Build the Plans/provider compatibility and Rust query indexes."""

    filter_index = build_plan_filter_index(snapshot)
    return (
        filter_index,
        compile_artifact_query_index(
            pane_id=pane_id,
            generation=generation,
            profile=profile,
            entries=(_plan_query_entry(snapshot, record) for record in filter_index),
        ),
    )


def build_files_query_index(
    snapshot: FilesSnapshot,
    *,
    pane_id: str,
    generation: int,
    profile: CompiledQueryProfile,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> ArtifactQueryIndex:
    """Build a Rust query index for the loaded logical file snapshot."""

    return compile_artifact_query_index(
        pane_id=pane_id,
        generation=generation,
        profile=profile,
        entries=(
            _file_query_entry(row, project_ref_display=project_ref_display)
            for row in snapshot.rows
        ),
    )


def build_agents_query_index(
    snapshot: AgentsSnapshot,
    *,
    pane_id: str,
    generation: int,
    profile: CompiledQueryProfile,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> ArtifactQueryIndex:
    """Build a Rust query index for the full Agent catalog snapshot."""

    return compile_artifact_query_index(
        pane_id=pane_id,
        generation=generation,
        profile=profile,
        entries=(
            _agent_query_entry(row, project_ref_display=project_ref_display)
            for row in snapshot.rows
        ),
    )


def build_commits_query_index(
    result: VcsLogResult,
    *,
    pane_id: str,
    generation: int,
    profile: CompiledQueryProfile,
) -> ArtifactQueryIndex:
    """Build a Rust query index for one collected commit result."""

    repo_kind_by_name = {repo.name: repo.kind for repo in result.repos}
    repo_labels_by_name = {
        repo.name: tuple(dict.fromkeys((repo.name, *repo.aliases)))
        for repo in result.repos
    }
    index = compile_artifact_query_index(
        pane_id=pane_id,
        generation=generation,
        profile=profile,
        entries=(
            _commit_query_entry(
                entry,
                repo_labels=repo_labels_by_name.get(entry.repo, (entry.repo,)),
                repo_kind=repo_kind_by_name.get(entry.repo, "primary"),
            )
            for entry in result.commits
        ),
    )
    facets = dict(index.facets)
    facets["author"] = tuple(
        sorted(
            {
                entry.commit.author_name
                for entry in result.commits
                if entry.commit.author_name
            }
        )
    )
    return replace(index, facets=facets)


def _bead_query_entry(record: Any) -> dict[str, Any]:
    fields: dict[str, object] = {
        "type": tuple(record.type_labels),
        "task_type": tuple(record.task_type_labels),
        "tier": tuple(record.tier_labels),
        "status": tuple(record.status_labels),
        "size": tuple(record.size_labels),
        "due": tuple(record.due_labels),
        "project": tuple(
            value for value in (record.project, record.project_display_name) if value
        ),
        "assignee": record.assignee,
        "owner": record.owner,
        "model": record.model,
        "has": tuple(record.has_labels),
        "bug": tuple(record.bug_labels),
        "label": tuple(record.issue_labels),
        "id": record.bead_id,
        "body": tuple(record.haystack),
    }
    if record.timestamp is not None:
        fields["since"] = (record.timestamp,)
        fields["until"] = (record.timestamp,)
    predicates: set[str] = set()
    if record.assignee.strip() and not record.status_labels.isdisjoint(
        {"claimed", "in_progress"}
    ):
        predicates.add("running_agent")
    return {
        "stable_id": record.option_id,
        "fields": fields,
        "searchable_text": "\n".join(record.haystack),
        "predicates": tuple(sorted(predicates)),
    }


def _plan_query_entry(
    snapshot: PlansSnapshot,
    record: Any,
) -> dict[str, Any]:
    fields: dict[str, object] = {
        "kind": tuple(record.kind_labels or frozenset((record.kind,))),
        "status": tuple(record.status_labels),
        "tier": tuple(record.tier_labels),
        "project": tuple(
            value for value in (record.project, record.project_display_name) if value
        ),
        "title": tuple(record.haystack),
        "body": tuple(record.haystack),
        "path": record.identity,
    }
    if record.timestamp is not None:
        fields["since"] = (record.timestamp,)
        fields["until"] = (record.timestamp,)
    return {
        "stable_id": record.option_id,
        "fields": fields,
        "properties": _plan_provider_properties(snapshot, record),
        "searchable_text": "\n".join(record.haystack),
        "predicates": (),
    }


def _agent_query_entry(
    row: AgentCatalogRow,
    *,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> dict[str, Any]:
    started_at = _epoch_seconds(row.started_at)
    finished_at = _epoch_seconds(row.finished_at)
    runtime_seconds = _runtime_seconds(
        started_at=started_at,
        finished_at=finished_at,
        status=row.status,
        state=row.state,
    )
    family = row.family or (row.name if "family" in row.kind else None)
    project_labels = _project_labels(row.project, project_ref_display)
    provider = _normalized_lower(row.llm_provider)
    fields: dict[str, object] = {
        "name": _dedupe_text((row.name, row.canonical_global_name)),
        "kind": row.kind,
        "family": family,
        "clan": row.clan,
        "tribe": row.tribe,
        "role": row.role,
        "workflow": row.workflow,
        "parent": row.parent_timestamp,
        "project": project_labels,
        "state": _normalized_lower(row.state),
        "status": row.status.upper() if row.status else None,
        "hidden": row.hidden,
        "dismissed": row.dismissed,
        "revivable": row.revivable,
        "attention": row.attention,
        "retry": row.retry,
        "attempt": row.retry_attempt,
        "model": row.model,
        "provider": provider,
    }
    if started_at is not None:
        fields["since"] = started_at
        fields["until"] = started_at
    if finished_at is not None:
        fields["after"] = finished_at
        fields["before"] = finished_at
    if runtime_seconds is not None:
        fields["min"] = runtime_seconds
        fields["max"] = runtime_seconds

    metadata = _dedupe_text(
        (
            row.name,
            row.canonical_global_name,
            *row.kind,
            family,
            row.clan,
            row.tribe,
            row.role,
            row.workflow,
            row.parent_timestamp,
            *project_labels,
            row.state,
            row.status,
            row.model,
            provider,
            row.patch,
            "dismissed" if row.dismissed else None,
            "revivable" if row.revivable else None,
            "attention" if row.attention else None,
            "retry" if row.retry else None,
            "hidden" if row.hidden else None,
            "collision" if row.has_collision_history else None,
            "artifact-index" if row.from_artifact_index else None,
            "dismissed-archive" if row.from_dismissed_archive else None,
        )
    )
    fields["label"] = metadata
    fields["text"] = metadata
    return {
        "stable_id": agent_query_row_id(row),
        "fields": fields,
        "searchable_text": "\n".join(metadata),
        "predicates": (),
    }


def agent_query_row_id(row: AgentCatalogRow) -> str:
    """Return the stable query row id for one Agent catalog row."""

    return f"agent:{row.name}"


def _plan_provider_properties(
    snapshot: PlansSnapshot,
    record: Any,
) -> Mapping[str, str]:
    if record.kind == "proposal":
        for proposal in snapshot.proposals:
            if proposal.notification.id == record.identity:
                return proposal.frontmatter
        return {}
    if record.kind == "active":
        for active in snapshot.active:
            if active.document.path == record.identity:
                return active.document.frontmatter
        return {}
    for archive in snapshot.archive:
        if archive.match.plan.path == record.identity:
            return archive.match.plan.frontmatter
    return {}


def _file_query_entry(
    row: LogicalFile,
    *,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> dict[str, Any]:
    project_labels: list[str] = []
    for project in row.projects:
        project_labels.append(project)
        label = project_ref_display.label_for_ref(project)
        if label:
            project_labels.append(label)
    fields: dict[str, object] = {
        "kind": row.kind,
        "origin": tuple(row.origins),
        "project": tuple(dict.fromkeys(project_labels)),
        "agent": row.agents,
        "workflow": tuple(
            version.workflow for version in row.versions if version.workflow
        ),
        "label": tuple(
            value
            for value in (row.label, *(version.label for version in row.versions))
            if value
        ),
        "stored_path": tuple(
            value for version in row.versions for value in (version.path,) if value
        ),
        "source_path": tuple(
            value
            for version in row.versions
            for value in (
                version.source_path,
                version.vcs_relpath,
                version.object_relpath,
                version.authored_path,
            )
            if value
        ),
    }
    if row.latest.created_at:
        fields["since"] = (row.latest.created_at,)
        fields["until"] = (row.latest.created_at,)
    searchable = tuple(
        value
        for version in row.versions
        for value in (
            row.label,
            row.logical_id,
            version.label,
            version.path,
            version.source_path,
            version.vcs_relpath,
            version.object_relpath,
            version.sha256,
            version.artifact_id,
        )
        if value
    )
    return {
        "stable_id": f"file:{row.logical_id}",
        "fields": fields,
        "searchable_text": "\n".join(searchable),
        "predicates": (),
    }


def _commit_query_entry(
    entry: Any,
    *,
    repo_labels: tuple[str, ...],
    repo_kind: str,
) -> dict[str, Any]:
    commit = entry.commit
    return {
        "stable_id": commit_query_row_id(entry),
        "fields": {
            "repo": repo_labels,
            "author": (commit.author_name, commit.author_email),
            "origin": commit.origin,
            "type": classify_commit_types(commit),
            "since": (commit.timestamp,),
            "until": (commit.timestamp,),
            "sidecar": repo_kind == "sidecar",
            "merges": "only" if commit.is_merge else "hide",
            "subject": commit.subject,
        },
        "searchable_text": commit.subject,
        "predicates": (),
    }


def commit_query_row_id(entry: Any) -> str:
    """Return the stable query row id for one aggregated commit."""

    return f"commit:{entry.repo}:{entry.commit.full_id}"


def _project_labels(
    project: str | None,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> tuple[str, ...]:
    if not project:
        return ()
    return _dedupe_text((project, project_ref_display.label_for_ref(project)))


def _dedupe_text(values: Sequence[object | None]) -> tuple[str, ...]:
    items: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            items.append(text)
    return tuple(dict.fromkeys(items))


def _normalized_lower(value: str | None) -> str | None:
    return value.casefold() if value else None


def _epoch_seconds(value: object | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _runtime_seconds(
    *,
    started_at: int | None,
    finished_at: int | None,
    status: str | None,
    state: str | None,
) -> int | None:
    if started_at is None:
        return None
    if finished_at is not None:
        return max(0, finished_at - started_at)
    if (state or "").casefold() == "active" or (status or "").upper() in {
        "STARTING",
        "RUNNING",
        "WAITING",
    }:
        return max(0, int(time.time()) - started_at)
    return None


__all__ = [
    "agent_query_row_id",
    "build_agents_query_index",
    "build_beads_query_index",
    "build_commits_query_index",
    "build_files_query_index",
    "build_plans_query_index",
    "commit_query_row_id",
]
