"""Thin parser facade for ``sase stitch list`` repository statistics."""

from __future__ import annotations

from sase.core.git_query_facade import parse_git_branch_name, parse_git_local_changes
from sase.core.vcs_log_facade import parse_git_log
from sase.core.vcs_repo_stats_wire import VcsRepoStatsWire


def build_vcs_repo_stats(
    *,
    total_commits_stdout: str,
    contributors_stdout: str,
    last_commit_stdout: str,
    branch_stdout: str,
    status_stdout: str,
) -> VcsRepoStatsWire:
    """Assemble repo stats from raw git command output.

    The non-trivial commit parser is the existing Rust-backed
    :func:`parse_git_log`; the remaining fields are small normalizations over
    aggregate git output collected by the provider.
    """
    commits = parse_git_log(last_commit_stdout)
    return VcsRepoStatsWire(
        total_commits=_parse_total_commits(total_commits_stdout),
        contributors=tuple(_parse_contributors(contributors_stdout)),
        last_commit=commits[0] if commits else None,
        branch=parse_git_branch_name(branch_stdout),
        dirty=parse_git_local_changes(status_stdout) is not None,
    )


def _parse_total_commits(stdout: str) -> int:
    text = stdout.strip()
    if not text:
        return 0
    try:
        value = int(text.splitlines()[0].strip())
    except (IndexError, ValueError):
        return 0
    return max(value, 0)


def _parse_contributors(stdout: str) -> list[str]:
    contributors: list[str] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        if "\t" in text:
            _, identity = text.split("\t", 1)
        else:
            parts = text.split(maxsplit=1)
            identity = parts[1] if len(parts) == 2 and parts[0].isdigit() else text
        identity = identity.strip()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        contributors.append(identity)
    return contributors


__all__ = ["build_vcs_repo_stats"]
