"""Resolve repository sets for ``sase vcs log``.

The default path keeps the current-project/fallback behavior used by the
existing command.  The explicit all-project path starts from the Rust-backed
project inventory, expands each usable project without materializing anything,
and canonicalizes the resulting catalog before collection.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.project_display_names import project_display_name_for
from sase.vcs_log.models import LogRepo, LogRepoKind

_KIND_ORDER = {"primary": 0, "linked": 1, "sdd": 2}


@dataclass(frozen=True)
class ResolvedRepos:
    """Repos to log plus any non-fatal resolution warnings."""

    repos: list[LogRepo]
    warnings: list[str]


@dataclass(frozen=True)
class _RepoCandidate:
    """One project-qualified route to a physical repository."""

    name: str
    path: str
    kind: LogRepoKind
    project_name: str
    project_label: str
    aliases: frozenset[str] = frozenset()


@dataclass
class _CatalogRepo:
    """Canonical all-project repository before its final label is assigned."""

    base_name: str
    path: str
    kind: LogRepoKind
    project_name: str
    project_label: str
    aliases: set[str] = field(default_factory=set)
    name: str = ""


def resolve_log_repos(
    *,
    cwd: str,
    repo_filters: Sequence[str] = (),
    exclude_repo_filters: Sequence[str] = (),
    all_projects: bool = False,
    project_scope: str | None = None,
    current_only: bool = False,
    include_sdd: bool = False,
) -> ResolvedRepos:
    """Resolve repositories for the requested timeline scope.

    Without ``all_projects``, a non-project *cwd* falls back to the current VCS
    repository exactly as before.  Global scope is independent of *cwd* and
    reads every registered enabled or disabled project record except ``home``.
    """
    warnings: list[str] = []

    if all_projects:
        repos = _resolve_all_project_repos(warnings, include_sdd=include_sdd)
    elif project_scope is not None:
        repos = _resolve_explicit_project_repos(
            project_scope,
            warnings,
            current_only=current_only,
            include_sdd=include_sdd,
        )
    else:
        repos = _resolve_current_scope_repos(
            cwd=cwd,
            current_only=current_only,
            include_sdd=include_sdd,
            warnings=warnings,
        )
        repos.sort(key=lambda repo: (_KIND_ORDER.get(repo.kind, 9), repo.name))

    excluded = _resolve_exclusions(repos, exclude_repo_filters, warnings)
    if repo_filters:
        repos = _apply_filters(repos, list(repo_filters), warnings)
    if excluded:
        repos = [repo for repo in repos if repo not in excluded]

    return ResolvedRepos(repos=repos, warnings=warnings)


def _resolve_explicit_project_repos(
    project_scope: str,
    warnings: list[str],
    *,
    current_only: bool,
    include_sdd: bool,
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
        matches[0], warnings, include_sdd=include_sdd
    )
    repos = _deduplicate_and_name(candidates)
    if current_only:
        repos = [repo for repo in repos if repo.kind == "primary"]
    return repos


def _resolve_current_scope_repos(
    *, cwd: str, current_only: bool, include_sdd: bool, warnings: list[str]
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
            include_sdd=include_sdd,
            warnings=warnings,
        )
    return _resolve_fallback_repos(cwd, warnings)


def _resolve_all_project_repos(
    warnings: list[str], *, include_sdd: bool
) -> list[LogRepo]:
    try:
        records = list_project_records(
            sase_projects_dir(), ("enabled", "disabled"), include_home=False
        )
    except Exception as exc:  # pragma: no cover - facade failures are rare
        _warn_once(
            warnings,
            f"all projects: project inventory could not be loaded: {exc}",
        )
        return []

    candidates: list[_RepoCandidate] = []
    for record in sorted(records, key=_record_sort_key):
        if record.project_name == "home" or record.system_managed:
            continue
        candidates.extend(
            _resolve_record_candidates(record, warnings, include_sdd=include_sdd)
        )

    repos = _deduplicate_and_name(candidates)
    warnings[:] = _collapse_global_warnings(warnings, repos)
    return repos


def _record_sort_key(record: ProjectRecordWire) -> tuple[str, str]:
    return (effective_project_name(record).casefold(), record.project_name)


def _resolve_record_candidates(
    record: ProjectRecordWire, warnings: list[str], *, include_sdd: bool
) -> list[_RepoCandidate]:
    project_label = effective_project_name(record)
    project_ref = _project_ref(record, project_label)

    record_warnings = [*record.warnings, *record.parse_warnings]
    for warning in record_warnings:
        _warn_once(warnings, f"{project_ref}: {warning}")

    project_file = Path(record.project_file).expanduser()
    if not project_file.is_file():
        if not _contains_warning(record_warnings, "projectspec file not found"):
            _warn_once(
                warnings,
                f"{project_ref}: project file is unavailable: {project_file}",
            )
        return []

    if not record.workspace_dir:
        if not _contains_warning(record_warnings, "workspace_dir"):
            _warn_once(warnings, f"{project_ref}: no primary workspace is recorded")
        return []
    primary_dir = os.path.expanduser(record.workspace_dir)
    if not Path(primary_dir).is_dir():
        _warn_once(
            warnings,
            f"{project_ref}: primary workspace is unavailable: {primary_dir}",
        )
        return []

    primary_aliases = {
        project_label,
        record.project_name,
        *(alias for alias in record.aliases if alias),
    }
    candidates = [
        _RepoCandidate(
            name=project_label,
            path=primary_dir,
            kind="primary",
            project_name=record.project_name,
            project_label=project_label,
            aliases=frozenset(primary_aliases),
        )
    ]

    project_warnings: list[str] = []
    linked = _resolve_linked_repos(str(project_file), primary_dir, project_warnings)
    sdd = _resolve_sdd_repo(primary_dir, project_warnings) if include_sdd else None
    for warning in project_warnings:
        _warn_once(warnings, f"{project_ref}: {warning}")

    for repo in linked:
        candidates.append(
            _RepoCandidate(
                name=repo.name,
                path=repo.path,
                kind="linked",
                project_name=record.project_name,
                project_label=project_label,
                aliases=frozenset((repo.name, *repo.aliases)),
            )
        )
    if sdd is not None:
        candidates.append(
            _RepoCandidate(
                name=sdd.name,
                path=sdd.path,
                kind="sdd",
                project_name=record.project_name,
                project_label=project_label,
                aliases=frozenset((sdd.name, "sdd", *sdd.aliases)),
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
    include_sdd: bool,
    warnings: list[str],
) -> list[LogRepo]:
    primary_dir = _primary_workspace_dir(project_file, cwd, workspace_num)
    display_name = project_display_name_for(project_name)
    repos: list[LogRepo] = [
        LogRepo(
            name=display_name,
            path=primary_dir,
            kind="primary",
            aliases=(project_name,) if project_name != display_name else (),
        )
    ]

    if current_only:
        return repos

    repos.extend(_resolve_linked_repos(project_file, primary_dir, warnings))
    if include_sdd:
        sdd_repo = _resolve_sdd_repo(primary_dir, warnings)
        if sdd_repo is not None:
            repos.append(sdd_repo)
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
    project_file: str, primary_dir: str, warnings: list[str]
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
        # Prefer the linked repo's primary checkout; it is the stable,
        # always-materialized copy (numbered workspaces are ephemeral).
        path = repo.primary_dir or repo.workspace_dir
        if path:
            repos.append(LogRepo(name=repo.name, path=path, kind="linked"))
    return repos


def _resolve_sdd_repo(primary_dir: str, warnings: list[str]) -> LogRepo | None:
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
        kind="sdd",
        aliases=("sdd",),
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
    return [LogRepo(name=name, path=cwd, kind="primary")]


def _deduplicate_and_name(candidates: list[_RepoCandidate]) -> list[LogRepo]:
    by_path: dict[str, list[_RepoCandidate]] = {}
    for candidate in candidates:
        canonical_path = _canonical_repo_path(candidate.path)
        by_path.setdefault(canonical_path, []).append(candidate)

    catalog: list[_CatalogRepo] = []
    for path, equivalent in by_path.items():
        winner = min(equivalent, key=_candidate_preference)
        aliases = {
            alias
            for candidate in equivalent
            for alias in (candidate.name, *candidate.aliases)
            if alias
        }
        catalog.append(
            _CatalogRepo(
                base_name=winner.name,
                path=path,
                kind=winner.kind,
                project_name=winner.project_name,
                project_label=winner.project_label,
                aliases=aliases,
            )
        )

    catalog.sort(key=_catalog_sort_key)
    _assign_unique_labels(catalog)
    return [
        LogRepo(
            name=repo.name,
            path=repo.path,
            kind=repo.kind,
            aliases=tuple(sorted(repo.aliases - {repo.name}, key=str.casefold)),
        )
        for repo in sorted(catalog, key=_catalog_sort_key)
    ]


def _canonical_repo_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def _candidate_preference(
    candidate: _RepoCandidate,
) -> tuple[int, str, str, str, str]:
    return (
        _KIND_ORDER.get(candidate.kind, 9),
        candidate.name.casefold(),
        candidate.project_label.casefold(),
        candidate.project_name,
        candidate.path,
    )


def _catalog_sort_key(repo: _CatalogRepo) -> tuple[int, str, str, str, str]:
    label = repo.name or repo.base_name
    return (
        _KIND_ORDER.get(repo.kind, 9),
        label.casefold(),
        label,
        repo.project_name,
        repo.path,
    )


def _assign_unique_labels(catalog: list[_CatalogRepo]) -> None:
    base_counts = Counter(repo.base_name for repo in catalog)
    primary_counts = Counter(
        repo.base_name for repo in catalog if repo.kind == "primary"
    )

    for repo in catalog:
        if base_counts[repo.base_name] == 1:
            repo.name = repo.base_name
        elif repo.kind == "primary" and primary_counts[repo.base_name] == 1:
            # A registered project keeps the convenient standalone name when
            # a linked-only or SDD label happens to collide with it.
            repo.name = repo.base_name
        elif repo.kind == "primary":
            repo.name = repo.project_name
        else:
            owner = repo.project_label
            if not owner or owner == repo.base_name:
                owner = repo.project_name
            repo.name = f"{owner}/{repo.base_name}"

    used: set[str] = set()
    for repo in catalog:
        proposed = repo.name
        if proposed in used:
            proposed = f"{repo.project_name}/{repo.base_name}"
        suffix = 2
        root = proposed
        while proposed in used:
            proposed = f"{root}#{suffix}"
            suffix += 1
        repo.name = proposed
        used.add(proposed)


def _apply_filters(
    repos: list[LogRepo], filters: list[str], warnings: list[str]
) -> list[LogRepo]:
    selected: set[int] = set()
    for name in filters:
        folded = name.casefold()
        direct = [
            index for index, repo in enumerate(repos) if repo.name.casefold() == folded
        ]
        if direct:
            selected.update(direct)
            continue

        aliases = [
            index
            for index, repo in enumerate(repos)
            if any(alias.casefold() == folded for alias in repo.aliases)
            or (repo.kind == "sdd" and folded == "sdd")
        ]
        if len(aliases) == 1:
            selected.add(aliases[0])
        elif len(aliases) > 1:
            choices = ", ".join(repos[index].name for index in aliases)
            _warn_once(
                warnings,
                f"--repo {name!r} is ambiguous; use one of: {choices}",
            )
        else:
            _warn_once(
                warnings,
                f"--repo {name!r} did not match any repository",
            )
    return [repo for index, repo in enumerate(repos) if index in selected]


def _resolve_exclusions(
    repos: list[LogRepo],
    filters: Sequence[str],
    warnings: list[str],
) -> set[LogRepo]:
    """Resolve exclusions against the full catalog, accepting shared aliases."""
    excluded: set[LogRepo] = set()
    for name in filters:
        folded = name.casefold()
        matches = [
            repo
            for repo in repos
            if repo.name.casefold() == folded
            or any(alias.casefold() == folded for alias in repo.aliases)
            or (repo.kind == "sdd" and folded == "sdd")
        ]
        if matches:
            excluded.update(matches)
        else:
            _warn_once(
                warnings,
                f"-repo {name!r} did not match any repository",
            )
    return excluded


def _collapse_global_warnings(warnings: list[str], repos: list[LogRepo]) -> list[str]:
    """Drop repeated discovery noise for repos already found globally."""
    known_names = {name for repo in repos for name in (repo.name, *repo.aliases)}
    collapsed: list[str] = []
    skipped_link = re.compile(r": linked repos: Skipping linked repo '([^']+)':")
    for warning in warnings:
        match = skipped_link.search(warning)
        if match is not None and match.group(1) in known_names:
            continue
        if warning not in collapsed:
            collapsed.append(warning)
    return collapsed


def _warn_once(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


__all__ = ["ResolvedRepos", "resolve_log_repos"]
