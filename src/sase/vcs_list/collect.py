"""Collect repository listings for ``sase vcs list``."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.core.vcs_repo_stats_wire import VcsRepoStatsWire
from sase.vcs_list.models import (
    DescriptionSource,
    RepoListing,
    VcsListResult,
    VcsListSort,
    VcsListTotals,
)
from sase.vcs_log.models import LogRepo
from sase.vcs_log.resolve import resolve_log_repos

ProviderFactory = Callable[[str], object]


def _collect_vcs_list(
    repos: Sequence[LogRepo],
    *,
    no_fetch: bool = False,
    sort: VcsListSort = "default",
    provider_factory: ProviderFactory | None = None,
) -> VcsListResult:
    """Collect stats and descriptions for an already-resolved repo set."""
    factory = provider_factory or _default_provider_factory()
    descriptions = _linked_config_descriptions(_primary_dir(repos))

    listings: list[RepoListing] = []
    warnings: list[str] = []
    for repo in repos:
        stats: VcsRepoStatsWire | None = None
        error: str | None = None
        try:
            provider = factory(repo.path)
            stats = provider.repo_stats(cwd=repo.path)  # type: ignore[attr-defined]
        except Exception as exc:
            error = _failure_reason(exc)
            warnings.append(f"{repo.name}: {error}")

        description, source = _resolve_description(
            repo,
            descriptions,
            no_fetch=no_fetch,
        )
        listings.append(
            RepoListing(
                repo=repo,
                stats=stats,
                description=description,
                description_source=source,
                error=error,
            )
        )

    sorted_listings = _sort_listings(listings, sort)
    return VcsListResult(
        repos=tuple(sorted_listings),
        totals=_totals(listings),
        warnings=tuple(warnings),
        color_repos=tuple(repos),
    )


def run_vcs_list(
    *,
    cwd: str,
    repo_filters: Sequence[str] = (),
    current_only: bool = False,
    no_fetch: bool = False,
    sort: VcsListSort = "default",
    provider_factory: ProviderFactory | None = None,
) -> VcsListResult:
    """Resolve the repo set, collect listings, and merge warnings."""
    resolved = resolve_log_repos(
        cwd=cwd,
        repo_filters=repo_filters,
        current_only=current_only,
        include_sdd=True,
    )
    collected = _collect_vcs_list(
        resolved.repos,
        no_fetch=no_fetch,
        sort=sort,
        provider_factory=provider_factory,
    )
    return VcsListResult(
        repos=collected.repos,
        totals=collected.totals,
        warnings=tuple(resolved.warnings) + collected.warnings,
        color_repos=collected.color_repos,
    )


def _default_provider_factory() -> ProviderFactory:
    from sase.vcs_provider import get_vcs_provider

    return get_vcs_provider


def _primary_dir(repos: Sequence[LogRepo]) -> str | None:
    for repo in repos:
        if repo.kind == "primary":
            return repo.path
    return None


def _linked_config_descriptions(primary_dir: str | None) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for entry in _linked_config_entries(primary_dir):
        name = entry.get("name")
        description = entry.get("description")
        if not isinstance(name, str) or not isinstance(description, str):
            continue
        normalized = description.strip()
        if normalized:
            descriptions.setdefault(name.strip(), normalized)
    return descriptions


def _linked_config_entries(primary_dir: str | None) -> list[Mapping[str, Any]]:
    entries: list[Mapping[str, Any]] = []
    try:
        from sase.config import load_merged_config

        entries.extend(_entries_from_config(load_merged_config()))
    except Exception:
        pass

    if primary_dir:
        entries.extend(_entries_from_config(_read_primary_local_config(primary_dir)))
    return entries


def _entries_from_config(config: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    entries: list[Mapping[str, Any]] = []
    for key in ("linked_repos", "sibling_repos"):
        raw = config.get(key, [])
        if not isinstance(raw, list):
            continue
        entries.extend(item for item in raw if isinstance(item, Mapping))
    return entries


def _read_primary_local_config(primary_dir: str) -> dict[str, Any]:
    from sase.content_layout import resolve_project_config_read_path

    path = resolve_project_config_read_path(Path(primary_dir).expanduser())
    if path is None:
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _resolve_description(
    repo: LogRepo,
    descriptions: Mapping[str, str],
    *,
    no_fetch: bool,
) -> tuple[str | None, DescriptionSource | None]:
    if repo.kind == "linked":
        description = descriptions.get(repo.name)
        if description:
            return description, "config"
    if no_fetch:
        return None, None
    # Future provider-backed descriptions can be added here without changing
    # repo resolution or the rendered JSON shape.
    return None, None


def _sort_listings(
    listings: Sequence[RepoListing],
    sort: VcsListSort,
) -> list[RepoListing]:
    rows = list(listings)
    if sort == "name":
        rows.sort(key=lambda item: item.repo.name.casefold())
    elif sort == "commits":
        rows.sort(
            key=lambda item: (
                -(item.stats.total_commits if item.stats else -1),
                item.repo.name.casefold(),
            )
        )
    elif sort == "recent":
        rows.sort(key=_recent_sort_key)
    return rows


def _recent_sort_key(item: RepoListing) -> tuple[int, str]:
    timestamp = _last_timestamp(item.stats)
    return (-(timestamp if timestamp is not None else -1), item.repo.name.casefold())


def _totals(listings: Sequence[RepoListing]) -> VcsListTotals:
    contributors: set[str] = set()
    total_commits = 0
    latest_activity: int | None = None
    for listing in listings:
        stats = listing.stats
        if stats is None:
            continue
        total_commits += stats.total_commits
        contributors.update(stats.contributors)
        timestamp = _last_timestamp(stats)
        if timestamp is not None:
            latest_activity = (
                timestamp
                if latest_activity is None
                else max(latest_activity, timestamp)
            )
    return VcsListTotals(
        repo_count=len(listings),
        total_commits=total_commits,
        contributors=tuple(sorted(contributors, key=str.casefold)),
        latest_activity=latest_activity,
    )


def _last_timestamp(stats: VcsRepoStatsWire | None) -> int | None:
    if stats is None or stats.last_commit is None:
        return None
    return stats.last_commit.timestamp


def _failure_reason(exc: Exception) -> str:
    message = str(exc).strip()
    return message or type(exc).__name__


__all__ = ["ProviderFactory", "run_vcs_list"]
