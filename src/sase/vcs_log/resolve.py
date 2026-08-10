"""Resolve repository sets for ``sase stitch log``.

The default path keeps the current-project/fallback behavior used by the
existing command.  The explicit all-project path starts from the Rust-backed
project inventory, expands each usable project without materializing anything,
and canonicalizes the resulting catalog before collection.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.plan_documents import PlanWorkspace
from sase.project_display_names import project_display_name_for
from sase.vcs_log._resolve_catalog import (
    _KIND_ORDER,
    RepoCandidate,
    apply_filters,
    collapse_global_warnings,
    deduplicate_and_name,
    resolve_exclusions,
    warn_once,
)
from sase.vcs_log.models import LogRepo, LogRepoKind


@dataclass(frozen=True)
class ResolvedRepos:
    """Repos to log plus any non-fatal resolution warnings."""

    repos: list[LogRepo]
    warnings: list[str]


def resolve_log_repos(
    *,
    cwd: str,
    repo_filters: Sequence[str] = (),
    exclude_repo_filters: Sequence[str] = (),
    all_projects: bool = False,
    project_scope: str | None = None,
    current_only: bool = False,
    include_sidecars: bool = False,
) -> ResolvedRepos:
    """Resolve repositories for the requested timeline scope.

    Without ``all_projects``, a non-project *cwd* falls back to the current VCS
    repository exactly as before.  Global scope is independent of *cwd* and
    reads every registered enabled or disabled project record except ``home``.
    """
    warnings: list[str] = []

    if all_projects:
        repos = _resolve_all_project_repos(warnings, include_sidecars=include_sidecars)
    elif project_scope is not None:
        repos = _resolve_explicit_project_repos(
            project_scope,
            warnings,
            current_only=current_only,
            include_sidecars=include_sidecars,
        )
    else:
        repos = _resolve_current_scope_repos(
            cwd=cwd,
            current_only=current_only,
            include_sidecars=include_sidecars,
            warnings=warnings,
        )
        repos.sort(key=lambda repo: (_KIND_ORDER.get(repo.kind, 9), repo.name))

    excluded = resolve_exclusions(repos, exclude_repo_filters, warnings)
    if repo_filters:
        repos = apply_filters(repos, list(repo_filters), warnings)
    if excluded:
        repos = [repo for repo in repos if repo not in excluded]

    return ResolvedRepos(repos=repos, warnings=warnings)


def _resolve_explicit_project_repos(
    project_scope: str,
    warnings: list[str],
    *,
    current_only: bool,
    include_sidecars: bool,
) -> list[LogRepo]:
    """Resolve one registered project's constellation without changing cwd."""
    try:
        records = list_project_records(
            sase_projects_dir(), ("enabled", "disabled"), include_home=False
        )
    except Exception as exc:  # pragma: no cover - facade failures are rare
        warnings.append(
            f"project {project_scope}: inventory could not be loaded: {exc}"
        )
        return []

    folded = project_scope.casefold()
    matches = [
        record
        for record in records
        if not record.system_managed
        and (
            record.project_name.casefold() == folded
            or effective_project_name(record).casefold() == folded
            or any(alias.casefold() == folded for alias in record.aliases)
        )
    ]
    if not matches:
        warnings.append(f"project '{project_scope}' was not found")
        return []

    matches.sort(
        key=lambda record: (
            record.project_name.casefold() != folded,
            effective_project_name(record).casefold() != folded,
            _record_sort_key(record),
        )
    )
    candidates = _resolve_record_candidates(
        matches[0], warnings, include_sidecars=include_sidecars
    )
    repos = deduplicate_and_name(candidates)
    if current_only:
        repos = [repo for repo in repos if repo.kind == "primary"]
    return repos


def _resolve_current_scope_repos(
    *, cwd: str, current_only: bool, include_sidecars: bool, warnings: list[str]
) -> list[LogRepo]:
    from sase.main.utils import ensure_project_file_and_get_workspace_num

    project_file, workspace_num, project_name = (
        ensure_project_file_and_get_workspace_num(create_missing=False)
    )
    if project_file and project_name:
        return _resolve_project_repos(
            project_file=project_file,
            project_name=project_name,
            workspace_num=workspace_num if workspace_num is not None else 0,
            cwd=cwd,
            current_only=current_only,
            include_sidecars=include_sidecars,
            warnings=warnings,
        )
    return _resolve_fallback_repos(cwd, warnings)


def _resolve_all_project_repos(
    warnings: list[str], *, include_sidecars: bool
) -> list[LogRepo]:
    try:
        records = list_project_records(
            sase_projects_dir(), ("enabled", "disabled"), include_home=False
        )
    except Exception as exc:  # pragma: no cover - facade failures are rare
        warn_once(
            warnings,
            f"all projects: project inventory could not be loaded: {exc}",
        )
        return []

    candidates: list[RepoCandidate] = []
    for record in sorted(records, key=_record_sort_key):
        if record.project_name == "home" or record.system_managed:
            continue
        candidates.extend(
            _resolve_record_candidates(
                record, warnings, include_sidecars=include_sidecars
            )
        )

    repos = deduplicate_and_name(candidates)
    warnings[:] = collapse_global_warnings(warnings, repos)
    return repos


def _record_sort_key(record: ProjectRecordWire) -> tuple[str, str]:
    return (effective_project_name(record).casefold(), record.project_name)


def _resolve_record_candidates(
    record: ProjectRecordWire, warnings: list[str], *, include_sidecars: bool
) -> list[RepoCandidate]:
    project_label = effective_project_name(record)
    project_ref = _project_ref(record, project_label)

    record_warnings = [*record.warnings, *record.parse_warnings]
    for warning in record_warnings:
        warn_once(warnings, f"{project_ref}: {warning}")

    project_file = Path(record.project_file).expanduser()
    if not project_file.is_file():
        if not _contains_warning(record_warnings, "projectspec file not found"):
            warn_once(
                warnings,
                f"{project_ref}: project file is unavailable: {project_file}",
            )
        return []

    if not record.workspace_dir:
        if not _contains_warning(record_warnings, "workspace_dir"):
            warn_once(warnings, f"{project_ref}: no primary workspace is recorded")
        return []
    primary_dir = os.path.expanduser(record.workspace_dir)
    if not Path(primary_dir).is_dir():
        warn_once(
            warnings,
            f"{project_ref}: primary workspace is unavailable: {primary_dir}",
        )
        return []

    primary_aliases = {
        project_label,
        record.project_name,
        *(alias for alias in record.aliases if alias),
    }
    plan_workspace = _plan_workspace(record.project_name, primary_dir, 1)
    candidates = [
        RepoCandidate(
            name=project_label,
            path=primary_dir,
            kind="primary",
            project_name=record.project_name,
            project_label=project_label,
            aliases=frozenset(primary_aliases),
            plan_workspaces=(plan_workspace,),
        )
    ]

    project_warnings: list[str] = []
    linked = _resolve_linked_repos(
        str(project_file),
        primary_dir,
        project_warnings,
        include_sidecars=include_sidecars,
        plan_workspaces=(plan_workspace,),
    )
    legacy_sidecar = (
        _resolve_legacy_sdd_repo(
            primary_dir,
            project_warnings,
            plan_workspaces=(plan_workspace,),
        )
        if include_sidecars
        else None
    )
    for warning in project_warnings:
        warn_once(warnings, f"{project_ref}: {warning}")

    for repo in linked:
        candidates.append(
            RepoCandidate(
                name=repo.name,
                path=repo.path,
                kind=repo.kind,
                project_name=record.project_name,
                project_label=project_label,
                aliases=frozenset((repo.name, *repo.aliases)),
                plan_workspaces=repo.plan_workspaces,
            )
        )
    if legacy_sidecar is not None:
        candidates.append(
            RepoCandidate(
                name=legacy_sidecar.name,
                path=legacy_sidecar.path,
                kind="sidecar",
                project_name=record.project_name,
                project_label=project_label,
                aliases=frozenset(
                    (legacy_sidecar.name, "sdd", *legacy_sidecar.aliases)
                ),
                plan_workspaces=legacy_sidecar.plan_workspaces,
            )
        )
    return candidates


def _project_ref(record: ProjectRecordWire, project_label: str) -> str:
    if project_label == record.project_name:
        return project_label
    return f"{project_label} ({record.project_name})"


def _contains_warning(warnings: Sequence[str], fragment: str) -> bool:
    fragment = fragment.casefold()
    return any(fragment in warning.casefold() for warning in warnings)


def _resolve_project_repos(
    *,
    project_file: str,
    project_name: str,
    workspace_num: int,
    cwd: str,
    current_only: bool,
    include_sidecars: bool,
    warnings: list[str],
) -> list[LogRepo]:
    primary_dir = _primary_workspace_dir(project_file, cwd, workspace_num)
    display_name = project_display_name_for(project_name)
    plan_workspaces = (_plan_workspace(project_name, primary_dir, workspace_num),)
    repos: list[LogRepo] = [
        LogRepo(
            name=display_name,
            path=primary_dir,
            kind="primary",
            aliases=(project_name,) if project_name != display_name else (),
            plan_workspaces=plan_workspaces,
        )
    ]

    if current_only:
        return repos

    repos.extend(
        _resolve_linked_repos(
            project_file,
            primary_dir,
            warnings,
            include_sidecars=include_sidecars,
            plan_workspaces=plan_workspaces,
        )
    )
    if include_sidecars:
        legacy_sidecar = _resolve_legacy_sdd_repo(
            primary_dir,
            warnings,
            plan_workspaces=plan_workspaces,
        )
        if legacy_sidecar is not None:
            repos.append(legacy_sidecar)
    return repos


def _primary_workspace_dir(project_file: str, cwd: str, workspace_num: int) -> str:
    """Return the primary checkout dir (WORKSPACE_DIR is the source of truth)."""
    from sase.workspace_provider.utils import parse_workspace_dir

    primary = parse_workspace_dir(project_file)
    if primary:
        return os.path.expanduser(primary)
    # No WORKSPACE_DIR recorded: derive from the current checkout.
    from sase.sdd import get_primary_workspace_dir

    return get_primary_workspace_dir(cwd, workspace_num)


def _resolve_linked_repos(
    project_file: str,
    primary_dir: str,
    warnings: list[str],
    *,
    include_sidecars: bool,
    plan_workspaces: tuple[PlanWorkspace, ...],
) -> list[LogRepo]:
    from sase.linked_repos import resolve_linked_repos_for_project

    try:
        resolution = resolve_linked_repos_for_project(
            project_file=project_file,
            workspace_dir=primary_dir,
            workspace_num=0,
            materialize=False,
        )
    except Exception as exc:  # pragma: no cover - defensive
        warnings.append(f"linked repos could not be resolved: {exc}")
        return []

    for warning in resolution.warnings:
        warnings.append(f"linked repos: {warning}")

    repos: list[LogRepo] = []
    for repo in resolution.repos:
        kind: LogRepoKind = "sidecar" if repo.kind == "sidecar" else "linked"
        if kind == "sidecar" and not include_sidecars:
            continue
        # Prefer the linked repo's primary checkout; it is the stable,
        # always-materialized copy (numbered workspaces are ephemeral).
        path = repo.primary_dir or repo.workspace_dir
        if path:
            repos.append(
                LogRepo(
                    name=repo.name,
                    path=path,
                    kind=kind,
                    plan_workspaces=plan_workspaces,
                )
            )
    return repos


def _resolve_legacy_sdd_repo(
    primary_dir: str,
    warnings: list[str],
    *,
    plan_workspaces: tuple[PlanWorkspace, ...],
) -> LogRepo | None:
    from sase.sdd import materialized_sdd_clone

    try:
        clone = materialized_sdd_clone(primary_dir)
    except Exception as exc:  # pragma: no cover - defensive
        warnings.append(f"sdd store could not be resolved: {exc}")
        return None

    if clone is None:
        return None

    return LogRepo(
        name=_sdd_label(primary_dir),
        path=str(clone),
        kind="sidecar",
        aliases=("sdd",),
        plan_workspaces=plan_workspaces,
    )


def _sdd_label(primary_dir: str) -> str:
    from sase.sdd import read_sdd_store_record

    try:
        record = read_sdd_store_record(Path(primary_dir))
    except Exception:  # pragma: no cover - defensive
        record = None
    if record is not None and record.repo:
        return record.repo
    return "sdd"


def _resolve_fallback_repos(cwd: str, warnings: list[str]) -> list[LogRepo]:
    """Not in a project: log just the current repo, if it is a VCS repo."""
    from sase.vcs_provider import get_vcs_provider

    try:
        get_vcs_provider(cwd)
    except Exception:
        warnings.append(f"{cwd} is not a recognized SASE workspace or VCS repository")
        return []

    name = os.path.basename(os.path.abspath(cwd.rstrip("/"))) or "current"
    return [
        LogRepo(
            name=name,
            path=cwd,
            kind="primary",
            plan_workspaces=(_plan_workspace(None, cwd, 1),),
        )
    ]


def _plan_workspace(
    project_name: str | None,
    workspace_dir: str,
    workspace_num: int,
) -> PlanWorkspace:
    plans_root: str | None = None
    try:
        from sase.sdd.store import resolve_sdd_kind_dir

        plans_root = str(resolve_sdd_kind_dir(workspace_dir, workspace_num, "plans"))
    except Exception:
        pass
    return PlanWorkspace(
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        plans_root=plans_root,
        project=project_name,
    )


__all__ = ["ResolvedRepos", "resolve_log_repos"]
