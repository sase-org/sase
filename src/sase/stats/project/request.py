"""Assemble existing project, inventory, and configuration APIs into a Rust request."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from sase.core.agent_identity_facade import globalize_owned_agent_name
from sase.core.agent_scan_facade import default_agent_artifact_index_path
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.core.repository_resolution_facade import canonical_repository_identity
from sase.core.time import get_timezone
from sase.llm_provider.config import get_model_aliases
from sase.project_display_names import ProjectRefDisplaySnapshot
from sase.repo_inventory import (
    RepoRecord,
    collect_repo_inventory,
    repo_inventory_session,
)
from sase.sdd.store import resolve_sdd_store
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM

from .query import (
    ALL_FACETS,
    ProjectStatsFacet,
    ProjectStatsQuery,
    ProjectStatsUsageError,
)


@dataclass(frozen=True, slots=True)
class _ProjectStatsRequest:
    """Wire inputs and presentation-only discovery diagnostics from one fresh read."""

    data: dict[str, Any]
    refs: ProjectRefDisplaySnapshot
    issues: tuple[dict[str, Any], ...]


def build_project_stats_request(
    query: ProjectStatsQuery,
    *,
    facets: Collection[ProjectStatsFacet] = ALL_FACETS,
    now_ts: int,
) -> _ProjectStatsRequest:
    """Resolve selectors without cwd inference and leave all counting to core."""
    if not facets or set(facets) - ALL_FACETS:
        raise ProjectStatsUsageError("Request at least one of output, code, runs")
    if query.group_by not in {None, "project", "repo", "language", "model", "patch"}:
        raise ProjectStatsUsageError(f"Unknown project grouping: {query.group_by}")
    records = list_project_records(
        sase_projects_dir(), ("enabled", "disabled"), projects_only=True
    )
    refs = ProjectRefDisplaySnapshot.from_records(records)
    selected = _select_projects(query.project_refs, records, refs)
    with repo_inventory_session():
        inventory = collect_repo_inventory(include_disabled=True)
    issues: list[dict[str, Any]] = [
        {
            "project": issue.project,
            "code": "inventory_unavailable",
            "message": issue.message,
        }
        for issue in inventory.issues
    ]
    projects = []
    for record in selected:
        repos = tuple(
            r for r in inventory.records if r.project_key == record.project_name
        )
        projects.append(_project_spec(record, repos, query, refs, issues))
    sidecars = [
        {"project_key": repo.project_key, "path": _clone_path(repo)}
        for repo in inventory.records
        if repo.kind == "sidecar" and repo.name == "agents"
    ]
    sentinel = "project-stats-prefix"
    global_name = globalize_owned_agent_name(sentinel)
    prefix = global_name.removesuffix(sentinel)
    return _ProjectStatsRequest(
        data={
            "schema_version": 1,
            "start_ts": query.range.start_ts,
            "end_ts": query.range.end_ts,
            "now_ts": now_ts,
            "timezone": str(get_timezone()),
            "facets": sorted(set(facets)),
            "cache_dir": str(sase_home() / "cache" / "project_stats"),
            "run_index_path": str(default_agent_artifact_index_path()),
            "agents_sidecars": sorted(
                sidecars, key=lambda row: (row["project_key"], row["path"])
            ),
            "local_agent_name_prefix": prefix,
            "known_model_aliases": get_model_aliases(),
            "record_repo_names": sorted(
                {
                    name
                    for repo in inventory.records
                    if repo.kind == "sidecar"
                    for name in (repo.name, repo.slug)
                    if name
                }
            ),
            "include_run_only_projects": not query.project_refs,
            "budget": {"timeout_ms": 30_000, "max_output_bytes": 32 * 1024 * 1024},
            "projects": projects,
        },
        refs=refs,
        issues=tuple(issues),
    )


def _select_projects(
    selectors: tuple[str, ...],
    records: Sequence[ProjectRecordWire],
    refs: ProjectRefDisplaySnapshot,
) -> list[ProjectRecordWire]:
    by_key = {record.project_name: record for record in records}
    names: dict[str, set[str]] = {}
    for record in records:
        for name in (
            record.project_name,
            refs.display_snapshot.label_for(record.project_name),
            *record.aliases,
        ):
            names.setdefault(name.casefold(), set()).add(record.project_name)
    selected: set[str] = set()
    for selector in selectors:
        ref = selector.removeprefix("+")
        key = refs.project_key_for_ref(ref)
        candidates = names.get(ref.casefold(), set())
        if len(candidates) > 1:
            raise ProjectStatsUsageError(
                f"Ambiguous project {selector!r}: {', '.join(sorted(candidates))}"
            )
        if key is None:
            suggestions = get_close_matches(
                ref.casefold(), sorted(names), n=3, cutoff=0.5
            )
            hint = f"; did you mean {', '.join(suggestions)}?" if suggestions else ""
            raise ProjectStatsUsageError(f"Unknown project {selector!r}{hint}")
        selected.add(key)
    return [by_key[key] for key in sorted(selected if selectors else by_key)]


def _clone_path(repo: RepoRecord) -> str:
    if repo.path and repo.exists:
        return repo.path
    for clone in sorted(repo.clones, key=lambda item: (item.workspace_num, item.path)):
        if clone.exists:
            return clone.path
    # Keep missing sources in the request so core reports unavailable coverage.
    return repo.path or str(
        sase_projects_dir() / repo.project_key / "unavailable-workspace"
    )


def _repo_spec(repo: RepoRecord, issues: list[dict[str, Any]]) -> dict[str, Any]:
    identity = (
        canonical_repository_identity(repo.remote_url) if repo.remote_url else None
    )
    if not repo.exists and not any(clone.exists for clone in repo.clones):
        issues.append(
            {
                "project": repo.project_key,
                "repo": repo.name,
                "code": "not_cloned",
                "message": f"Repository {repo.name!r} has no existing registered clone",
            }
        )
    return {
        "id": f"{repo.kind}:{repo.name}",
        "name": repo.name,
        "kind": repo.kind,
        "path": _clone_path(repo),
        "identity": identity["canonical"] if identity else "",
        "ref_candidates": ["refs/remotes/origin/HEAD", "HEAD"],
    }


def _project_spec(
    record: ProjectRecordWire,
    repos: Sequence[RepoRecord],
    query: ProjectStatsQuery,
    refs: ProjectRefDisplaySnapshot,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    code_repos: list[dict[str, Any]] = []
    record_repos: list[dict[str, Any]] = []
    not_counted: list[dict[str, str]] = []
    for repo in sorted(repos, key=lambda row: (row.kind, row.name)):
        if repo.kind == "external":
            not_counted.append({"name": repo.name, "reason": "external"})
        elif repo.kind == "linked" and repo.declared_by != "project":
            not_counted.append({"name": repo.name, "reason": "user_linked"})
        else:
            target = record_repos if repo.kind == "sidecar" else code_repos
            target.append(_repo_spec(repo, issues))
    return {
        "key": record.project_name,
        "label": refs.display_snapshot.label_for(record.project_name),
        "state": record.state,
        "selection": "always"
        if query.project_refs or query.include_disabled or record.state == "enabled"
        else "if_runs",
        "index_project_names": sorted(
            {
                record.project_name,
                *record.aliases,
                refs.display_snapshot.label_for(record.project_name),
            }
        ),
        "code_repos": code_repos,
        "record_repos": record_repos,
        "not_counted": not_counted,
        "plan_store": _plan_store(record, repos, issues),
    }


def _plan_store(
    record: ProjectRecordWire,
    repos: Sequence[RepoRecord],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        if not record.workspace_dir:
            raise ValueError("Project has no primary workspace")
        primary = Path(record.workspace_dir)
        store = resolve_sdd_store(primary, PRIMARY_WORKSPACE_NUM)
        root = primary if store.storage == "in_tree" else store.repo_root
        plans_dir = store.sdd_dir.relative_to(root).as_posix()
        repo_path = str(root)
        # In-tree plans and sidecars use the same deterministic clone choice.
        for repo in repos:
            if repo.kind in {"primary", "sidecar"} and Path(repo.path) == root:
                repo_path = _clone_path(repo)
                break
        return {
            "storage": store.storage,
            "repo_path": None if store.storage == "local" else repo_path,
            "plans_dir": plans_dir,
            "project_filter": record.project_name
            if store.storage == "separate_repo"
            else None,
        }
    except (OSError, RuntimeError, ValueError) as exc:
        issues.append(
            {
                "project": record.project_name,
                "code": "plan_store_unresolved",
                "message": str(exc),
            }
        )
        # An unresolved committed source stays unavailable, never a measured zero.
        return {
            "storage": "separate_repo",
            "repo_path": None,
            "plans_dir": ".",
            "project_filter": None,
        }
