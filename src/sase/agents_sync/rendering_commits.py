"""Shared commit-table rendering for agent and family browsing pages."""

from __future__ import annotations

from datetime import UTC, datetime

from sase.agents_sync.models import CommitRecord
from sase.agents_sync.rendering_markdown import md_cell, md_code

MAX_RENDERED_COMMITS = 50


def render_agent_commits(
    commits: tuple[CommitRecord, ...],
    *,
    commit_url_base: str | None,
) -> list[str]:
    """Render one run's bounded commit table."""

    rows = tuple(
        (commit, None)
        for commit in sorted(
            commits,
            key=lambda item: (item.committed_at, item.sha),
        )
    )
    return _render_commit_table(
        rows,
        commit_url_base=commit_url_base,
        include_role=False,
    )


def render_family_commits(
    commits: tuple[tuple[CommitRecord, str], ...],
    *,
    commit_url_base: str | None,
) -> list[str]:
    """Render a family's bounded, role-attributed commit table."""

    rows = tuple(
        sorted(
            commits,
            key=lambda item: (item[0].committed_at, item[0].sha, item[1]),
        )
    )
    return _render_commit_table(
        rows,
        commit_url_base=commit_url_base,
        include_role=True,
    )


def _render_commit_table(
    rows: tuple[tuple[CommitRecord, str | None], ...],
    *,
    commit_url_base: str | None,
    include_role: bool,
) -> list[str]:
    lines = (
        [
            "| Role | Commit | Subject | Committed (UTC) |",
            "|---|---|---|---|",
        ]
        if include_role
        else [
            "| Commit | Subject | Committed (UTC) |",
            "|---|---|---|",
        ]
    )
    for commit, role in rows[:MAX_RENDERED_COMMITS]:
        commit_cell = f"`{md_code(commit.sha[:7])}`"
        if commit_url_base is not None:
            commit_cell = f"[{commit_cell}]({commit_url_base}/{commit.sha})"
        committed = datetime.fromtimestamp(commit.committed_at, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        cells = [
            commit_cell,
            md_cell(commit.subject),
            committed,
        ]
        if include_role:
            cells.insert(0, md_cell(role or "root"))
        lines.append("| " + " | ".join(cells) + " |")
    remaining = len(rows) - MAX_RENDERED_COMMITS
    if remaining > 0:
        lines.extend(["", f"… and {remaining} more commits"])
    return lines


__all__ = [
    "MAX_RENDERED_COMMITS",
    "render_agent_commits",
    "render_family_commits",
]
