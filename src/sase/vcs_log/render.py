"""Renderers for ``sase stitch log`` — ``pretty``, ``full``, ``oneline``, and ``json``.

Mirrors the dual-output + ``--color`` contract used by ``sase plan
search``: the JSON branch returns a plain string (no Rich), and the
colored output routes through a ``make_console`` factory that honors
``auto``/``always``/``never`` plus ``NO_COLOR`` and TTY detection. All
wall-clock formatting goes through :mod:`sase.core.time` so it respects
the configured timezone; sorting stays epoch-based upstream and is
timezone-immune.

This module owns format dispatch and the shared builders that the ACE
timelines reuse. The format implementations live in
:mod:`sase.vcs_log._render_plain` (``json``, ``oneline``) and
:mod:`sase.vcs_log._render_console` (``pretty``, ``full``), over the
helpers in :mod:`sase.vcs_log._render_util`.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import TextIO

from rich.text import Text

from sase.core.vcs_log_wire import AggregatedCommitWire
from sase.vcs_log.models import CommitFilters, VcsLogResult
from sase.vcs_log._render_console import commit_line, day_header, legend
from sase.vcs_log._render_console import render_full as _render_full
from sase.vcs_log._render_console import render_pretty as _render_pretty
from sase.vcs_log._render_plain import render_json, render_oneline
from sase.vcs_log._render_util import (
    build_commit_presence,
    day_label,
    local_now,
    ordered_commits,
    relative_age_between,
    to_local,
)
from sase.vcs_log._style import repo_colors


def render(
    result: VcsLogResult,
    *,
    fmt: str,
    color: str,
    out: TextIO | None = None,
    limit: int = 40,
    filters: CommitFilters | None = None,
    reverse: bool = False,
    show_tags: bool = True,
    all_projects: bool = False,
) -> None:
    """Render *result* in the requested format to *out* (default stdout)."""
    stream = out if out is not None else sys.stdout
    filters = filters or result.resolved_filters or CommitFilters()
    commits = ordered_commits(
        result,
        filters=filters,
        limit=limit,
        reverse=reverse,
    )
    if fmt == "json":
        stream.write(
            render_json(
                result,
                commits,
                limit,
                filters,
                reverse,
                show_tags,
                all_projects,
            )
        )
        return
    if fmt == "oneline":
        stream.write(render_oneline(commits, show_tags=show_tags))
        return
    if fmt == "full":
        _render_full(
            result,
            commits,
            color=color,
            out=stream,
            filters=filters,
            show_tags=show_tags,
        )
        return
    _render_pretty(
        result,
        commits,
        color=color,
        out=stream,
        filters=filters,
        show_tags=show_tags,
    )


# ---------------------------------------------------------------------------
# shared builders (CLI + interactive timelines)
# ---------------------------------------------------------------------------


def build_pretty_legend(
    result: VcsLogResult,
    *,
    filters: CommitFilters | None = None,
    visible_repos_only: bool = False,
    show_filter_summary: bool = True,
) -> Text:
    """Build the shared Rich legend used by CLI and interactive timelines."""
    return legend(
        result,
        tuple(result.commits),
        repo_colors(result.repos),
        filters or CommitFilters(),
        visible_repos_only=visible_repos_only,
        show_filter_summary=show_filter_summary,
    )


def build_timeline_day(
    timestamp: int,
    *,
    now_local: datetime | None = None,
) -> tuple[str, Text]:
    """Return the grouping key and banner for a commit timestamp."""
    label = day_label(to_local(timestamp), now_local or local_now())
    return label, day_header(label)


def build_timeline_commit(
    entry: AggregatedCommitWire,
    result: VcsLogResult,
    *,
    show_tags: bool = True,
    show_author: bool = True,
) -> Text:
    """Build one shared pretty timeline row for an aggregated commit."""
    commits = tuple(result.commits)
    repo_width = max((len(item.repo) for item in commits), default=len(entry.repo))
    sha_width = max(
        (len(item.commit.short_id) for item in commits),
        default=len(entry.commit.short_id),
    )
    merge_column = any(item.commit.is_merge for item in commits)
    line = commit_line(
        entry,
        repo_colors(result.repos),
        repo_width,
        sha_width,
        to_local(entry.commit.timestamp),
        show_tags,
        show_author,
        merge_column=merge_column,
    )
    line.no_wrap = True
    line.overflow = "ellipsis"
    return line


def build_commit_time_chip(
    timestamp: int,
    *,
    now_local: datetime | None = None,
) -> Text:
    """Build the compact ``<day> <clock> · <age>`` chip for one commit time."""
    dt_local = to_local(timestamp)
    reference = now_local or local_now()
    label = day_label(dt_local, reference)
    clock_format = "%H:%M:%S" if label in ("Today", "Yesterday") else "%H:%M"

    text = Text(no_wrap=True)
    text.append(f"{label} {dt_local:{clock_format}}", style="#D7AF5F")
    text.append(f" · {relative_age_between(dt_local, reference)}", style="dim #D7AF5F")
    return text


def format_commit_timestamp(timestamp: int) -> str:
    """Format a complete commit timestamp in the configured local timezone."""
    dt_local = to_local(timestamp)
    return f"{dt_local:%A, %B} {dt_local.day}, {dt_local:%Y at %H:%M:%S}"


__all__ = [
    "build_commit_presence",
    "build_commit_time_chip",
    "build_pretty_legend",
    "build_timeline_commit",
    "build_timeline_day",
    "format_commit_timestamp",
    "render",
]
