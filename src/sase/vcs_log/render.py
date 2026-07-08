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
from datetime import UTC, datetime, timedelta
from typing import TextIO

from rich.console import Console
from rich.text import Text

from sase.core.vcs_log_wire import AggregatedCommitWire, CommitPresence
from sase.vcs_log.models import CommitFilters, LogRepo, RepoRemoteState, VcsLogResult
from sase.vcs_log._style import GOLD, INCOMING, UNPUSHED, make_console, repo_colors

_HEADER_WIDTH = 56


def render(
    result: VcsLogResult,
    *,
    fmt: str,
    color: str,
    out: TextIO | None = None,
    limit: int = 20,
    filters: CommitFilters | None = None,
    reverse: bool = False,
) -> None:
    """Render *result* in the requested format to *out* (default stdout)."""
    stream = out if out is not None else sys.stdout
    filters = filters or CommitFilters()
    commits = _ordered_commits(result, reverse=reverse)
    if fmt == "json":
        stream.write(_render_json(result, commits, limit, filters, reverse))
        return
    if fmt == "oneline":
        stream.write(_render_oneline(commits))
        return
    if fmt == "full":
        _render_full(result, commits, color=color, out=stream, filters=filters)
        return
    _render_pretty(result, commits, color=color, out=stream, filters=filters)


# ---------------------------------------------------------------------------
# json
# ---------------------------------------------------------------------------


def _render_json(
    result: VcsLogResult,
    commits: tuple[AggregatedCommitWire, ...],
    limit: int,
    filters: CommitFilters,
    reverse: bool,
) -> str:
    states = {state.name: state for state in result.remote_states}
    payload = {
        "repos": [_repo_json(repo, states) for repo in result.repos],
        "commits": [
            {
                "repo": entry.repo,
                "full_id": entry.commit.full_id,
                "short_id": entry.commit.short_id,
                "author_name": entry.commit.author_name,
                "author_email": entry.commit.author_email,
                "timestamp": entry.commit.timestamp,
                "subject": entry.commit.subject,
                "presence": entry.commit.presence,
            }
            for entry in commits
        ],
        "query": {
            "limit": limit,
            "since": filters.since,
            "until": filters.until,
            "authors": list(filters.authors),
            "reverse": reverse,
        },
        "warnings": list(result.warnings),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


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
    }


# ---------------------------------------------------------------------------
# oneline
# ---------------------------------------------------------------------------


def _render_oneline(commits: tuple[AggregatedCommitWire, ...]) -> str:
    if not commits:
        return ""
    repo_width = max(len(entry.repo) for entry in commits)
    sha_width = max(len(entry.commit.short_id) for entry in commits)
    lines = [
        f"{_presence_glyph(entry.commit.presence)} "
        f"{entry.commit.short_id.ljust(sha_width)} "
        f"{entry.repo.ljust(repo_width)} {entry.commit.subject}"
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
            _commit_line(entry, colors, repo_width, sha_width, dt_local),
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
        _print_full_commit(console, entry, colors, dt_local)
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
    if commit.author_name:
        line.append(f"  · {commit.author_name}", style="dim")
    return line


def _print_full_commit(
    console: Console,
    entry: AggregatedCommitWire,
    colors: dict[str, str],
    dt_local: datetime,
) -> None:
    commit = entry.commit
    repo_color = colors.get(entry.repo, "")

    header = Text("   ")
    header.append("▌ ", style=repo_color or None)
    header.append(entry.repo, style=f"bold {repo_color}".strip() or None)
    header.append("  ")
    header.append(commit.subject, style="bold")
    console.print(header, soft_wrap=True)

    body = commit.body.strip("\n")
    if body:
        for line in body.splitlines():
            console.print(Text(f"     {line}", style="dim"), soft_wrap=True)

    author = commit.author_name
    if commit.author_email:
        author = f"{author} <{commit.author_email}>" if author else commit.author_email
    footer = Text("     ")
    footer.append(
        f"{commit.short_id} · {author} · {dt_local:%H:%M} · {_relative_age(dt_local)}",
        style="dim",
    )
    footer.append(f" · {_presence_label(commit.presence)}", style="dim")
    console.print(footer, soft_wrap=True)


def _print_warnings(console: Console, result: VcsLogResult) -> None:
    if not result.warnings:
        return
    console.print()
    for warning in result.warnings:
        console.print(Text(f"  ⚠ {warning}", style="dim"))


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
    if all(state.fetched for state in known):
        fetch_text = "fetched"
    elif any(state.fetched for state in known):
        fetch_text = "partly fetched"
    else:
        fetch_text = "not fetched"
    return f"vs {ref_text} · {fetch_text}"


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


__all__ = ["render"]
