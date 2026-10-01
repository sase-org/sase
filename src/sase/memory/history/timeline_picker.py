"""Picker rows for the pager ``@`` timeline modal.

Pure and Textual-free: this module normalizes one core timeline wire
dict into the lightweight row records the timeline picker renders.
All glyphs come from :mod:`sase.memory.history.vocabulary`; the pager
side only sees plain row dicts, so the provider seam stays intact.

Row order follows the timeline: the worktree pseudo-version first,
then the staged pseudo-version when core reports one, then committed
versions newest first. Pseudo-versions are never hidden. A committed
row is hidden when core sets either hidden bit or its class is hidden
by default (moves, reflows); ``.`` in the picker reveals them.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any

from sase.memory.history import render_text
from sase.memory.history.vocabulary import (
    glyph_for,
    is_hidden_by_default,
    label_for,
)
from sase.pager.history.timeline import (
    filter_rows as _filter_rows,
    visible_rows as _visible_rows,
)

#: Pseudo-version classes, shown as the leading worktree/staged rows.
PSEUDO_CLASSES: tuple[str, str] = ("uncommitted", "staged")

#: Ordinal label per pseudo class (committed rows use ``vN``).
PSEUDO_LABELS: dict[str, str] = {"uncommitted": "now", "staged": "stg"}


def _row_is_hidden(row: dict[str, Any], class_name: str) -> bool:
    """Return whether a committed timeline row hides by default."""
    if bool(row.get("hidden", False)):
        return True
    if bool(row.get("hidden_by_default", False)):
        return True
    return is_hidden_by_default(class_name)


def _ordinal_label(class_name: str, ordinal: int) -> str:
    """Return the picker label for one row (``now``/``stg``/``vN``)."""
    if class_name in PSEUDO_LABELS:
        return PSEUDO_LABELS[class_name]
    return f"v{ordinal}"


def _format_day(epoch: int) -> str:
    """Return a short picker date (``Sep 27``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%b %d")


def _words_suffix(summary: dict[str, Any], class_name: str) -> str:
    """Return the word-delta suffix (``+31w −4w``) for one row."""
    if class_name == "created":
        return ""
    added = int(summary.get("words_added", 0) or 0)
    removed = int(summary.get("words_removed", 0) or 0)
    parts = []
    if added:
        parts.append(f"+{added}w")
    if removed:
        parts.append(f"-{removed}w")
    return " ".join(parts)


def _display_for_row(
    *,
    label: str,
    glyph: str,
    date: str,
    age: str,
    summary: str,
    words: str,
    bead: str,
    agent: str,
    short: str,
    pseudo_detail: str = "",
) -> str:
    """Join one picker row's cells with two-space separators."""
    if pseudo_detail:
        cells = [label, glyph, pseudo_detail, "not durable until committed"]
        if words:
            cells.append(words)
        return "  ".join(part for part in cells if part)
    cells = [label, glyph, date, age, summary, words, bead, agent, short]
    return "  ".join(part for part in cells if part)


def build_picker_rows(
    timeline: dict[str, Any], *, now_epoch: int
) -> tuple[dict[str, Any], ...]:
    """Build picker rows for a core timeline wire dict.

    Each row carries ``ordinal``, ``class``, ``label``, ``glyph``,
    ``display``, ``haystack`` (lowercase filter text over section,
    agent, bead, subject, words, and path), and ``hidden``. Building
    rows is O(n) dict reads only, so timelines with hundreds of
    versions open instantly; the modal renders a window of them.
    """
    rows: list[dict[str, Any]] = []
    versions = timeline.get("versions", ())
    if not isinstance(versions, (list, tuple)):
        return ()
    for version in versions:
        if not isinstance(version, dict):
            continue
        class_name = str(version.get("class", "unclassified") or "unclassified")
        try:
            ordinal = int(version.get("ordinal", 0) or 0)
        except (TypeError, ValueError):
            continue
        pseudo = class_name in PSEUDO_CLASSES
        label = _ordinal_label(class_name, ordinal)
        glyph = glyph_for(class_name)
        summary_raw = version.get("summary", {})
        summary_map = dict(summary_raw) if isinstance(summary_raw, dict) else {}
        provenance_raw = version.get("provenance", {})
        provenance = dict(provenance_raw) if isinstance(provenance_raw, dict) else {}
        bead = str(provenance.get("bead") or "")
        agent = str(provenance.get("agent") or "")
        subject = str(provenance.get("subject") or "")
        commit = str(version.get("commit", "") or "")
        short = commit[:7]
        path = str(version.get("path", "") or version.get("source_path", "") or "")
        if pseudo:
            detail = "worktree" if class_name == "uncommitted" else "staged"
            display = _display_for_row(
                label=label,
                glyph=glyph,
                date="",
                age="",
                summary="",
                words="",
                bead="",
                agent="",
                short="",
                pseudo_detail=detail,
            )
            haystack = " ".join((detail, label, path)).lower()
            rows.append(
                {
                    "ordinal": 0,
                    "class": class_name,
                    "label": label,
                    "glyph": glyph,
                    "display": display,
                    "haystack": haystack,
                    "hidden": False,
                    "pseudo": True,
                }
            )
            continue
        if ordinal <= 0:
            continue
        committer_time = int(version.get("committer_time", 0) or 0)
        date = _format_day(committer_time) if committer_time else ""
        age = (
            render_text.format_age(now_epoch, committer_time) if committer_time else ""
        )
        summary = render_text.summary_text(summary_map, class_name)
        words = _words_suffix(summary_map, class_name)
        display = _display_for_row(
            label=label,
            glyph=glyph,
            date=date,
            age=age,
            summary=summary,
            words=words,
            bead=bead,
            agent=agent,
            short=short,
        )
        sections = " ".join(str(part) for part in summary_map.get("section_paths", ()))
        haystack = " ".join(
            (
                sections,
                agent,
                bead,
                subject,
                summary,
                words,
                label_for(class_name),
                label,
                path,
            )
        ).lower()
        rows.append(
            {
                "ordinal": ordinal,
                "class": class_name,
                "label": label,
                "glyph": glyph,
                "display": display,
                "haystack": haystack,
                "hidden": _row_is_hidden(version, class_name),
                "pseudo": False,
            }
        )
    return tuple(rows)


def visible_picker_rows(
    rows: tuple[Mapping[str, Any], ...], *, show_hidden: bool
) -> tuple[Mapping[str, Any], ...]:
    """Return the rows the picker lists (hidden rows need ``.``)."""
    return _visible_rows(rows, show_hidden=show_hidden)


def filter_picker_rows(
    rows: tuple[Mapping[str, Any], ...], query: str
) -> tuple[Mapping[str, Any], ...]:
    """Filter rows across section, agent, bead, subject, and words."""
    return _filter_rows(rows, query)


def hidden_picker_rows(
    rows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Return the committed rows hidden unless ``.`` is pressed."""
    return tuple(row for row in rows if bool(row.get("hidden", False)))


def hidden_summary_text(hidden_rows: tuple[dict[str, Any], ...]) -> str:
    """Return the summary line for hidden rows (``·· 2 hidden …``)."""
    total = len(hidden_rows)
    if not total:
        return ""
    moves = sum(1 for row in hidden_rows if str(row.get("class")) == "moved")
    reflows = sum(
        1 for row in hidden_rows if str(row.get("class")) in ("reflow", "whitespace")
    )
    detail: list[str] = []
    if moves:
        detail.append(f"↦ {moves} move" + ("s" if moves != 1 else ""))
    if reflows:
        detail.append(f"≈ {reflows} reflow" + ("s" if reflows != 1 else ""))
    remainder = total - moves - reflows
    if remainder:
        detail.append(f"{remainder} other")
    return f"·· {total} hidden ({', '.join(detail)}) · . show"


def picker_header_text(
    *,
    subject_display: str,
    total_committed: int,
    hidden_count: int,
    show_hidden: bool,
    query: str,
) -> str:
    """Return the picker title line for the modal header."""
    noun = "version" if total_committed == 1 else "versions"
    header = f"{subject_display} · {total_committed} {noun}"
    if hidden_count and not show_hidden:
        header += f" · {hidden_count} hidden"
    if query:
        header += f" — / {query}"
    else:
        header += " — / filter"
    return header


__all__ = [
    "PSEUDO_CLASSES",
    "PSEUDO_LABELS",
    "build_picker_rows",
    "filter_picker_rows",
    "hidden_picker_rows",
    "hidden_summary_text",
    "picker_header_text",
    "visible_picker_rows",
]
