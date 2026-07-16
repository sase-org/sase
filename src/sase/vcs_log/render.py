"""Renderers for ``sase vcs log`` — ``pretty``, ``full``, ``oneline``, and ``json``.

Mirrors the dual-output + ``--color`` contract used by ``sase plan
search``: the JSON branch returns a plain string (no Rich), and the
colored output routes through a ``make_console`` factory that honors
``auto``/``always``/``never`` plus ``NO_COLOR`` and TTY detection. All
wall-clock formatting goes through :mod:`sase.core.time` so it respects
the configured timezone; sorting stays epoch-based upstream and is
timezone-immune.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import TextIO

from rich.console import Console
from rich.text import Text

from sase.core.vcs_log_wire import AggregatedCommitWire, CommitPresence
from sase.vcs_log.models import CommitFilters, LogRepo, RepoRemoteState, VcsLogResult
from sase.vcs_log._style import GOLD, INCOMING, UNPUSHED, make_console, repo_colors
from sase.vcs_log._tag_style import full_tag_lines, inline_tag_text
from sase.vcs_log.tags import commit_tag_view

_HEADER_WIDTH = 56


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
    filters = filters or CommitFilters()
    commits = _ordered_commits(result, reverse=reverse)
    if fmt == "json":
        stream.write(
            _render_json(
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
        stream.write(_render_oneline(commits, show_tags=show_tags))
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
# json
# ---------------------------------------------------------------------------


def _render_json(
    result: VcsLogResult,
    commits: tuple[AggregatedCommitWire, ...],
    limit: int,
    filters: CommitFilters,
    reverse: bool,
    show_tags: bool,
    all_projects: bool,
) -> str:
    states = {state.name: state for state in result.remote_states}
    payload = {
        "repos": [_repo_json(repo, states) for repo in result.repos],
        "commits": [_commit_json(entry, show_tags=show_tags) for entry in commits],
        "query": {
            "all": all_projects,
            "limit": limit,
            "since": filters.since,
            "until": filters.until,
            "authors": list(filters.authors),
            "reverse": reverse,
        },
        "warnings": list(result.warnings),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _commit_json(entry: AggregatedCommitWire, *, show_tags: bool) -> dict[str, object]:
    item: dict[str, object] = {
        "repo": entry.repo,
        "full_id": entry.commit.full_id,
        "short_id": entry.commit.short_id,
        "author_name": entry.commit.author_name,
        "author_email": entry.commit.author_email,
        "timestamp": entry.commit.timestamp,
        "subject": entry.commit.subject,
        "presence": entry.commit.presence,
    }
    if show_tags:
        item["sase_tags"] = dict(commit_tag_view(entry.commit).tags)
    return item


def _repo_json(repo: LogRepo, states: dict[str, RepoRemoteState]) -> dict[str, object]:
    state = states.get(repo.name, RepoRemoteState(repo.name, None, 0, 0, False))
    return {
        "name": repo.name,
        "kind": repo.kind,
        "path": repo.path,
        "remote_ref": state.remote_ref,
        "ahead": state.ahead,
        "behind": state.behind,
        "fetched": state.fetched,
        "fetched_at": state.fetched_at,
    }


# ---------------------------------------------------------------------------
# oneline
# ---------------------------------------------------------------------------


def _render_oneline(
    commits: tuple[AggregatedCommitWire, ...], *, show_tags: bool
) -> str:
    if not commits:
        return ""
    repo_width = max(len(entry.repo) for entry in commits)
    sha_width = max(len(entry.commit.short_id) for entry in commits)
    lines = [
        f"{_presence_glyph(entry.commit.presence)} "
        f"{entry.commit.short_id.ljust(sha_width)} "
        f"{entry.repo.ljust(repo_width)} {entry.commit.subject}"
        f"{_oneline_tag_suffix(entry) if show_tags else ''}"
        for entry in commits
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# pretty
# ---------------------------------------------------------------------------


def _render_pretty(
    result: VcsLogResult,
    commits: tuple[AggregatedCommitWire, ...],
    *,
    color: str,
    out: TextIO,
    filters: CommitFilters,
    show_tags: bool,
) -> None:
    console = make_console(color, file=out)
    colors = _repo_colors(result)

    if not commits:
        console.print(Text(_empty_message(filters), style="dim"))
        _print_warnings(console, result)
        return

    console.print(_legend(result, commits, colors, filters), soft_wrap=True)
    console.print()

    repo_width = max(len(entry.repo) for entry in commits)
    sha_width = max(len(entry.commit.short_id) for entry in commits)
    now_local = _local_now()
    current_day: str | None = None
    for entry in commits:
        dt_local = _to_local(entry.commit.timestamp)
        day = _day_label(dt_local, now_local)
        if day != current_day:
            console.print(_day_header(day), soft_wrap=True)
            current_day = day
        console.print(
            _commit_line(
                entry,
                colors,
                repo_width,
                sha_width,
                dt_local,
                show_tags=show_tags,
            ),
            soft_wrap=True,
        )

    _print_warnings(console, result)


def _render_full(
    result: VcsLogResult,
    commits: tuple[AggregatedCommitWire, ...],
    *,
    color: str,
    out: TextIO,
    filters: CommitFilters,
    show_tags: bool,
) -> None:
    console = make_console(color, file=out)
    colors = _repo_colors(result)

    if not commits:
        console.print(Text(_empty_message(filters), style="dim"))
        _print_warnings(console, result)
        return

    console.print(_legend(result, commits, colors, filters), soft_wrap=True)
    console.print()

    now_local = _local_now()
    current_day: str | None = None
    for i, entry in enumerate(commits):
        dt_local = _to_local(entry.commit.timestamp)
        day = _day_label(dt_local, now_local)
        if day != current_day:
            console.print(_day_header(day), soft_wrap=True)
            current_day = day
        _print_full_commit(console, entry, colors, dt_local, show_tags=show_tags)
        if i != len(commits) - 1:
            console.print()

    _print_warnings(console, result)


def _legend(
    result: VcsLogResult,
    commits: tuple[AggregatedCommitWire, ...],
    colors: dict[str, str],
    filters: CommitFilters,
) -> Text:
    counts: dict[str, int] = {}
    for entry in commits:
        counts[entry.repo] = counts.get(entry.repo, 0) + 1

    text = Text("  ")
    for i, repo in enumerate(result.repos):
        if i:
            text.append("  ·  ", style="dim")
        style = colors.get(repo.name, "")
        text.append(repo.name, style=f"bold {style}".strip())
        count = counts.get(repo.name, 0)
        text.append(f" ({count})", style="dim")
        state = _remote_state(result, repo.name)
        if state.remote_ref is not None or state.ahead or state.behind:
            text.append(f"  ↑{state.ahead} ↓{state.behind}", style="dim")
    summary = _filter_summary(filters)
    if summary:
        text.append("  ·  ", style="dim")
        text.append(summary, style="dim")
    text.append("  ·  ", style="dim")
    text.append("↑ unpushed", style=UNPUSHED)
    text.append("  ", style="dim")
    text.append("↓ GitHub-only", style=INCOMING)
    text.append("  ", style="dim")
    text.append("● synced", style="dim")
    remote_summary = _remote_summary(result.remote_states)
    if remote_summary:
        text.append("\n  ", style="dim")
        text.append(remote_summary, style="dim")
    return text


def _day_header(day: str) -> Text:
    text = Text("  ")
    label = f"── {day} "
    text.append(label, style="bold")
    pad = max(3, _HEADER_WIDTH - len(label))
    text.append("─" * pad, style="dim")
    return text


def _commit_line(
    entry: AggregatedCommitWire,
    colors: dict[str, str],
    repo_width: int,
    sha_width: int,
    dt_local: datetime,
    show_tags: bool,
) -> Text:
    commit = entry.commit
    repo_color = colors.get(entry.repo, "")

    line = Text("   ")
    line.append(
        f"{_presence_glyph(commit.presence)} ",
        style=_presence_style(commit.presence, repo_color),
    )
    line.append(f"{dt_local:%H:%M}  ", style="dim")
    line.append(f"{commit.short_id.ljust(sha_width)}  ", style=GOLD)
    line.append(
        entry.repo.ljust(repo_width),
        style=f"bold {repo_color}".strip() or None,
    )
    line.append("  ")
    line.append(commit.subject)
    if show_tags:
        tags = commit_tag_view(commit).tags
        if tags:
            line.append("  · ", style="dim")
            line.append_text(inline_tag_text(tags))
    if commit.author_name:
        line.append(f"  · {commit.author_name}", style="dim")
    return line


def _print_full_commit(
    console: Console,
    entry: AggregatedCommitWire,
    colors: dict[str, str],
    dt_local: datetime,
    show_tags: bool,
) -> None:
    for line in _full_commit_lines(entry, colors, dt_local, show_tags=show_tags):
        console.print(line, soft_wrap=True)


def _full_commit_lines(
    entry: AggregatedCommitWire,
    colors: dict[str, str],
    dt_local: datetime,
    show_tags: bool,
) -> tuple[Text, ...]:
    commit = entry.commit
    repo_color = colors.get(entry.repo, "")
    lines: list[Text] = []

    header = Text("   ")
    header.append("▌ ", style=repo_color or None)
    header.append(entry.repo, style=f"bold {repo_color}".strip() or None)
    header.append("  ")
    header.append(commit.subject, style="bold")
    lines.append(header)

    tag_view = commit_tag_view(commit) if show_tags else None
    body = (tag_view.body if tag_view is not None else commit.body).strip("\n")
    if body:
        for line in body.splitlines():
            lines.append(Text(f"     {line}", style="dim"))
    if tag_view is not None and tag_view.tags:
        lines.extend(full_tag_lines(tag_view.tags))

    author = commit.author_name
    if commit.author_email:
        author = f"{author} <{commit.author_email}>" if author else commit.author_email
    footer = Text("     ")
    footer.append(
        f"{commit.short_id} · {author} · {dt_local:%H:%M} · {_relative_age(dt_local)}",
        style="dim",
    )
    footer.append(f" · {_presence_label(commit.presence)}", style="dim")
    lines.append(footer)
    return tuple(lines)


def _print_warnings(console: Console, result: VcsLogResult) -> None:
    if not result.warnings:
        return
    console.print()
    for warning in result.warnings:
        console.print(Text(f"  ⚠ {warning}", style="dim"))


def _oneline_tag_suffix(entry: AggregatedCommitWire) -> str:
    tags = commit_tag_view(entry.commit).tags
    if not tags:
        return ""
    return f" [{_format_tags(tags, separator=' ')}]"


def _format_tags(tags: tuple[tuple[str, str], ...], *, separator: str) -> str:
    return separator.join(f"{key}={value}" for key, value in tags)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _presence_glyph(presence: CommitPresence) -> str:
    return {
        "synced": "●",
        "remote_only": "↓",
        "local_only": "↑",
        "unknown": "·",
    }.get(presence, "·")


def _presence_style(presence: CommitPresence, repo_color: str) -> str | None:
    if presence == "remote_only":
        return INCOMING
    if presence == "local_only":
        return UNPUSHED
    if presence == "unknown":
        return "dim"
    return repo_color or None


def _presence_label(presence: CommitPresence) -> str:
    return {
        "synced": "synced",
        "remote_only": "GitHub-only",
        "local_only": "unpushed",
        "unknown": "unknown",
    }.get(presence, "unknown")


def _remote_state(result: VcsLogResult, repo_name: str) -> RepoRemoteState:
    for state in result.remote_states:
        if state.name == repo_name:
            return state
    return RepoRemoteState(repo_name, None, 0, 0, False)


def _remote_summary(states: tuple[RepoRemoteState, ...]) -> str:
    known = [state for state in states if state.remote_ref]
    if not known:
        return ""
    refs = {state.remote_ref for state in known}
    if len(refs) == 1:
        ref_text = next(iter(refs)) or ""
    else:
        ref_text = ", ".join(f"{state.name}={state.remote_ref}" for state in known)
    fetch_text = _remote_fetch_summary(known)
    return f"vs {ref_text} · {fetch_text}"


def _remote_fetch_summary(states: list[RepoRemoteState]) -> str:
    if all(state.fetched for state in states):
        return "fetched"
    if all(state.fetched_at is not None and not state.fetched for state in states):
        fetched_at = min(
            state.fetched_at for state in states if state.fetched_at is not None
        )
        return f"fetched {_format_fetch_age(fetched_at)}"
    if all(state.fetched or state.fetched_at is not None for state in states):
        return "fresh"
    if any(state.fetched or state.fetched_at is not None for state in states):
        return "partly fetched"
    return "not fetched"


def _format_fetch_age(fetched_at: float) -> str:
    age_seconds = max(0, int(_now_epoch() - fetched_at))
    if age_seconds < 60:
        return f"{age_seconds}s ago"
    minutes = age_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _repo_colors(result: VcsLogResult) -> dict[str, str]:
    """Assign a stable accent color to each repo in resolved order."""
    return repo_colors(result.repos)


def _ordered_commits(
    result: VcsLogResult, *, reverse: bool
) -> tuple[AggregatedCommitWire, ...]:
    commits = tuple(result.commits)
    return tuple(reversed(commits)) if reverse else commits


def _filter_summary(filters: CommitFilters) -> str:
    parts: list[str] = []
    if filters.since is not None:
        parts.append(f"since {_format_bound(filters.since)}")
    if filters.until is not None:
        parts.append(f"until {_format_bound(filters.until)}")
    if filters.authors:
        parts.append(f"author {' or '.join(filters.authors)}")
    return " · ".join(parts)


def _empty_message(filters: CommitFilters) -> str:
    summary = _filter_summary(filters).replace(" · ", ", ")
    if not summary:
        return "No commits found"
    return f"No commits found ({summary})"


def _format_bound(timestamp: int) -> str:
    dt_local = _to_local(timestamp)
    if (
        dt_local.hour,
        dt_local.minute,
        dt_local.second,
        dt_local.microsecond,
    ) == (0, 0, 0, 0):
        return f"{dt_local:%Y-%m-%d}"
    if dt_local.second or dt_local.microsecond:
        return f"{dt_local:%Y-%m-%dT%H:%M:%S}"
    return f"{dt_local:%Y-%m-%dT%H:%M}"


def _relative_age(dt_local: datetime) -> str:
    from sase.notifications.models import format_relative_time

    return format_relative_time(dt_local.isoformat(timespec="seconds"))


def _to_local(timestamp: int) -> datetime:
    from sase.core.time import to_local

    return to_local(datetime.fromtimestamp(timestamp, tz=UTC))


def _local_now() -> datetime:
    from sase.core.time import local_now

    return local_now()


def _now_epoch() -> float:
    return time.time()


def _day_label(dt_local: datetime, now_local: datetime) -> str:
    day = dt_local.date()
    today = now_local.date()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    if day.year == today.year:
        return f"{dt_local:%b} {dt_local.day}"
    return f"{dt_local:%b} {dt_local.day}, {dt_local.year}"


def build_pretty_legend(
    result: VcsLogResult,
    *,
    filters: CommitFilters | None = None,
) -> Text:
    """Build the shared Rich legend used by CLI and interactive timelines."""
    return _legend(
        result,
        tuple(result.commits),
        _repo_colors(result),
        filters or CommitFilters(),
    )


def build_timeline_day(
    timestamp: int,
    *,
    now_local: datetime | None = None,
) -> tuple[str, Text]:
    """Return the grouping key and banner for a commit timestamp."""
    label = _day_label(_to_local(timestamp), now_local or _local_now())
    return label, _day_header(label)


def build_timeline_commit(
    entry: AggregatedCommitWire,
    result: VcsLogResult,
    *,
    show_tags: bool = True,
) -> Text:
    """Build one shared pretty timeline row for an aggregated commit."""
    commits = tuple(result.commits)
    repo_width = max((len(item.repo) for item in commits), default=len(entry.repo))
    sha_width = max(
        (len(item.commit.short_id) for item in commits),
        default=len(entry.commit.short_id),
    )
    return _commit_line(
        entry,
        _repo_colors(result),
        repo_width,
        sha_width,
        _to_local(entry.commit.timestamp),
        show_tags,
    )


__all__ = [
    "build_pretty_legend",
    "build_timeline_commit",
    "build_timeline_day",
    "render",
]
