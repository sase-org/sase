"""Renderers for ``sase vcs log`` — ``pretty``, ``oneline``, and ``json``.

Mirrors the dual-output + ``--color`` contract used by ``sase plan
search``: the JSON branch returns a plain string (no Rich), and the
colored output routes through a ``_make_console`` factory that honors
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

from sase.core.vcs_log_wire import AggregatedCommitWire
from sase.vcs_log.models import VcsLogResult

#: House gold accent used for short SHAs (matches the CLI convention).
_GOLD = "#D7AF5F"

#: Deterministic per-repo accent palette, cycled in resolved-repo order
#: (primary first, then linked sorted by name, then SDD).
_REPO_PALETTE = (
    "#87D7FF",
    "#5FD75F",
    "#D7AF5F",
    "#AF87FF",
    "#5FD7D7",
    "#D787AF",
)

_HEADER_WIDTH = 56


def _make_console(
    color: str, *, file: TextIO | None = None, width: int | None = None
) -> Console:
    """Build a ``rich`` console honoring the ``--color`` mode.

    ``auto`` defers to ``rich`` (color only on a TTY, and never when
    ``NO_COLOR`` is set); ``always`` forces color even under ``NO_COLOR``;
    ``never`` strips it.
    """
    kwargs: dict[str, object] = {"file": file or sys.stdout}
    if width is not None:
        kwargs["width"] = width
    if color == "always":
        kwargs.update(force_terminal=True, no_color=False, color_system="standard")
    elif color == "never":
        kwargs.update(no_color=True)
    return Console(**kwargs)  # type: ignore[arg-type]


def render(
    result: VcsLogResult,
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


def _render_json(result: VcsLogResult) -> str:
    payload = {
        "repos": [
            {"name": repo.name, "kind": repo.kind, "path": repo.path}
            for repo in result.repos
        ],
        "commits": [
            {
                "repo": entry.repo,
                "full_id": entry.commit.full_id,
                "short_id": entry.commit.short_id,
                "author_name": entry.commit.author_name,
                "author_email": entry.commit.author_email,
                "timestamp": entry.commit.timestamp,
                "subject": entry.commit.subject,
            }
            for entry in result.commits
        ],
        "warnings": list(result.warnings),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# oneline
# ---------------------------------------------------------------------------


def _render_oneline(result: VcsLogResult) -> str:
    if not result.commits:
        return ""
    repo_width = max(len(entry.repo) for entry in result.commits)
    sha_width = max(len(entry.commit.short_id) for entry in result.commits)
    lines = [
        f"{entry.commit.short_id.ljust(sha_width)} "
        f"{entry.repo.ljust(repo_width)} {entry.commit.subject}"
        for entry in result.commits
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# pretty
# ---------------------------------------------------------------------------


def _render_pretty(result: VcsLogResult, *, color: str, out: TextIO) -> None:
    console = _make_console(color, file=out)
    colors = _repo_colors(result)

    if not result.commits:
        console.print(Text("No commits found", style="dim"))
        _print_warnings(console, result)
        return

    console.print(_legend(result, colors))
    console.print()

    repo_width = max(len(entry.repo) for entry in result.commits)
    sha_width = max(len(entry.commit.short_id) for entry in result.commits)
    now_local = _local_now()
    current_day: str | None = None
    for entry in result.commits:
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


def _legend(result: VcsLogResult, colors: dict[str, str]) -> Text:
    counts: dict[str, int] = {}
    for entry in result.commits:
        counts[entry.repo] = counts.get(entry.repo, 0) + 1

    text = Text("  ")
    for i, repo in enumerate(result.repos):
        if i:
            text.append("  ·  ", style="dim")
        style = colors.get(repo.name, "")
        text.append(repo.name, style=f"bold {style}".strip())
        count = counts.get(repo.name, 0)
        text.append(f" ({count})", style="dim")
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
    line.append("● ", style=repo_color or None)
    line.append(f"{dt_local:%H:%M}  ", style="dim")
    line.append(f"{commit.short_id.ljust(sha_width)}  ", style=_GOLD)
    line.append(
        entry.repo.ljust(repo_width),
        style=f"bold {repo_color}".strip() or None,
    )
    line.append("  ")
    line.append(commit.subject)
    if commit.author_name:
        line.append(f"  · {commit.author_name}", style="dim")
    return line


def _print_warnings(console: Console, result: VcsLogResult) -> None:
    if not result.warnings:
        return
    console.print()
    for warning in result.warnings:
        console.print(Text(f"  ⚠ {warning}", style="dim"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _repo_colors(result: VcsLogResult) -> dict[str, str]:
    """Assign a stable accent color to each repo in resolved order."""
    colors: dict[str, str] = {}
    for i, repo in enumerate(result.repos):
        colors.setdefault(repo.name, _REPO_PALETTE[i % len(_REPO_PALETTE)])
    return colors


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
