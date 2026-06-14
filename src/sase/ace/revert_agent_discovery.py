"""Commit discovery for Agents-tab reverts."""

from __future__ import annotations

from sase.ace.revert_agent_git import run_git
from sase.ace.revert_agent_models import RevertCommit, RevertTarget
from sase.plan_chain import agent_family_base
from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags

#: How many recent commits to scan for matching ``AGENT=`` tags.
_DISCOVERY_COMMIT_LIMIT = 300

# Field/record separators for parsing ``git log`` output robustly even when
# commit bodies contain newlines.
_UNIT_SEP = "\x1f"
_RECORD_SEP = "\x1e"
_LOG_FORMAT = f"%H{_UNIT_SEP}%h{_UNIT_SEP}%s{_UNIT_SEP}%B{_RECORD_SEP}"


def discover_agent_commits(
    workspace_dir: str,
    agent_name: str,
    *,
    family_base: str | None = None,
    limit: int = _DISCOVERY_COMMIT_LIMIT,
) -> list[RevertCommit]:
    """Return commits tagged for *agent_name* (or its family), newest-first.

    Matches the exact ``AGENT=<name>`` tag line parsed from each commit
    message. When *family_base* is set, any commit whose ``AGENT`` tag shares
    that family base also matches.
    """
    log = run_git(
        workspace_dir,
        ["log", f"-{limit}", "--no-merges", f"--format={_LOG_FORMAT}"],
    )
    if log.returncode != 0:
        return []

    commits: list[RevertCommit] = []
    for full_sha, short_sha, subject, body in _parse_log_records(log.stdout):
        tags = parse_trailing_commit_tags(body)
        agent_value = tags.get("AGENT")
        if not _agent_tag_matches(agent_value, agent_name, family_base):
            continue
        commits.append(
            RevertCommit(
                sha=short_sha,
                full_sha=full_sha,
                subject=subject,
                agent_tag=agent_value or "",
                changed_paths=tuple(_commit_changed_paths(workspace_dir, full_sha)),
            )
        )
    return commits


def discover_bulk_commits(
    workspace_dir: str,
    targets: tuple[RevertTarget, ...],
    *,
    limit: int = _DISCOVERY_COMMIT_LIMIT,
) -> tuple[list[RevertCommit], set[str]]:
    """Scan history once and match commits against every target.

    Returns ``(commits, matched_names)`` where *commits* is deduplicated by
    full SHA (so marking both a family parent and a child cannot revert the
    same commit twice) and preserves git-log newest-first order across the
    combined set, and *matched_names* is the set of target agent names that
    matched at least one commit. A target whose only matches are commits
    already contributed by another target is still recorded as matched.
    """
    log = run_git(
        workspace_dir,
        ["log", f"-{limit}", "--no-merges", f"--format={_LOG_FORMAT}"],
    )
    if log.returncode != 0:
        return [], set()

    commits: list[RevertCommit] = []
    matched: set[str] = set()
    seen_shas: set[str] = set()
    for full_sha, short_sha, subject, body in _parse_log_records(log.stdout):
        tags = parse_trailing_commit_tags(body)
        agent_value = tags.get("AGENT")
        if not agent_value:
            continue
        matching = [
            t
            for t in targets
            if _agent_tag_matches(agent_value, t.agent_name, t.family_base)
        ]
        if not matching:
            continue
        for target in matching:
            matched.add(target.agent_name)
        if full_sha in seen_shas:
            continue
        seen_shas.add(full_sha)
        commits.append(
            RevertCommit(
                sha=short_sha,
                full_sha=full_sha,
                subject=subject,
                agent_tag=agent_value,
                changed_paths=tuple(_commit_changed_paths(workspace_dir, full_sha)),
            )
        )
    return commits, matched


def _agent_tag_matches(
    tag_value: str | None,
    agent_name: str,
    family_base: str | None,
) -> bool:
    if not tag_value:
        return False
    if tag_value == agent_name:
        return True
    if family_base is not None:
        tag_base = agent_family_base(tag_value) or tag_value
        return tag_base == family_base
    return False


def _parse_log_records(stdout: str) -> list[tuple[str, str, str, str]]:
    records: list[tuple[str, str, str, str]] = []
    for raw in stdout.split(_RECORD_SEP):
        chunk = raw.lstrip("\n")
        if not chunk.strip():
            continue
        fields = chunk.split(_UNIT_SEP, 3)
        if len(fields) < 4:
            continue
        full_sha, short_sha, subject, body = fields
        records.append((full_sha.strip(), short_sha.strip(), subject, body))
    return records


def _commit_changed_paths(workspace_dir: str, full_sha: str) -> list[str]:
    out = run_git(
        workspace_dir,
        ["diff-tree", "--no-commit-id", "--name-only", "-r", full_sha],
    )
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


__all__ = [
    "_agent_tag_matches",
    "_commit_changed_paths",
    "_parse_log_records",
    "discover_agent_commits",
    "discover_bulk_commits",
]
