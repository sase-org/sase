"""Rich ``sase vcs log`` renderers — ``pretty`` and ``full``.

Colored output routes through the ``make_console`` factory so it honors
``auto``/``always``/``never`` plus ``NO_COLOR`` and TTY detection, matching
the dual-output + ``--color`` contract used by ``sase plan search``. The
legend, day banners, and commit rows are also reused by the interactive
ACE timelines through :mod:`sase.vcs_log.render`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TextIO

from rich.console import Console
from rich.text import Text

from sase.core.vcs_log_facade import merge_summary
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.vcs_log.models import CommitFilters, VcsLogResult
from sase.vcs_log._render_util import (
    build_commit_presence,
    day_label,
    empty_message,
    filter_summary,
    local_now,
    presence_glyph,
    presence_label,
    presence_style,
    relative_age,
    remote_state,
    remote_summary,
    to_local,
)
from sase.vcs_log._style import GOLD, MERGE, make_console, repo_colors
from sase.vcs_log._tag_style import full_tag_lines, inline_tag_text
from sase.vcs_log.tags import commit_tag_view

_HEADER_WIDTH = 56


def render_pretty(
    result: VcsLogResult,
    commits: tuple[AggregatedCommitWire, ...],
    *,
    color: str,
    out: TextIO,
    filters: CommitFilters,
    show_tags: bool,
) -> None:
    console = make_console(color, file=out)
    colors = repo_colors(result.repos)

    if not commits:
        console.print(Text(empty_message(filters), style="dim"))
        _print_warnings(console, result)
        return

    console.print(legend(result, commits, colors, filters), soft_wrap=True)
    console.print()

    repo_width = max(len(entry.repo) for entry in commits)
    sha_width = max(len(entry.commit.short_id) for entry in commits)
    merge_column = _has_merge(commits)
    now_local = local_now()
    current_day: str | None = None
    for entry in commits:
        dt_local = to_local(entry.commit.timestamp)
        day = day_label(dt_local, now_local)
        if day != current_day:
            console.print(day_header(day), soft_wrap=True)
            current_day = day
        console.print(
            commit_line(
                entry,
                colors,
                repo_width,
                sha_width,
                dt_local,
                show_tags=show_tags,
                merge_column=merge_column,
            ),
            soft_wrap=True,
        )

    _print_warnings(console, result)


def render_full(
    result: VcsLogResult,
    commits: tuple[AggregatedCommitWire, ...],
    *,
    color: str,
    out: TextIO,
    filters: CommitFilters,
    show_tags: bool,
) -> None:
    console = make_console(color, file=out)
    colors = repo_colors(result.repos)

    if not commits:
        console.print(Text(empty_message(filters), style="dim"))
        _print_warnings(console, result)
        return

    console.print(legend(result, commits, colors, filters), soft_wrap=True)
    console.print()

    now_local = local_now()
    current_day: str | None = None
    for i, entry in enumerate(commits):
        dt_local = to_local(entry.commit.timestamp)
        day = day_label(dt_local, now_local)
        if day != current_day:
            console.print(day_header(day), soft_wrap=True)
            current_day = day
        _print_full_commit(console, entry, colors, dt_local, show_tags=show_tags)
        if i != len(commits) - 1:
            console.print()

    _print_warnings(console, result)


def legend(
    result: VcsLogResult,
    commits: tuple[AggregatedCommitWire, ...],
    colors: dict[str, str],
    filters: CommitFilters,
    *,
    visible_repos_only: bool = False,
    show_filter_summary: bool = True,
) -> Text:
    counts: dict[str, int] = {}
    for entry in commits:
        counts[entry.repo] = counts.get(entry.repo, 0) + 1

    text = Text("  ")
    visible_names = frozenset(counts)
    repos = (
        tuple(repo for repo in result.repos if repo.name in visible_names)
        if visible_repos_only
        else result.repos
    )
    for i, repo in enumerate(repos):
        if i:
            text.append("  ·  ", style="dim")
        style = colors.get(repo.name, "")
        text.append(repo.name, style=f"bold {style}".strip())
        count = counts.get(repo.name, 0)
        text.append(f" ({count})", style="dim")
        state = remote_state(result, repo.name)
        if state.remote_ref is not None or state.ahead or state.behind:
            text.append(f"  ↑{state.ahead} ↓{state.behind}", style="dim")
    summary = filter_summary(filters) if show_filter_summary else ""
    if summary:
        text.append("  ·  ", style="dim")
        text.append(summary, style="dim")
    text.append("  ·  ", style="dim")
    text.append_text(build_commit_presence("local_only"))
    text.append("  ", style="dim")
    text.append_text(build_commit_presence("remote_only"))
    text.append("  ", style="dim")
    text.append_text(build_commit_presence("synced", repo_color="dim"))
    if _has_merge(commits):
        text.append("  ", style="dim")
        text.append("◆", style=MERGE)
        text.append(" merge", style="dim")
    remote_states = (
        tuple(state for state in result.remote_states if state.name in visible_names)
        if visible_repos_only
        else result.remote_states
    )
    summary_text = remote_summary(remote_states)
    if summary_text:
        text.append("\n  ", style="dim")
        text.append(summary_text, style="dim")
    return text


def day_header(day: str) -> Text:
    text = Text("  ")
    label = f"── {day} "
    text.append(label, style="bold")
    pad = max(3, _HEADER_WIDTH - len(label))
    text.append("─" * pad, style="dim")
    return text


def commit_line(
    entry: AggregatedCommitWire,
    colors: dict[str, str],
    repo_width: int,
    sha_width: int,
    dt_local: datetime,
    show_tags: bool,
    show_author: bool = True,
    merge_column: bool = False,
) -> Text:
    commit = entry.commit
    repo_color = colors.get(entry.repo, "")

    line = Text("   ")
    line.append(
        f"{presence_glyph(commit.presence)} ",
        style=presence_style(commit.presence, repo_color),
    )
    line.append(f"{dt_local:%H:%M}  ", style="dim")
    line.append(f"{commit.short_id.ljust(sha_width)}  ", style=GOLD)
    line.append(
        _single_line(entry.repo).ljust(repo_width),
        style=f"bold {repo_color}".strip() or None,
    )
    line.append("  ")
    if merge_column:
        if commit.is_merge:
            line.append("◆ ", style=MERGE)
        else:
            line.append("  ")
    line.append_text(_timeline_subject_text(commit))
    if show_tags:
        tags = commit_tag_view(commit).tags
        if tags:
            line.append("  · ", style="dim")
            line.append_text(inline_tag_text(tags))
    if show_author and commit.author_name:
        line.append(f"  · {_single_line(commit.author_name)}", style="dim")
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
    if commit.is_merge:
        header.append("◆ ", style=MERGE)
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
        f"{commit.short_id} · {author} · {dt_local:%H:%M} · {relative_age(dt_local)}",
        style="dim",
    )
    footer.append(f" · {presence_label(commit.presence)}", style="dim")
    lines.append(footer)
    if commit.is_merge:
        short_width = len(commit.short_id)
        parent_ids = "  ".join(
            parent_id[:short_width] for parent_id in commit.parent_ids
        )
        lines.append(Text(f"     parents  {parent_ids}", style="dim"))
    return tuple(lines)


def _print_warnings(console: Console, result: VcsLogResult) -> None:
    if not result.warnings:
        return
    console.print()
    for warning in result.warnings:
        console.print(Text(f"  ⚠ {warning}", style="dim"))


def _single_line(value: str) -> str:
    """Return display text that cannot add a physical timeline row."""
    return value.replace("\r", " ").replace("\n", " ")


def _has_merge(commits: tuple[AggregatedCommitWire, ...]) -> bool:
    return any(entry.commit.is_merge for entry in commits)


def _timeline_subject_text(commit: VcsCommitWire) -> Text:
    """Return the pretty/timeline subject, condensing recognized PR merges."""
    if commit.is_merge:
        summary = merge_summary(commit.subject, commit.body)
        if (
            summary is not None
            and summary.kind == "pull_request"
            and summary.reference
            and summary.headline
            and (headline := summary.headline.strip())
        ):
            text = Text()
            text.append(f"#{summary.reference}", style=MERGE)
            text.append(f"  {_single_line(headline)}")
            return text
    return Text(_single_line(commit.subject))
