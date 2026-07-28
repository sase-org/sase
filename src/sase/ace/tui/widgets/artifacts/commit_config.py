"""Configuration resolution for the Artifacts commits pane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from sase.vcs_log.filter_query import (
    CommitFilterQueryError,
    CommitLogFilterValues,
    parse_commit_filter_query,
)


BUNDLED_COMMITS_DEFAULT_QUERY = "sidecar:false since:24h"
_CONFIG_PATH = "ace.artifacts.commits.default_query"


@dataclass(frozen=True)
class _ResolvedCommitsDefaultQuery:
    """Parsed startup query plus an optional fallback diagnostic."""

    values: CommitLogFilterValues
    diagnostic: str | None = None


def resolve_commits_default_query(
    ace_config: Mapping[str, Any] | object,
) -> _ResolvedCommitsDefaultQuery:
    """Resolve and validate the commits query from already-loaded ACE config."""
    if not isinstance(ace_config, Mapping):
        return _bundled_fallback("ACE configuration is not an object")

    artifacts = ace_config.get("artifacts")
    if artifacts is None:
        return _bundled_default()
    if not isinstance(artifacts, Mapping):
        return _bundled_fallback("ace.artifacts is not an object")

    commits = artifacts.get("commits")
    if commits is None:
        return _bundled_default()
    if not isinstance(commits, Mapping):
        return _bundled_fallback("ace.artifacts.commits is not an object")

    configured = commits.get("default_query")
    if configured is None:
        return _bundled_default()
    if not isinstance(configured, str):
        return _bundled_fallback(f"{_CONFIG_PATH} must be a string")

    try:
        values = parse_commit_filter_query(configured)
    except CommitFilterQueryError as exc:
        return _bundled_fallback(
            f"{_CONFIG_PATH} is invalid: {exc.message}",
        )
    return _ResolvedCommitsDefaultQuery(values)


def merge_commits_startup_project(
    values: CommitLogFilterValues,
    *,
    explicit_project: str | None,
    current_project: str | None,
) -> CommitLogFilterValues:
    """Apply startup project precedence to an already parsed default query."""
    project = explicit_project or values.project or current_project
    if project == values.project:
        return values
    return replace(values, project=project)


def _bundled_default() -> _ResolvedCommitsDefaultQuery:
    return _ResolvedCommitsDefaultQuery(
        parse_commit_filter_query(BUNDLED_COMMITS_DEFAULT_QUERY)
    )


def _bundled_fallback(reason: str) -> _ResolvedCommitsDefaultQuery:
    return _ResolvedCommitsDefaultQuery(
        parse_commit_filter_query(BUNDLED_COMMITS_DEFAULT_QUERY),
        _fallback_diagnostic(reason),
    )


def _fallback_diagnostic(reason: str) -> str:
    return f"{reason}; using bundled commits query {BUNDLED_COMMITS_DEFAULT_QUERY!r}"


__all__ = [
    "BUNDLED_COMMITS_DEFAULT_QUERY",
    "merge_commits_startup_project",
    "resolve_commits_default_query",
]
