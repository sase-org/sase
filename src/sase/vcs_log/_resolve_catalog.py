"""Canonicalize, label, and filter repositories discovered for VCS logs."""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from sase.plan_documents import PlanWorkspace
from sase.vcs_log.models import LogRepo, LogRepoKind

_KIND_ORDER = {"primary": 0, "linked": 1, "sidecar": 2}


@dataclass(frozen=True)
class RepoCandidate:
    """One project-qualified route to a physical repository."""

    name: str
    path: str
    kind: LogRepoKind
    project_name: str
    project_label: str
    aliases: frozenset[str] = frozenset()
    plan_workspaces: tuple[PlanWorkspace, ...] = ()


@dataclass
class _CatalogRepo:
    """Canonical all-project repository before its final label is assigned."""

    base_name: str
    path: str
    kind: LogRepoKind
    project_name: str
    project_label: str
    aliases: set[str] = field(default_factory=set)
    plan_workspaces: set[PlanWorkspace] = field(default_factory=set)
    name: str = ""


def deduplicate_and_name(candidates: list[RepoCandidate]) -> list[LogRepo]:
    by_path: dict[str, list[RepoCandidate]] = {}
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
        plan_workspaces = {
            workspace
            for candidate in equivalent
            for workspace in candidate.plan_workspaces
        }
        catalog.append(
            _CatalogRepo(
                base_name=winner.name,
                path=path,
                kind=winner.kind,
                project_name=winner.project_name,
                project_label=winner.project_label,
                aliases=aliases,
                plan_workspaces=plan_workspaces,
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
            plan_workspaces=tuple(
                sorted(repo.plan_workspaces, key=_plan_workspace_sort_key)
            ),
        )
        for repo in sorted(catalog, key=_catalog_sort_key)
    ]


def _canonical_repo_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def _plan_workspace_sort_key(
    workspace: PlanWorkspace,
) -> tuple[str, str, int, str]:
    return (
        (workspace.project or "").casefold(),
        workspace.workspace_dir,
        workspace.workspace_num,
        workspace.plans_root or "",
    )


def _candidate_preference(
    candidate: RepoCandidate,
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
            # a linked-only or sidecar label happens to collide with it.
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


def apply_filters(
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
        ]
        if len(aliases) == 1:
            selected.add(aliases[0])
        elif len(aliases) > 1:
            choices = ", ".join(repos[index].name for index in aliases)
            warn_once(
                warnings,
                f"--repo {name!r} is ambiguous; use one of: {choices}",
            )
        else:
            warn_once(
                warnings,
                f"--repo {name!r} did not match any repository",
            )
    return [repo for index, repo in enumerate(repos) if index in selected]


def resolve_exclusions(
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
        ]
        if matches:
            excluded.update(matches)
        else:
            warn_once(
                warnings,
                f"-repo {name!r} did not match any repository",
            )
    return excluded


def collapse_global_warnings(warnings: list[str], repos: list[LogRepo]) -> list[str]:
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


def warn_once(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)
