"""``sase prompt search`` — cross-store search over SDD + local prompts.

This is the CLI surface: argument validation, color resolution, the call into
the pure :func:`~sase.prompt.search.engine.search_prompts` engine, and the
``compact`` renderer. The ``json`` and ``full`` renderers arrive in a later
phase; the parser already advertises them so the command contract is stable.

The ``compact`` format groups hits by source (SDD before local), prints a
badge + locator + date + path/status line per hit, a dim indented snippet that
highlights the matched term (or names the field that matched, so the user
always sees *why* a hit matched), and a footer that makes truncation explicit.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text

from sase.prompt.render import (
    format_search_date,
    highlight_match,
    source_badge,
)
from sase.prompt.search.dates import PromptSearchDateError, parse_search_date
from sase.prompt.search.engine import search_prompts
from sase.prompt.search.model import (
    PromptHit,
    PromptSearchMatch,
    PromptSearchResult,
    PromptSource,
)
from sase.prompt.search.sources import collect_prompt_hits

# Longest single snippet line shown under a hit, centered on the match.
_SNIPPET_CHARS = 96
# Source render order: SDD always groups above local (the ranking's priority).
_SOURCE_ORDER: tuple[PromptSource, ...] = (PromptSource.SDD, PromptSource.LOCAL)
# Fields whose match is best illustrated by the body snippet itself.
_BODY_FIELDS = frozenset({"title", "body"})


def handle_prompt_search(args: argparse.Namespace) -> None:
    """Validate arguments, run the search, and render the requested format."""
    query: str = getattr(args, "query", "") or ""
    if not query.strip():
        print("Error: search query cannot be empty", file=sys.stderr)
        sys.exit(2)

    sources = _resolve_sources(getattr(args, "source", "all"))
    after = _resolve_date(getattr(args, "after", None))
    before = _resolve_date(getattr(args, "before", None))
    tags = getattr(args, "tag", None) or []
    cancelled_only = bool(getattr(args, "cancelled", False))
    limit = _resolve_limit(getattr(args, "limit", 20))
    fmt: str = getattr(args, "format", "compact") or "compact"

    hits = collect_prompt_hits(sources, Path.cwd())
    result = search_prompts(
        query,
        hits,
        sources=sources,
        after=after,
        before=before,
        tags=tags,
        cancelled_only=cancelled_only,
        limit=limit,
    )

    match fmt:
        case "compact":
            _render_compact(result, use_color=_resolve_color(args))
        case "json" | "full":
            # Implemented in the json + full renderer phase; the parser already
            # accepts these so the command contract does not shift later.
            print(
                f"sase prompt search: --format {fmt} is not available yet;"
                " use --format compact.",
                file=sys.stderr,
            )
            sys.exit(2)
        case _:
            print(f"sase prompt search: unknown format: {fmt}", file=sys.stderr)
            sys.exit(2)


# ---------------------------------------------------------------------------
# Argument resolution
# ---------------------------------------------------------------------------


def _resolve_sources(choice: str | None) -> list[PromptSource]:
    """Map the ``--source`` choice to the concrete source set to search."""
    normalized = (choice or "all").lower()
    if normalized == "sdd":
        return [PromptSource.SDD]
    if normalized == "local":
        return [PromptSource.LOCAL]
    return [PromptSource.SDD, PromptSource.LOCAL]


def _resolve_date(value: str | None) -> str | None:
    """Parse a ``--after``/``--before`` value, exiting ``2`` on a bad date."""
    if value is None:
        return None
    try:
        return parse_search_date(value)
    except PromptSearchDateError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


def _resolve_limit(value: object) -> int:
    """Return the parsed ``--limit`` int; ``0`` (or less) is unlimited."""
    return value if isinstance(value, int) else 20


def _resolve_color(args: argparse.Namespace) -> bool:
    """Resolve ``--color`` to a boolean, honoring ``auto`` (TTY + ``NO_COLOR``)."""
    choice = getattr(args, "color", "auto") or "auto"
    if choice == "always":
        return True
    if choice == "never":
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


# ---------------------------------------------------------------------------
# Compact renderer
# ---------------------------------------------------------------------------


def _render_compact(result: PromptSearchResult, *, use_color: bool) -> None:
    """Print the grouped, highlighted compact view (default format)."""
    console = _make_console(use_color)
    if result.total == 0:
        console.print(f'No prompts match "{result.query}".', soft_wrap=True)
        return

    grouped = _group_by_source(result.matches)
    first = True
    for source in _SOURCE_ORDER:
        matches = grouped.get(source, [])
        if not matches:
            continue
        if not first:
            console.print()
        first = False
        console.print(_group_header(source, len(matches)), soft_wrap=True)
        for match in matches:
            console.print(_hit_line(match, result.query), soft_wrap=True)
            snippet = _snippet_line(match, result.query)
            if snippet is not None:
                console.print(snippet, soft_wrap=True)

    console.print()
    console.print(_footer(result), soft_wrap=True)


def _make_console(use_color: bool) -> Console:
    """Build a Console that emits ANSI iff *use_color*, regardless of the TTY."""
    return Console(
        force_terminal=use_color,
        no_color=not use_color,
        highlight=False,
    )


def _group_by_source(
    matches: tuple[PromptSearchMatch, ...],
) -> dict[PromptSource, list[PromptSearchMatch]]:
    """Bucket ranked matches by source, preserving their ranked order."""
    grouped: dict[PromptSource, list[PromptSearchMatch]] = {}
    for match in matches:
        grouped.setdefault(match.hit.source, []).append(match)
    return grouped


def _group_header(source: PromptSource, shown: int) -> Text:
    """Return the dim ``── <label> (<shown>) ──`` group header."""
    label = "SDD prompts" if source is PromptSource.SDD else "Local history"
    return Text(f"── {label} ({shown}) ──", style="dim")


def _hit_line(match: PromptSearchMatch, query: str) -> Text:
    """Return line 1: ``<badge> <locator>  <date>  <path-or-status>``.

    The locator is highlighted only when the id is one of the matched fields,
    so the highlight always marks a genuine match.
    """
    hit = match.hit
    line = Text()
    line.append_text(source_badge(hit.source))
    line.append("  ")
    if "id" in match.matched_fields:
        line.append_text(highlight_match(hit.id, query, base_style="cyan"))
    else:
        line.append(hit.id, style="cyan")
    line.append("  ")
    line.append(format_search_date(hit.date), style="dim")
    suffix = _line_suffix(hit)
    if suffix is not None:
        line.append("  ")
        line.append_text(suffix)
    return line


def _line_suffix(hit: PromptHit) -> Text | None:
    """Return the trailing path (SDD) or launched/cancelled status (local)."""
    text = Text()
    if hit.source is PromptSource.SDD:
        if hit.path:
            text.append(hit.path, style="dim")
        if hit.also_in_local:
            if text.plain:
                text.append("  ")
            text.append("also in local history", style="dim")
    elif hit.cancelled:
        text.append("cancelled", style="magenta")
    else:
        text.append("launched", style="green")
    return text if text.plain else None


def _snippet_line(match: PromptSearchMatch, query: str) -> Text | None:
    """Return line 2: a highlighted body snippet, or ``field: "value"``."""
    field, value = _why_matched(match, query)
    if not value:
        return None
    snippet = _single_line_snippet(value, query)
    if not snippet:
        return None

    line = Text("  ")
    if field in _BODY_FIELDS:
        line.append_text(highlight_match(snippet, query, base_style="dim"))
        return line
    line.append(f"{field}: ", style="dim")
    line.append('"', style="dim")
    line.append_text(highlight_match(snippet, query, base_style="dim"))
    line.append('"', style="dim")
    return line


def _why_matched(match: PromptSearchMatch, query: str) -> tuple[str, str]:
    """Return the ``(label, value)`` best explaining why *match* matched.

    A title/body match is illustrated by the body itself; otherwise the first
    non-body matched field is named (``path``/``plan``/``tag``) so the user sees
    the reason even when the match is off-screen of the body. An id-only match
    needs no second line — the locator is already highlighted on line 1.
    """
    hit = match.hit
    if any(field in _BODY_FIELDS for field in match.matched_fields):
        return "body", hit.text or hit.title
    lowered = query.lower()
    for field in match.matched_fields:
        if field == "path":
            return "path", hit.path or ""
        if field == "plan":
            return "plan", hit.plan or ""
        if field == "tags":
            tag = next(
                (t for t in hit.tags if lowered in t.lower()),
                hit.tags[0] if hit.tags else "",
            )
            return "tag", tag
    return "", ""


def _single_line_snippet(
    value: str, query: str, max_chars: int = _SNIPPET_CHARS
) -> str:
    """Return a single line of *value* centered on *query*, bounded to width.

    The first non-blank line containing the query is preferred; long lines are
    windowed around the match with ellipses so the matched term stays visible.
    """
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""

    lowered_query = query.lower()
    line = next((ln for ln in lines if lowered_query in ln.lower()), lines[0])
    if len(line) <= max_chars:
        return line

    index = line.lower().find(lowered_query)
    if index < 0:
        return line[: max_chars - 1].rstrip() + "…"
    end = min(len(line), max(index + len(query), index + max_chars // 2))
    start = max(0, end - max_chars)
    end = min(len(line), start + max_chars)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return f"{prefix}{line[start:end].strip()}{suffix}"


def _footer(result: PromptSearchResult) -> Text:
    """Return the count footer; the ``showing`` clause appears when truncated."""
    sdd = result.count_for(PromptSource.SDD)
    local = result.count_for(PromptSource.LOCAL)
    total = result.total
    noun = "match" if total == 1 else "matches"
    text = Text(f"{total} {noun} ({sdd} SDD · {local} local)", style="dim")
    if result.count < total:
        text.append(f" · showing {result.count}", style="dim")
    return text
