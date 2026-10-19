"""Merge a Code-only Projects report onto the Output/Runs primary result."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from sase.stats.project.models import (
    ProjectStatsCoverage,
    ProjectStatsIssue,
    ProjectStatsProject,
    ProjectStatsRepo,
)
from sase.stats.project.view import ProjectStatsView


def merge_project_code_stats(
    primary: ProjectStatsView,
    code: ProjectStatsView,
) -> ProjectStatsView | None:
    """Copy Code/snapshot fields onto ``primary`` without replacing Output/Runs.

    Returns ``None`` when the two responses name different refs for the same
    repo, so the caller can revalidate instead of painting mixed revisions.
    """
    if _repo_refs_conflict(primary, code):
        return None

    code_by_key = {project.key: project for project in code.projects}
    merged_projects = tuple(
        _merge_project(project, code_by_key.get(project.key))
        for project in primary.projects
    )
    merged_data = deepcopy(primary.data)
    _merge_raw_code(merged_data, code.data)
    return ProjectStatsView(
        query=primary.query,
        projects=merged_projects,
        portfolio=replace(
            primary.portfolio,
            code=code.portfolio.code
            if code.portfolio.code is not None
            else primary.portfolio.code,
            coverage=_merge_coverage(
                primary.portfolio.coverage, code.portfolio.coverage
            ),
        ),
        issues=_merge_issues(primary.issues, code.issues),
        fingerprint=primary.fingerprint,
        machine=primary.machine,
        generated_at=primary.generated_at,
        timezone=primary.timezone,
        facets=primary.facets | code.facets,
        display_snapshot=primary.display_snapshot,
        data=merged_data,
    )


def _repo_refs(view: ProjectStatsView) -> dict[str, tuple[str, str] | None]:
    refs: dict[str, tuple[str, str] | None] = {}
    for repo in view.repos:
        if repo.ref is None:
            refs[repo.id] = None
            continue
        refs[repo.id] = (repo.ref.name, repo.ref.commit)
    return refs


def _repo_refs_conflict(primary: ProjectStatsView, code: ProjectStatsView) -> bool:
    primary_refs = _repo_refs(primary)
    code_refs = _repo_refs(code)
    for repo_id, code_ref in code_refs.items():
        primary_ref = primary_refs.get(repo_id)
        if primary_ref and code_ref and primary_ref != code_ref:
            return True
    return False


def _merge_project(
    primary: ProjectStatsProject,
    extra: ProjectStatsProject | None,
) -> ProjectStatsProject:
    if extra is None:
        return primary
    extra_repos = {repo.id: repo for repo in extra.repos}
    return replace(
        primary,
        code=extra.code if extra.code is not None else primary.code,
        repos=tuple(
            _merge_repo(repo, extra_repos.get(repo.id)) for repo in primary.repos
        ),
        coverage=_merge_coverage(primary.coverage, extra.coverage),
    )


def _merge_repo(
    primary: ProjectStatsRepo, extra: ProjectStatsRepo | None
) -> ProjectStatsRepo:
    if extra is None:
        return primary
    return replace(
        primary,
        snapshot=extra.snapshot if extra.snapshot is not None else primary.snapshot,
        issue=primary.issue if primary.issue is not None else extra.issue,
    )


def _merge_coverage(
    primary: ProjectStatsCoverage, extra: ProjectStatsCoverage
) -> ProjectStatsCoverage:
    return replace(
        primary,
        configured_repos=extra.configured_repos or primary.configured_repos,
        measured_repos=extra.measured_repos or primary.measured_repos,
        partial_repos=extra.partial_repos or primary.partial_repos,
        unavailable_repos=extra.unavailable_repos or primary.unavailable_repos,
    )


def _merge_issues(
    primary: tuple[ProjectStatsIssue, ...], extra: tuple[ProjectStatsIssue, ...]
) -> tuple[ProjectStatsIssue, ...]:
    seen = {(issue.code, issue.project, issue.repo, issue.message) for issue in primary}
    merged = list(primary)
    for issue in extra:
        key = (issue.code, issue.project, issue.repo, issue.message)
        if key in seen:
            continue
        seen.add(key)
        merged.append(issue)
    return tuple(merged)


def _merge_raw_code(primary: dict[str, Any], extra: dict[str, Any]) -> None:
    extra_projects = {
        row.get("key"): row for row in extra.get("projects") or () if row.get("key")
    }
    for row in primary.get("projects") or ():
        extra_row = extra_projects.get(row.get("key"))
        if not extra_row:
            continue
        if extra_row.get("code") is not None:
            row["code"] = deepcopy(extra_row["code"])
        extra_repos = {
            repo.get("id"): repo
            for repo in extra_row.get("repos") or ()
            if repo.get("id")
        }
        for repo in row.get("repos") or ():
            extra_repo = extra_repos.get(repo.get("id"))
            if extra_repo is None:
                continue
            if extra_repo.get("snapshot") is not None:
                repo["snapshot"] = deepcopy(extra_repo["snapshot"])
    extra_portfolio = extra.get("portfolio") or {}
    portfolio = primary.setdefault("portfolio", {})
    if extra_portfolio.get("code") is not None:
        portfolio["code"] = deepcopy(extra_portfolio["code"])
    extra_issues = extra.get("issues") or ()
    if extra_issues:
        existing = {
            (
                item.get("code"),
                item.get("project"),
                item.get("repo"),
                item.get("message"),
            )
            for item in primary.get("issues") or ()
        }
        issues = list(primary.get("issues") or ())
        for item in extra_issues:
            key = (
                item.get("code"),
                item.get("project"),
                item.get("repo"),
                item.get("message"),
            )
            if key in existing:
                continue
            existing.add(key)
            issues.append(deepcopy(item))
        primary["issues"] = issues


__all__ = ["merge_project_code_stats"]
