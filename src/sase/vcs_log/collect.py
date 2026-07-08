"""Collect and interleave commit logs across the resolved repo set.

Each repo's log is fetched in its own ``try``/``except`` so one failing
repo (missing checkout, non-VCS path, provider without ``vcs_log``, or a
``git`` error) becomes a warning rather than crashing the whole command.
The per-repo lists are then merged into one chronological timeline by the
Rust core aggregator.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from sase.core.vcs_log_facade import aggregate_commit_log
from sase.vcs_log.models import UNLIMITED, CommitFilters, LogRepo, VcsLogResult
from sase.vcs_log.resolve import resolve_log_repos

#: A callable that returns a VCS provider for a repo path. Injectable so the
#: collection logic can be tested without real repositories.
ProviderFactory = Callable[[str], object]


def collect_vcs_log(
    repos: Sequence[LogRepo],
    *,
    limit: int,
    filters: CommitFilters | None = None,
    provider_factory: ProviderFactory | None = None,
) -> VcsLogResult:
    """Fetch each repo's log (isolated) and merge into one timeline.

    Fetches up to *limit* commits per repo so the merged top-*limit* by
    time is correct even when a single repo dominates recent activity.
    """
    factory = provider_factory or _default_provider_factory()
    filters = filters or CommitFilters()
    effective_limit = _effective_limit(limit)

    per_repo: list[tuple[str, list]] = []
    ok_repos: list[LogRepo] = []
    warnings: list[str] = []

    for repo in repos:
        try:
            provider = factory(repo.path)
            commits = provider.log(  # type: ignore[attr-defined]
                cwd=repo.path,
                limit=effective_limit,
                since=filters.since,
                until=filters.until,
                authors=filters.authors,
            )
        except Exception as exc:
            warnings.append(f"{repo.name}: {_failure_reason(exc)}")
            continue
        per_repo.append((repo.name, commits))
        ok_repos.append(repo)

    aggregated = aggregate_commit_log(per_repo, effective_limit)
    return VcsLogResult(
        repos=tuple(ok_repos),
        commits=tuple(aggregated),
        warnings=tuple(warnings),
    )


def run_vcs_log(
    *,
    cwd: str,
    limit: int,
    filters: CommitFilters | None = None,
    repo_filters: Sequence[str] = (),
    current_only: bool = False,
    provider_factory: ProviderFactory | None = None,
) -> VcsLogResult:
    """Resolve the repo set, collect logs, and merge resolution warnings.

    The top-level entry point used by the CLI handler: resolution warnings
    are surfaced ahead of collection warnings so the user sees config
    problems first.
    """
    resolved = resolve_log_repos(
        cwd=cwd, repo_filters=repo_filters, current_only=current_only
    )
    collected = collect_vcs_log(
        resolved.repos,
        limit=limit,
        filters=filters,
        provider_factory=provider_factory,
    )
    return VcsLogResult(
        repos=collected.repos,
        commits=collected.commits,
        warnings=tuple(resolved.warnings) + collected.warnings,
    )


def _default_provider_factory() -> ProviderFactory:
    from sase.vcs_provider import get_vcs_provider

    return get_vcs_provider


def _failure_reason(exc: Exception) -> str:
    message = str(exc).strip()
    return message or type(exc).__name__


def _effective_limit(limit: int) -> int:
    return UNLIMITED if limit == 0 else limit


__all__ = ["ProviderFactory", "collect_vcs_log", "run_vcs_log"]
