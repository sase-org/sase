"""Renderers for ``sase stitch list``."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from rich.console import Console
from rich.text import Text

from sase.core.vcs_log_wire import VcsCommitWire
from sase.vcs_list.models import RepoListing, VcsListResult
from sase.vcs_log._style import GOLD, make_console, repo_colors


def render(
    result: VcsListResult,
    *,
    fmt: str,
    color: str,
    out: TextIO | None = None,
) -> None:
    """Render *result* in the requested format to *out* (default stdout)."""
    stream = out if out is not None else sys.stdout
    if fmt == "json":
        stream.write(_render_json(result))
        return
    if fmt == "oneline":
        stream.write(_render_oneline(result))
        return
    _render_pretty(result, color=color, out=stream)


# ---------------------------------------------------------------------------
# json
# ---------------------------------------------------------------------------


def _render_json(result: VcsListResult) -> str:
    payload = {
        "repos": [_repo_json(listing) for listing in result.repos],
        "totals": {
            "contributors": len(result.totals.contributors),
            "latest_activity": result.totals.latest_activity,
            "repos": result.totals.repo_count,
            "total_commits": result.totals.total_commits,
        },
        "warnings": list(result.warnings),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _repo_json(listing: RepoListing) -> dict[str, object]:
    stats = listing.stats
    return {
        "branch": stats.branch if stats else None,
        "contributor_count": len(stats.contributors) if stats else None,
        "contributors": list(stats.contributors) if stats else [],
        "description": listing.description,
        "description_source": listing.description_source,
        "dirty": stats.dirty if stats else None,
        "error": listing.error,
        "kind": listing.repo.kind,
        "last_commit": _commit_json(stats.last_commit) if stats else None,
        "name": listing.repo.name,
        "path": listing.repo.path,
        "total_commits": stats.total_commits if stats else None,
    }


def _commit_json(commit: VcsCommitWire | None) -> dict[str, object] | None:
    return asdict(commit) if commit is not None else None


# ---------------------------------------------------------------------------
# oneline
# ---------------------------------------------------------------------------


def _render_oneline(result: VcsListResult) -> str:
    if not result.repos:
        return _warnings_text(result)
    name_width = max(len(listing.repo.name) for listing in result.repos)
    kind_width = max(len(listing.repo.kind) for listing in result.repos)
    lines: list[str] = []
    for listing in result.repos:
        stats = listing.stats
        commits = f"{stats.total_commits}c" if stats else "-c"
        contributors = f"{len(stats.contributors)}a" if stats else "-a"
        age = (
            _relative_age(stats.last_commit.timestamp)
            if stats and stats.last_commit
            else "-"
        )
        branch = stats.branch if stats and stats.branch else "-"
        description = listing.description or "-"
        error = f"  [{listing.error}]" if listing.error else ""
        lines.append(
            f"{listing.repo.name.ljust(name_width)}  "
            f"{listing.repo.kind.ljust(kind_width)}  "
            f"{commits.rjust(6)}  {contributors.rjust(4)}  "
            f"{age.ljust(8)}  {branch}  {description}{error}"
        )
    text = "\n".join(lines) + "\n"
    return text + _warnings_text(result)


def _warnings_text(result: VcsListResult) -> str:
    if not result.warnings:
        return ""
    return "".join(f"WARNING: {warning}\n" for warning in result.warnings)


# ---------------------------------------------------------------------------
# pretty
# ---------------------------------------------------------------------------


def _render_pretty(result: VcsListResult, *, color: str, out: TextIO) -> None:
    console = make_console(color, file=out)
    colors = repo_colors(
        result.color_repos or tuple(listing.repo for listing in result.repos)
    )

    if not result.repos:
        console.print(Text("No repositories found", style="dim"))
        _print_warnings(console, result)
        return

    console.print(_summary(result))
    console.print()

    name_width = max(len(listing.repo.name) for listing in result.repos)
    for index, listing in enumerate(result.repos):
        if index:
            console.print()
        _print_listing(console, listing, colors, name_width)

    _print_warnings(console, result)


def _summary(result: VcsListResult) -> Text:
    totals = result.totals
    text = Text("  ")
    text.append("Constellation", style="bold")
    text.append(" · ", style="dim")
    text.append(_plural(totals.repo_count, "repo"), style="dim")
    text.append(" · ", style="dim")
    text.append(_plural(totals.total_commits, "commit"), style="dim")
    text.append(" · ", style="dim")
    text.append(_plural(len(totals.contributors), "contributor"), style="dim")
    text.append(" · ", style="dim")
    text.append(f"updated {_relative_age(totals.latest_activity)}", style="dim")
    return text


def _print_listing(
    console: Console,
    listing: RepoListing,
    colors: dict[str, str],
    name_width: int,
) -> None:
    repo = listing.repo
    stats = listing.stats
    repo_color = colors.get(repo.name, "")

    header = Text("  ")
    header.append("● ", style=repo_color or None)
    header.append(repo.name.ljust(name_width), style=f"bold {repo_color}".strip())
    header.append("  ")
    header.append(repo.kind.ljust(7), style="dim")
    if stats and stats.branch:
        header.append("  ")
        header.append(stats.branch, style="dim")
    if stats and stats.dirty:
        header.append("  ✎ dirty", style="yellow")
    console.print(header, soft_wrap=True)

    console.print(
        Text(f"      {listing.description or '-'}", style="dim"), soft_wrap=True
    )

    if stats is None:
        console.print(
            Text(
                f"      stats unavailable: {listing.error or 'unknown error'}",
                style="dim",
            ),
            soft_wrap=True,
        )
        console.print(Text(f"      {_display_path(repo.path)}", style="dim"))
        return

    meta = Text("      ")
    meta.append(_plural(stats.total_commits, "commit"), style="dim")
    meta.append(" · ", style="dim")
    meta.append(_plural(len(stats.contributors), "contributor"), style="dim")
    meta.append(" · ", style="dim")
    meta.append(f"updated {_relative_age(_last_timestamp(listing))}", style="dim")
    meta.append(" · ", style="dim")
    meta.append(_display_path(repo.path), style="dim")
    console.print(meta, soft_wrap=True)

    if stats.last_commit is not None:
        commit = stats.last_commit
        line = Text("      ")
        line.append(commit.short_id, style=GOLD)
        line.append("  ")
        line.append(commit.subject)
        if commit.author_name:
            line.append(f" · {commit.author_name}", style="dim")
        console.print(line, soft_wrap=True)


def _print_warnings(console: Console, result: VcsListResult) -> None:
    if not result.warnings:
        return
    console.print()
    for warning in result.warnings:
        console.print(Text(f"  ⚠ {warning}", style="dim"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _plural(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count:,} {noun}{suffix}"


def _last_timestamp(listing: RepoListing) -> int | None:
    if listing.stats is None or listing.stats.last_commit is None:
        return None
    return listing.stats.last_commit.timestamp


def _relative_age(timestamp: int | None) -> str:
    if timestamp is None:
        return "never"
    from sase.notifications.models import format_relative_time

    dt_local = _to_local(timestamp)
    return format_relative_time(dt_local.isoformat(timespec="seconds"))


def _to_local(timestamp: int) -> datetime:
    from sase.core.time import to_local

    return to_local(datetime.fromtimestamp(timestamp, tz=UTC))


def _display_path(path: str) -> str:
    expanded = Path(path).expanduser()
    home = Path.home()
    try:
        rel = expanded.resolve(strict=False).relative_to(home)
    except ValueError:
        return str(expanded)
    return "~" if str(rel) == "." else f"~/{rel}"


__all__ = ["render"]
