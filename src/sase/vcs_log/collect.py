"""Collect and interleave commit logs across the resolved repo set.

Each repo's log is fetched in its own ``try``/``except`` so one failing
repo (missing checkout, non-VCS path, provider without ``vcs_log``, or a
``git`` error) becomes a warning rather than crashing the whole command.
The per-repo lists are then merged into one chronological timeline by the
Rust core aggregator.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from sase.core.vcs_log_facade import aggregate_commit_log, classify_commit_presence
from sase.core.vcs_log_wire import CommitPresence, VcsCommitWire
from sase.vcs_log.models import (
    UNLIMITED,
    CommitFilters,
    LogRepo,
    RepoRemoteState,
    VcsLogResult,
)
from sase.vcs_log.resolve import resolve_log_repos

#: A callable that returns a VCS provider for a repo path. Injectable so the
#: collection logic can be tested without real repositories.
ProviderFactory = Callable[[str], object]


def collect_vcs_log(
    repos: Sequence[LogRepo],
    *,
    limit: int,
    filters: CommitFilters | None = None,
    no_fetch: bool = False,
    remote_ref: str | None = None,
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
    remote_states: list[RepoRemoteState] = []
    warnings: list[str] = []

    for repo in repos:
        try:
            provider = factory(repo.path)
            commits, state, repo_warnings = _collect_repo_commits(
                provider,
                repo,
                effective_limit,
                filters,
                no_fetch=no_fetch,
                remote_ref=remote_ref,
            )
        except Exception as exc:
            warnings.append(f"{repo.name}: {_failure_reason(exc)}")
            continue
        per_repo.append((repo.name, commits))
        ok_repos.append(repo)
        remote_states.append(state)
        warnings.extend(repo_warnings)

    aggregated = aggregate_commit_log(per_repo, effective_limit)
    return VcsLogResult(
        repos=tuple(ok_repos),
        commits=tuple(aggregated),
        warnings=tuple(warnings),
        remote_states=tuple(remote_states),
    )


def run_vcs_log(
    *,
    cwd: str,
    limit: int,
    filters: CommitFilters | None = None,
    repo_filters: Sequence[str] = (),
    current_only: bool = False,
    no_fetch: bool = False,
    remote_ref: str | None = None,
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
        no_fetch=no_fetch,
        remote_ref=remote_ref,
        provider_factory=provider_factory,
    )
    return VcsLogResult(
        repos=collected.repos,
        commits=collected.commits,
        warnings=tuple(resolved.warnings) + collected.warnings,
        remote_states=collected.remote_states,
    )


def _default_provider_factory() -> ProviderFactory:
    from sase.vcs_provider import get_vcs_provider

    return get_vcs_provider


def _failure_reason(exc: Exception) -> str:
    message = str(exc).strip()
    return message or type(exc).__name__


def _collect_repo_commits(
    provider: object,
    repo: LogRepo,
    limit: int,
    filters: CommitFilters,
    *,
    no_fetch: bool,
    remote_ref: str | None,
) -> tuple[list[VcsCommitWire], RepoRemoteState, list[str]]:
    warnings: list[str] = []
    resolved_ref, resolver_available = _resolve_remote_ref(
        provider, repo.path, remote_ref
    )
    if resolved_ref is None:
        commits = _local_log(provider, repo.path, limit, filters)
        if resolver_available:
            warnings.append(
                f"{repo.name}: no usable origin remote; showing local commits"
            )
        return (
            _mark_presence(commits, "unknown"),
            RepoRemoteState(repo.name, None, 0, 0, False),
            warnings,
        )

    fetched = False
    if not no_fetch:
        ok, error = provider.fetch_remote(  # type: ignore[attr-defined]
            cwd=repo.path,
            refs=(resolved_ref,),
        )
        fetched = ok
        if not ok:
            warnings.append(
                f"{repo.name}: fetch failed for {resolved_ref}: "
                f"{error or 'unknown error'}; using existing remote ref"
            )

    try:
        commits = provider.log(  # type: ignore[attr-defined]
            cwd=repo.path,
            limit=limit,
            since=filters.since,
            until=filters.until,
            authors=filters.authors,
            revs=("HEAD", resolved_ref),
        )
        ahead, behind = provider.partition_commits(  # type: ignore[attr-defined]
            cwd=repo.path,
            local_ref="HEAD",
            remote_ref=resolved_ref,
        )
    except Exception as exc:
        reason = _failure_reason(exc)
        warnings.append(
            f"{repo.name}: remote comparison unavailable for {resolved_ref}: "
            f"{reason}; showing local commits"
        )
        commits = _local_log(provider, repo.path, limit, filters)
        return (
            _mark_presence(commits, "unknown"),
            RepoRemoteState(repo.name, None, 0, 0, fetched),
            warnings,
        )

    return (
        classify_commit_presence(commits, ahead, behind),
        RepoRemoteState(repo.name, resolved_ref, len(ahead), len(behind), fetched),
        warnings,
    )


def _resolve_remote_ref(
    provider: object, cwd: str, ref_name: str | None
) -> tuple[str | None, bool]:
    resolver = getattr(provider, "resolve_remote_log_ref", None)
    if resolver is None:
        return (None, False)
    return (resolver(cwd=cwd, ref_name=ref_name), True)


def _local_log(
    provider: object, cwd: str, limit: int, filters: CommitFilters
) -> list[VcsCommitWire]:
    return provider.log(  # type: ignore[attr-defined]
        cwd=cwd,
        limit=limit,
        since=filters.since,
        until=filters.until,
        authors=filters.authors,
    )


def _mark_presence(
    commits: Sequence[VcsCommitWire], presence: CommitPresence
) -> list[VcsCommitWire]:
    return [replace(commit, presence=presence) for commit in commits]


def _effective_limit(limit: int) -> int:
    return UNLIMITED if limit == 0 else limit


__all__ = ["ProviderFactory", "collect_vcs_log", "run_vcs_log"]
