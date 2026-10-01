"""Rich text rendering for memory history.

Timelines, single versions, word diffs, and the feed render as colored
Rich output on a TTY and as plain text when piped (a piped word diff
uses git's ``[-old-]{+new+}`` form). All glyphs come from
:mod:`sase.memory.history.vocabulary`.
"""

from __future__ import annotations

import datetime
from typing import Any

from rich.console import Console
from rich.text import Text

from sase.memory.history.vocabulary import (
    HOME_TAG,
    STYLE_ROLES,
    glyph_for,
)

_WORD_DELETE_OPEN = "[-"
_WORD_DELETE_CLOSE = "-]"
_WORD_INSERT_OPEN = "{+"
_WORD_INSERT_CLOSE = "+}"


def format_age(now_epoch: int, then_epoch: int) -> str:
    """Return a compact relative age (``3d``, ``8d``, ``5mo``)."""
    delta = max(0, now_epoch - then_epoch)
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    if delta < 30 * 86400:
        return f"{delta // 86400}d"
    if delta < 365 * 86400:
        return f"{delta // (30 * 86400)}mo"
    return f"{delta // (365 * 86400)}y"


def _format_date(epoch: int) -> str:
    """Return an ISO local date (``2026-09-27``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")


def format_banner_date(epoch: int) -> str:
    """Return a tombstone banner date (``Jul 13 2026``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%b %d %Y")


def _format_day(epoch: int) -> str:
    """Return a feed day header (``Mon Sep 28``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%a %b %d")


def _format_clock(epoch: int) -> str:
    """Return a local clock time (``11:03``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%H:%M")


def short_display_for_subject_id(subject_id: str) -> str:
    """Return a compact display name for a subject id.

    ``note:project:sase/tui`` becomes ``tui.md``-style ``tui``,
    ``strand:project:sase/glossary/stitch`` becomes ``glossary:stitch``,
    and ``instructions:project:sase/.`` becomes ``AGENTS.md``.
    """
    kind, _, rest = subject_id.partition(":")
    name = rest.split("/", 1)[1] if "/" in rest else rest
    if kind == "strand":
        return name.replace("/", ":")
    if kind == "instructions":
        if name in (".", ""):
            return "AGENTS.md"
        return f"{name}/AGENTS.md"
    if kind == "web":
        return name
    if kind == "asset":
        return name
    return name


def _kind_for_subject_id(subject_id: str) -> str:
    """Return the subject kind embedded in a subject id."""
    kind, _, _ = subject_id.partition(":")
    return kind or "note"


def _scope_display_for_key(scope_key: str) -> str:
    """Render ``project:sase`` as ``project sase``."""
    return scope_key.replace(":", " ")


def _state_display(state: Any) -> str:
    """Render a timeline path-state wire value (case-insensitive)."""
    normalized = str(state).lower().replace("_", "").replace(" ", "")
    if normalized == "notracked":
        return "TRACKED"
    if normalized in ("nouncs", "novcs", "no_vcs"):
        return "NO VCS"
    if "untracked" in normalized:
        return "UNTRACKED"
    if "ignored" in normalized:
        return "IGNORED"
    return str(state).upper()


def summary_text(summary: dict[str, Any], class_name: str) -> str:
    """Return the one-line meaning summary for a version."""
    sections = list(summary.get("section_paths", ()))
    phrase = summary.get("frontmatter_phrase")
    if phrase:
        return str(phrase)
    if class_name == "created":
        created_words = summary.get("created_words")
        size = f" · {created_words}w" if created_words is not None else ""
        if sections:
            return (
                "created · " + " · ".join(f"§ {section}" for section in sections) + size
            )
        return f"created{size}"
    if sections:
        return " · ".join(f"§ {section}" for section in sections)
    return ""


def _words_text(summary: dict[str, Any], class_name: str) -> str:
    """Return the word-delta suffix (``+31w -4w``) for a version.

    Created versions carry their size in :func:`summary_text` already,
    so there is no separate delta suffix for them.
    """
    if class_name == "created":
        return ""
    added = int(summary.get("words_added", 0) or 0)
    removed = int(summary.get("words_removed", 0) or 0)
    if added == 0 and removed == 0:
        return ""
    parts = []
    if added:
        parts.append(f"+{added}w")
    if removed:
        parts.append(f"-{removed}w")
    return " ".join(parts)


def _version_row_cells(
    version: dict[str, Any], now_epoch: int
) -> tuple[str, str, str, str, str, str, str, str, str]:
    """Return timeline row cells for one version wire dict."""
    class_name = str(version.get("class", "unclassified"))
    ordinal = version.get("ordinal", 0)
    if class_name in ("uncommitted",):
        ordinal_label = "now"
    elif class_name in ("staged",):
        ordinal_label = "stg"
    else:
        ordinal_label = f"v{ordinal}"
    glyph = glyph_for(class_name)
    committer_time = int(version.get("committer_time", 0) or 0)
    date = _format_date(committer_time) if committer_time else "----.--.--"
    age = format_age(now_epoch, committer_time) if committer_time else ""
    summary = summary_text(dict(version.get("summary", {})), class_name)
    words = _words_text(dict(version.get("summary", {})), class_name)
    provenance = dict(version.get("provenance", {}))
    bead = str(provenance.get("bead") or "")
    agent = str(provenance.get("agent") or "")
    commit = str(version.get("commit", "") or "")
    return (
        ordinal_label,
        glyph,
        date,
        age,
        summary,
        words,
        bead,
        agent,
        commit[:7],
    )


def render_timeline(
    console: Console,
    timeline: dict[str, Any],
    subject_display: str,
    scope_key: str,
    *,
    now_epoch: int,
    include_hidden: bool = False,
) -> None:
    """Render one subject's timeline as text rows."""
    subject_id = str(timeline.get("subject_id", ""))
    kind = _kind_for_subject_id(subject_id)
    versions = list(timeline.get("versions", ()))
    hidden = [v for v in versions if bool(v.get("hidden_by_default", False))]
    shown = (
        versions
        if include_hidden
        else [v for v in versions if not bool(v.get("hidden_by_default", False))]
    )
    total_committed = sum(1 for v in versions if int(v.get("ordinal", 0) or 0) > 0)
    hidden_committed = sum(1 for v in hidden if int(v.get("ordinal", 0) or 0) > 0)
    count_text = f"{total_committed} version" + ("s" if total_committed != 1 else "")
    if hidden_committed and not include_hidden:
        count_text += f" ({hidden_committed} hidden)"
    header = Text()
    header.append(glyph_for("authored"), style=STYLE_ROLES["past"])
    header.append(f" {subject_display} · {kind} · ")
    header.append(_scope_display_for_key(scope_key), style=STYLE_ROLES["dim"])
    header.append(f" · {count_text} · ")
    header.append(
        _state_display(timeline.get("state", "tracked")),
        style=STYLE_ROLES["uncommitted"]
        if _state_display(timeline.get("state", "tracked")) != "TRACKED"
        else STYLE_ROLES["dim"],
    )
    console.print(header)
    for version in shown:
        (ordinal_label, glyph, date, age, summary, words, bead, agent, short) = (
            _version_row_cells(version, now_epoch)
        )
        row = Text()
        row.append(f"  {ordinal_label:<4} {glyph}  {date}  {age:<3} ")
        if summary:
            row.append(summary + "  ")
        if words:
            row.append(words + "   ", style=STYLE_ROLES["dim"])
        if bead:
            row.append(bead + "  ")
        if agent:
            row.append(agent + "  ", style=STYLE_ROLES["dim"])
        if short:
            row.append(short, style=STYLE_ROLES["dim"])
        console.print(row)
    if hidden_committed and not include_hidden:
        moves = sum(1 for v in hidden if str(v.get("class")) == "moved")
        reflows = sum(
            1 for v in hidden if str(v.get("class")) in ("reflow", "whitespace")
        )
        detail = []
        if moves:
            detail.append(f"↦ {moves} move" + ("s" if moves != 1 else ""))
        if reflows:
            detail.append(f"≈ {reflows} reflow" + ("s" if reflows != 1 else ""))
        remainder = hidden_committed - moves - reflows
        if remainder:
            detail.append(f"{remainder} other")
        console.print(
            f"  ·· {hidden_committed} hidden ({', '.join(detail)}) · -a to show",
            style=STYLE_ROLES["dim"],
        )


def render_version(
    console: Console,
    response: dict[str, Any],
    subject_display: str,
    scope_key: str,
    *,
    now_epoch: int,
) -> None:
    """Render one version header plus its body."""
    version = dict(response.get("version", {}))
    (ordinal_label, glyph, date, age, summary, words, bead, agent, short) = (
        _version_row_cells(version, now_epoch)
    )
    header = Text()
    header.append(glyph, style=STYLE_ROLES["past"])
    header.append(f" {subject_display} · {ordinal_label} · {date}")
    if age:
        header.append(f" · {age} ago", style=STYLE_ROLES["dim"])
    if summary:
        header.append(f" · {summary}")
    if words:
        header.append(f" · {words}", style=STYLE_ROLES["dim"])
    provenance_bits = " · ".join(bit for bit in (bead, agent, short) if bit)
    if provenance_bits:
        header.append(f" · {provenance_bits}", style=STYLE_ROLES["dim"])
    header.append(f" · {_scope_display_for_key(scope_key)}", style=STYLE_ROLES["dim"])
    console.print(header)
    body = str(response.get("body", "") or "")
    if response.get("body_missing"):
        console.print("(blob unavailable: object missing)", style=STYLE_ROLES["dim"])
    elif body:
        console.print(body, end="" if body.endswith("\n") else "\n")


def _render_word_line(
    ops: list[dict[str, Any]],
    *,
    plain: bool,
    insert_style: str | None,
    delete_style: str | None,
    line: str = "",
) -> Text:
    """Render one target line's word ops, inline.

    Spans are applied against *line* (the fetched target body) so the
    gaps between word tokens keep their original spacing; delete spans
    carry their own text at their anchor position. Without *line* the
    op texts are concatenated in order.
    """
    ordered = sorted(
        ops,
        key=lambda op: (
            int(op.get("start", 0) or 0),
            int(op.get("end", 0) or 0),
        ),
    )
    rendered = Text()
    if not line:
        for op in ordered:
            kind = str(op.get("kind", "equal"))
            text = str(op.get("text", ""))
            if kind == "insert":
                if plain:
                    rendered.append(f"{_WORD_INSERT_OPEN}{text}{_WORD_INSERT_CLOSE}")
                else:
                    rendered.append(text, style=insert_style)
            elif kind == "delete":
                if plain:
                    rendered.append(f"{_WORD_DELETE_OPEN}{text}{_WORD_DELETE_CLOSE}")
                else:
                    rendered.append(text, style=delete_style)
            else:
                rendered.append(text)
        return rendered
    cursor = 0
    for op in ordered:
        kind = str(op.get("kind", "equal"))
        text = str(op.get("text", ""))
        start = min(int(op.get("start", 0) or 0), len(line))
        end = min(int(op.get("end", 0) or 0), len(line))
        if start > cursor:
            rendered.append(line[cursor:start])
        if kind == "insert":
            if plain:
                rendered.append(f"{_WORD_INSERT_OPEN}{text}{_WORD_INSERT_CLOSE}")
            else:
                rendered.append(text, style=insert_style)
        elif kind == "delete":
            if plain:
                rendered.append(f"{_WORD_DELETE_OPEN}{text}{_WORD_DELETE_CLOSE}")
            else:
                rendered.append(text, style=delete_style)
        else:
            rendered.append(text or line[start:end])
        cursor = max(cursor, end)
    if cursor < len(line):
        rendered.append(line[cursor:])
    return rendered


def render_diff(
    console: Console,
    compare: dict[str, Any],
    *,
    plain: bool,
    base_body: str = "",
    target_body: str = "",
) -> None:
    """Render a version comparison as an inline word diff."""
    comparison = dict(compare.get("comparison", {}))
    base = dict(compare.get("base", {}))
    target = dict(compare.get("target", {}))
    base_label = f"v{base.get('ordinal', '?')}"
    target_label = f"v{target.get('ordinal', '?')}"
    if str(target.get("class")) in ("uncommitted", "staged"):
        target_label = "now"
    header = Text()
    header.append("≠ ", style=STYLE_ROLES["past"])
    header.append(f"diff {base_label} → {target_label}")
    console.print(header)
    frontmatter = dict(comparison.get("frontmatter", {}))
    type_change = frontmatter.get("type_change")
    entries = list(frontmatter.get("entries", ()))
    if type_change == "promoted":
        console.print("⇧ type: reference → core", style=STYLE_ROLES["past"])
    elif type_change == "demoted":
        console.print("⇩ type: core → reference", style=STYLE_ROLES["past"])
    for entry in entries:
        key = entry.get("key", "")
        before = entry.get("before", "")
        after = entry.get("after", "")
        console.print(f"▣ {key}: {before} → {after}")
    word_lines = {
        int(line.get("target_line", 0)): line
        for line in comparison.get("word_ops", ())
        if int(line.get("target_line", 0) or 0) > 0
    }
    hunks = list(comparison.get("hunks", ()))
    if not word_lines and not hunks:
        unified = str(comparison.get("unified_diff", "") or "")
        if unified:
            console.print(unified, end="" if unified.endswith("\n") else "\n")
        else:
            console.print("(no changes)", style=STYLE_ROLES["dim"])
        return
    target_lines = target_body.splitlines()
    anchors = sorted(
        (
            int(anchor.get("after_target_line", 0) or 0),
            int(anchor.get("removed_count", 0) or 0),
        )
        for anchor in comparison.get("removal_anchors", ())
    )
    previous_end = 0
    for hunk in hunks:
        start = int(hunk.get("target_start", 0) or 0)
        end = int(hunk.get("target_end", 0) or 0)
        if start > previous_end + 1:
            console.print(
                f"┄ {start - previous_end - 1} unchanged lines ┄",
                style=STYLE_ROLES["dim"],
            )
        sections = list(hunk.get("section_path", ()))
        if sections:
            console.print(
                "§ " + " › ".join(str(section) for section in sections),
                style=STYLE_ROLES["dim"],
            )
        for lineno in range(max(start, 1), max(end, 1)):
            ops = list(word_lines.get(lineno, {}).get("ops", ()))
            if ops:
                line_text = (
                    target_lines[lineno - 1] if 1 <= lineno <= len(target_lines) else ""
                )
                console.print(
                    _render_word_line(
                        [dict(op) for op in ops],
                        plain=plain,
                        insert_style=STYLE_ROLES["insert"],
                        delete_style=STYLE_ROLES["delete"],
                        line=line_text,
                    )
                )
            elif 1 <= lineno <= len(target_lines):
                console.print(Text(target_lines[lineno - 1]))
        for after, removed in anchors:
            if max(start, 1) - 1 <= after < max(end, 1):
                console.print(
                    f"╴ {removed} line{'s' if removed != 1 else ''} removed",
                    style=None if plain else STYLE_ROLES["gutter_remove"],
                )
        previous_end = max(previous_end, max(end, 1) - 1)
    stats = dict(comparison.get("stats", {}))
    added = int(stats.get("words_added", 0) or 0)
    removed = int(stats.get("words_removed", 0) or 0)
    if added or removed:
        console.print(f"+{added}w -{removed}w", style=STYLE_ROLES["dim"])


def _feed_entry_text(entry: dict[str, Any]) -> tuple[str, str, str]:
    """Return (display, summary, words) for one feed entry."""
    subject_id = str(entry.get("subject_id", ""))
    class_name = str(entry.get("class", "unclassified"))
    display = short_display_for_subject_id(subject_id)
    summary = dict(entry.get("summary", {}))
    return display, summary_text(summary, class_name), _words_text(summary, class_name)


def render_feed(
    console: Console,
    feed: dict[str, Any],
    scopes_label: str,
    *,
    now_epoch: int,
) -> None:
    """Render merged changesets grouped by day (newest first)."""
    changesets = list(feed.get("changesets", ()))
    hidden_count = int(feed.get("hidden_changeset_count", 0) or 0)
    header = Text()
    header.append("▤ ", style=STYLE_ROLES["past"])
    header.append(f"Memory changes · {scopes_label}")
    count = len(changesets)
    header.append(
        f" · {count} changeset" + ("s" if count != 1 else ""),
        style=STYLE_ROLES["dim"],
    )
    if hidden_count:
        header.append(f" · {hidden_count} regen-only hidden", style=STYLE_ROLES["dim"])
    console.print(header)
    current_day = ""
    for changeset in changesets:
        committer_time = int(changeset.get("committer_time", 0) or 0)
        day = _format_day(committer_time) if committer_time else "undated"
        if day != current_day:
            current_day = day
            console.print(f"━━ {day} " + "━" * max(0, 60 - len(day)))
        provenance = dict(changeset.get("provenance", {}))
        subject = str(provenance.get("subject") or "(no subject)")
        bead = str(provenance.get("bead") or "")
        agent = str(provenance.get("agent") or "")
        scope_key = str(changeset.get("scope_key", ""))
        home_tag = f"{HOME_TAG}  " if scope_key == "home" else ""
        meta = " · ".join(bit for bit in (bead, agent) if bit)
        line = Text()
        line.append(
            f"  {_format_clock(committer_time) if committer_time else '--:--'}  "
        )
        line.append(subject)
        if meta:
            line.append(f"   {home_tag}{meta}", style=STYLE_ROLES["dim"])
        elif home_tag:
            line.append(f"   {home_tag.strip()}", style=STYLE_ROLES["dim"])
        console.print(line)
        for entry in changeset.get("authored", ()):
            display, summary, words = _feed_entry_text(dict(entry))
            row = Text()
            row.append(
                f"          {glyph_for(str(entry.get('class', '')))} {display:<28}"
            )
            if summary:
                row.append(f"  {summary}")
            if words:
                row.append(f"  {words}", style=STYLE_ROLES["dim"])
            console.print(row)
        consequences = list(changeset.get("consequences", ()))
        if consequences:
            folded = Text()
            folded.append("            ⟳ ", style=STYLE_ROLES["dim"])
            folded.append(
                " · ".join(
                    short_display_for_subject_id(str(c.get("subject_id", "")))
                    for c in consequences
                ),
                style=STYLE_ROLES["dim"],
            )
            console.print(folded)
    if hidden_count:
        console.print(
            f"  ⋯ {hidden_count} regenerated-only changesets hidden  -a to show",
            style=STYLE_ROLES["dim"],
        )
    _ = now_epoch


__all__ = [
    "format_age",
    "render_diff",
    "render_feed",
    "render_timeline",
    "render_version",
    "short_display_for_subject_id",
    "summary_text",
]
