"""Rich renderers for ``sase plan search`` (Phase 5).

Turns the ranked :class:`~sase.plan_search.model.PlanSearchMatch` results into
the three human/agent formats the design promises beyond ``json``:

* ``compact`` — a colored, source-grouped listing (REPO above LOCAL), each plan
  shown with a status icon, a colored kind label, a relative path, a title, and
  a highlighted snippet of the matched line (the snippet logic is ported from
  the bead search renderer's ``_single_line_snippet``).
* ``full`` — one ``rich`` panel per plan: a frontmatter/metadata table, a body
  excerpt, and the path, bordered by the plan's status color.
* ``markdown`` — agent-friendly grouped headings + a table per source, mirroring
  ``search_handler.py``'s patch markdown.

Color is wired through :func:`_make_console`: ``-c/--color {auto,always,never}``
honoring ``NO_COLOR`` and TTY detection (``rich`` handles both natively in
``auto`` mode; ``always``/``never`` are explicit overrides).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase import plan_style
from sase.plan_search.model import Plan, PlanSearchMatch

# --- source presentation -------------------------------------------------

SOURCE_REPO = "repo"
SOURCE_LOCAL = "local"
# Repo plans are surfaced above local plans (the design's repo-prioritization).
_SOURCE_ORDER = (SOURCE_REPO, SOURCE_LOCAL)
_SOURCE_LABELS = {SOURCE_REPO: "REPO", SOURCE_LOCAL: "LOCAL"}
_SOURCE_ROOTS = {SOURCE_REPO: "sdd/", SOURCE_LOCAL: "~/.sase/plans/"}

# --- status / kind styling -----------------------------------------------

# Shared with sase.main.plan_show_render so the two subcommands stay
# pixel-consistent; see sase.plan_style for the canonical tables.
_DOCUMENT_KIND_STYLES = plan_style.DOCUMENT_KIND_STYLES
_status_icon = plan_style.status_icon
_status_style = plan_style.status_style
_kind_style = plan_style.kind_style

_TITLE_STYLE = "bold"
_SNIPPET_STYLE = "dim"
_MATCH_STYLE = "bold yellow"

# Cap the relpath column so a deeply-nested plan can't blow out the layout.
_MAX_PATH_WIDTH = 48
# Cap the full-format body excerpt.
_MAX_EXCERPT_CHARS = 280


def _make_console(
    color: str, *, file: TextIO | None = None, width: int | None = None
) -> Console:
    """Build a ``rich`` console honoring the ``--color`` mode.

    ``auto`` defers to ``rich`` (color only on a TTY, and never when ``NO_COLOR``
    is set); ``always`` forces color even under ``NO_COLOR``; ``never`` strips it.
    """
    kwargs: dict[str, object] = {"file": file or sys.stdout}
    if width is not None:
        kwargs["width"] = width
    if color == "always":
        kwargs.update(force_terminal=True, no_color=False, color_system="standard")
    elif color == "never":
        kwargs.update(no_color=True)
    return Console(**kwargs)  # type: ignore[arg-type]


# --- small helpers -------------------------------------------------------


def _display_path(plan: Plan) -> str:
    """Path shown in listings: relpath minus ``.md`` and the repo kind dir.

    Repo relpaths are ``{kind_dir}/{shard}/{name}.md``; the kind is already shown
    in its own column, so the leading kind directory is dropped to avoid the
    redundant ``plans/`` prefix. Local relpaths (``{shard}/{name}.md`` or a flat
    ``{name}.md``) only lose the extension.
    """
    rel = plan.relpath
    if rel.endswith(".md"):
        rel = rel[:-3]
    if plan.source == SOURCE_REPO and "/" in rel:
        rel = rel.split("/", 1)[1]
    return rel


def _source_root_label(source: str, matches: list[PlanSearchMatch]) -> str:
    """Return the root label for a source group."""
    if source != SOURCE_REPO or not matches:
        return _SOURCE_ROOTS.get(source, source)

    plan = matches[0].plan
    try:
        root = Path(plan.path)
        for _ in Path(plan.relpath).parts:
            root = root.parent
    except (OSError, RuntimeError, ValueError):
        return _SOURCE_ROOTS[SOURCE_REPO]

    if root.name == "sdd" and root.parent.name == ".sase":
        return ".sase/sdd/"
    if root.name == "sdd":
        return "sdd/"
    return _SOURCE_ROOTS[SOURCE_REPO]


def _created_date(plan: Plan) -> str:
    """The date portion of the ISO ``created_at`` (``YYYY-MM-DD``)."""
    return plan.created_at.split("T", 1)[0] if plan.created_at else ""


def _group_matches(
    matches: list[PlanSearchMatch],
) -> dict[str, list[PlanSearchMatch]]:
    """Group matches by source, preserving each group's global ranking order."""
    grouped: dict[str, list[PlanSearchMatch]] = {}
    for match in matches:
        grouped.setdefault(match.plan.source, []).append(match)
    return grouped


def _ordered_sources(grouped: dict[str, list[PlanSearchMatch]]) -> list[str]:
    """Sources in display order: repo, local, then any unexpected source."""
    ordered = [s for s in _SOURCE_ORDER if s in grouped]
    ordered += [s for s in grouped if s not in _SOURCE_ORDER]
    return ordered


def _plural(count: int, noun: str = "plan") -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _empty_text(query: str | None) -> Text:
    if query and query.strip():
        return Text(f'No plans match "{query}".')
    return Text("No plans found.")


def _single_line_snippet(value: str, query: str | None, max_chars: int = 96) -> str:
    """Pick + truncate a single matched line (ported from bead search).

    With a query, prefers the first line containing it (case-insensitively) and
    centers the truncation window on the hit; without one, uses the first
    non-blank line. Returns ``""`` when there's nothing to show.
    """
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""

    lowered_query = (query or "").lower()
    line = next(
        (line for line in lines if lowered_query and lowered_query in line.lower()),
        lines[0],
    )
    if len(line) <= max_chars:
        return line

    index = line.lower().find(lowered_query) if lowered_query else -1
    if index < 0:
        return line[: max_chars - 1].rstrip() + "…"
    start = max(0, index - max_chars // 2)
    end = min(len(line), start + max_chars)
    start = max(0, end - max_chars)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return f"{prefix}{line[start:end].strip()}{suffix}"


def _snippet_source(match: PlanSearchMatch, query: str | None) -> str:
    """The field text to snippet: the first one containing the query.

    Prefers the clean first-paragraph ``summary`` over the raw ``body`` (which
    leads with the markdown H1), then frontmatter values. With no query (browse
    mode), falls back to the summary/body so the listing still shows context.
    """
    plan = match.plan
    body = _body_without_heading(plan.body)
    if query and query.strip():
        lowered = query.lower()
        for value in (plan.summary, body, *plan.frontmatter.values()):
            if value and lowered in value.lower():
                return value
    return plan.summary or body


def _snippet_text(match: PlanSearchMatch, query: str | None) -> Text | None:
    """A dimmed snippet ``Text`` with query occurrences highlighted."""
    raw = _single_line_snippet(_snippet_source(match, query), query)
    if not raw:
        return None
    text = Text(raw, style=_SNIPPET_STYLE)
    if query and query.strip():
        text.highlight_words([query], style=_MATCH_STYLE, case_sensitive=False)
    return text


# --- compact -------------------------------------------------------------


def _group_header(source: str, group: list[PlanSearchMatch], width: int) -> Text:
    text = Text()
    text.append(_SOURCE_LABELS.get(source, source.upper()), style="bold")
    text.append(f"  ▸ {_source_root_label(source, group)}", style="dim")
    right = _plural(len(group))
    pad = max(1, width - text.cell_len - len(right))
    text.append(" " * pad)
    text.append(right, style="dim")
    return text


def _compact_row(match: PlanSearchMatch, kind_w: int, path_w: int) -> Text:
    plan = match.plan
    text = Text("  ")
    text.append(_status_icon(plan.status), style=_status_style(plan.status))
    text.append(" ")
    text.append(plan.kind.ljust(kind_w), style=_kind_style(plan.kind))
    text.append("  ")
    text.append(_display_path(plan).ljust(path_w))
    text.append("  ")
    text.append(plan.title or plan.name, style=_TITLE_STYLE)
    return text


def _render_compact(
    matches: list[PlanSearchMatch],
    *,
    query: str | None,
    sort_label: str,
    console: Console,
) -> None:
    if not matches:
        console.print(_empty_text(query))
        return

    grouped = _group_matches(matches)
    plans = [m.plan for m in matches]
    kind_w = max(len(p.kind) for p in plans)
    path_w = min(max(len(_display_path(p)) for p in plans), _MAX_PATH_WIDTH)
    indent = " " * (kind_w + 6)  # align snippet under the path column

    for i, source in enumerate(_ordered_sources(grouped)):
        group = grouped[source]
        if i:
            console.print()
        console.print(_group_header(source, group, console.width))
        for match in group:
            console.print(_compact_row(match, kind_w, path_w), no_wrap=True, crop=False)
            snippet = _snippet_text(match, query)
            if snippet is not None:
                line = Text(indent)
                line.append_text(snippet)
                console.print(line, no_wrap=True, crop=False)

    console.print()
    console.print(_footer(grouped, sort_label))


def _footer(grouped: dict[str, list[PlanSearchMatch]], sort_label: str) -> Text:
    total = sum(len(group) for group in grouped.values())
    parts = [_plural(total)]
    if len(grouped) > 1:
        for source in _ordered_sources(grouped):
            parts.append(f"{len(grouped[source])} {source}")
    parts.append(f"sorted by {sort_label}")
    return Text(" · ".join(parts), style="dim")


# --- full ----------------------------------------------------------------


def _excerpt_text(plan: Plan, query: str | None) -> Text | None:
    raw = (plan.summary or _body_without_heading(plan.body)).strip()
    if not raw:
        return None
    if len(raw) > _MAX_EXCERPT_CHARS:
        raw = raw[: _MAX_EXCERPT_CHARS - 1].rstrip() + "…"
    text = Text(raw, style="italic")
    if query and query.strip():
        text.highlight_words([query], style=_MATCH_STYLE, case_sensitive=False)
    return text


def _body_without_heading(body: str) -> str:
    lines = body.splitlines()
    kept = [line for line in lines if not line.lstrip().startswith("#")]
    return "\n".join(kept).strip()


def _full_panel(match: PlanSearchMatch, query: str | None) -> Panel:
    plan = match.plan
    meta = Table.grid(padding=(0, 2))
    meta.add_column(style="bold", justify="right")
    meta.add_column(overflow="fold")
    meta.add_row("Kind", Text(plan.kind, style=_kind_style(plan.kind)))
    meta.add_row(
        "Status",
        Text(
            f"{_status_icon(plan.status)} {plan.status or 'unknown'}",
            style=_status_style(plan.status),
        ),
    )
    created = _created_date(plan)
    if created:
        meta.add_row("Created", created)
    meta.add_row("Source", plan.source)
    if plan.prompt_link:
        meta.add_row("Prompt", plan.prompt_link)
    if match.matched_fields:
        meta.add_row("Matched", ", ".join(match.matched_fields))
    meta.add_row("Score", f"{match.score:g}")
    meta.add_row("Path", plan.relpath)

    excerpt = _excerpt_text(plan, query)
    body: RenderableType = Group(meta, "", excerpt) if excerpt else meta
    title = Text.assemble(
        (f"{_status_icon(plan.status)} ", _status_style(plan.status)),
        (plan.title or plan.name, _TITLE_STYLE),
    )
    return Panel(
        body,
        title=title,
        title_align="left",
        subtitle=Text(_display_path(plan), style="dim"),
        subtitle_align="right",
        border_style=_status_style(plan.status),
    )


def _render_full(
    matches: list[PlanSearchMatch], *, query: str | None, console: Console
) -> None:
    if not matches:
        console.print(_empty_text(query))
        return
    for i, match in enumerate(matches):
        if i:
            console.print()
        console.print(_full_panel(match, query))


# --- markdown ------------------------------------------------------------


def _md_escape(value: str) -> str:
    """Escape table-breaking pipes so a title can't corrupt a markdown row."""
    return value.replace("|", "\\|")


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _render_markdown(
    matches: list[PlanSearchMatch], *, query: str | None, sort_label: str
) -> str:
    lines = ["# Plan Search Results", ""]
    if query and query.strip():
        lines += [f"**Query:** `{query}`", ""]

    if not matches:
        lines.append(
            f"No plans match `{query}`."
            if query and query.strip()
            else "No plans found."
        )
        return "\n".join(lines) + "\n"

    grouped = _group_matches(matches)
    summary = [_plural(len(matches))]
    if len(grouped) > 1:
        for source in _ordered_sources(grouped):
            summary.append(f"{len(grouped[source])} {source}")
    summary.append(f"sorted by {sort_label}")
    lines.append("Found " + " · ".join(summary))
    lines.append("")

    for source in _ordered_sources(grouped):
        group = grouped[source]
        lines.append(
            f"## {_SOURCE_LABELS.get(source, source.upper())} — "
            f"{_source_root_label(source, group)}"
        )
        lines.append("")
        rows = [
            [
                f"{_status_icon(p.status)} {p.status or '—'}",
                p.kind,
                f"`{_display_path(p)}`",
                _md_escape(p.title or p.name),
                _created_date(p) or "—",
            ]
            for p in (m.plan for m in group)
        ]
        lines.extend(_md_table(["Status", "Kind", "Plan", "Title", "Created"], rows))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# --- entry point ---------------------------------------------------------


def render(
    matches: list[PlanSearchMatch],
    *,
    query: str | None,
    fmt: str,
    color: str,
    sort_label: str,
    file: TextIO | None = None,
) -> None:
    """Render ``matches`` in ``fmt`` to ``file`` (defaults to stdout).

    ``compact``/``full`` go through a color-aware ``rich`` console; ``markdown``
    is plain text written directly (no ``rich`` markup interpretation).
    """
    out = file or sys.stdout
    if fmt == "markdown":
        out.write(_render_markdown(matches, query=query, sort_label=sort_label))
        return

    console = _make_console(color, file=out)
    if fmt == "compact":
        _render_compact(matches, query=query, sort_label=sort_label, console=console)
    elif fmt == "full":
        _render_full(matches, query=query, console=console)
    else:
        raise AssertionError(f"unknown plan-search format: {fmt}")


__all__ = ["_DOCUMENT_KIND_STYLES", "render"]
