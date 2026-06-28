"""Shared primitives for ``sase plugin`` Rich renderers."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

from sase.updates.incoming_commits import IncomingCommits

#: Glyphs (never color alone) for installed vs. available plugins.
_INSTALLED_GLYPH = "●"
_AVAILABLE_GLYPH = "○"
_UPDATE_GLYPH = "↑"

#: Glyphs (never color alone) for the ``show`` installed/not-installed row.
_INSTALLED_CHECK = "✓"
_NOT_INSTALLED_CROSS = "✗"

#: Result glyphs (never color alone), mirroring the ``sase update`` renderer.
_CHANGED_GLYPH = "✓"
_UNCHANGED_GLYPH = "·"

#: Placeholder for an empty cell (em dash).
_EMPTY = "—"

_BUILTIN_STYLE = "green"
_COMMUNITY_STYLE = "yellow"

_REFRESH_COMMAND = "`sase plugin list --refresh`"


def humanize_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    rest = int(seconds % 60)
    return f"{minutes}m{rest:02d}s"


def humanize_age(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h ago"
    days = int(hours // 24)
    return f"{days}d ago"


def build_incoming_commits_renderable(
    incoming: IncomingCommits | None = None,
    *,
    loading: bool = False,
) -> RenderableType:
    """Return a compact incoming-commit section for update surfaces."""
    if loading:
        text = Text()
        text.append(_UPDATE_GLYPH, style="bold cyan")
        text.append(" checking incoming commits...", style="dim")
        return text
    if incoming is None:
        return Text("")
    if incoming.source == "unavailable":
        error = incoming.error or "unknown"
        return Text(f"incoming commits unavailable ({error})", style="dim")

    lines: list[Text] = [_incoming_header(incoming.total)]
    for commit in incoming.commits:
        line = Text("  ")
        line.append(commit.short_sha, style="dim")
        line.append("  ")
        line.append(commit.subject)
        lines.append(line)
    if incoming.extra > 0:
        lines.append(Text(f"  +{incoming.extra} more…", style="dim"))
    return Group(*lines)


def _incoming_header(total: int) -> Text:
    noun = "commit" if total == 1 else "commits"
    header = Text()
    header.append(_UPDATE_GLYPH, style="bold cyan")
    header.append(f" {total} incoming {noun}", style="cyan")
    return header
