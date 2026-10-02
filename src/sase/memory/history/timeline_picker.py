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

from rich.cells import cell_len

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


def _format_day(epoch: int, now_epoch: int = 0) -> str:
    """Return a short picker date (``Sep 27``, with year when past)."""
    moment = datetime.datetime.fromtimestamp(epoch)
    if now_epoch:
        try:
            now_year = datetime.datetime.fromtimestamp(now_epoch).year
        except (TypeError, ValueError, OverflowError, OSError):
            now_year = moment.year
        if moment.year != now_year:
            return moment.strftime("%b %d %Y")
    return moment.strftime("%b %d")


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


def _newest_committed_ordinal(versions: object) -> int:
    """Return the newest committed ordinal in a timeline wire list."""
    newest = 0
    if not isinstance(versions, (list, tuple)):
        return 0
    for version in versions:
        if not isinstance(version, dict):
            continue
        try:
            ordinal = int(version.get("ordinal", 0) or 0)
        except (TypeError, ValueError):
            continue
        if ordinal > newest:
            newest = ordinal
    return newest


def build_picker_rows(
    timeline: dict[str, Any],
    *,
    now_epoch: int,
    now_matches_newest: bool = False,
    newest: int | None = None,
) -> tuple[dict[str, Any], ...]:
    """Build picker rows for a core timeline wire dict.

    Each row carries ``ordinal``, ``class``, ``label``, ``glyph``,
    ``haystack`` (lowercase filter text over section,
    agent, bead, subject, words, and path), ``hidden``, ``pseudo``,
    and the structured column cells the modal lays out
    (``date``, ``age``, ``change``, ``words``, ``by``, ``sha``,
    ``detail``, ``is_now_alias``). The ``now`` row is always first:
    the live worktree row when core reports one, otherwise a
    synthesized clean-now row. Building rows is O(n) dict reads only,
    so timelines with hundreds of versions open instantly; the modal
    renders a window of them.
    """
    rows: list[dict[str, Any]] = []
    versions = timeline.get("versions", ())
    if not isinstance(versions, (list, tuple)):
        return ()
    resolved_newest = _newest_committed_ordinal(versions) if newest is None else newest
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
            if class_name == "uncommitted":
                column_detail = "uncommitted · not durable until committed"
            else:
                column_detail = "staged"
            haystack = " ".join((detail, label, path)).lower()
            rows.append(
                {
                    "ordinal": 0,
                    "class": class_name,
                    "label": label,
                    "glyph": glyph,
                    "haystack": haystack,
                    "hidden": False,
                    "pseudo": True,
                    "date": "",
                    "age": "",
                    "change": "",
                    "words": "",
                    "by": "",
                    "sha": "",
                    "detail": column_detail,
                    "is_now_alias": False,
                }
            )
            continue
        if ordinal <= 0:
            continue
        committer_time = int(version.get("committer_time", 0) or 0)
        date = _format_day(committer_time, now_epoch) if committer_time else ""
        age = (
            render_text.format_age(now_epoch, committer_time) if committer_time else ""
        )
        summary = render_text.summary_text(summary_map, class_name)
        words = _words_suffix(summary_map, class_name)
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
                "haystack": haystack,
                "hidden": _row_is_hidden(version, class_name),
                "pseudo": False,
                "date": date,
                "age": age,
                "change": summary,
                "words": words,
                "by": bead or agent,
                "sha": short,
                "detail": "",
                "is_now_alias": bool(
                    now_matches_newest
                    and resolved_newest
                    and ordinal == resolved_newest
                ),
            }
        )
    if resolved_newest > 0 and not any(row.get("label") == "now" for row in rows):
        if now_matches_newest:
            detail = f"≡ v{resolved_newest} · the live file"
        else:
            detail = "the live file"
        rows.insert(
            0,
            {
                "ordinal": 0,
                "class": "",
                "label": "now",
                "glyph": "",
                "haystack": f"now live file {detail}".lower(),
                "hidden": False,
                "pseudo": True,
                "date": "",
                "age": "",
                "change": "",
                "words": "",
                "by": "",
                "sha": "",
                "detail": detail,
                "is_now_alias": False,
            },
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
    pill_text: str = "",
) -> str:
    """Return the picker title line for the modal header."""
    noun = "version" if total_committed == 1 else "versions"
    header = f"{subject_display} · {total_committed} {noun}"
    if hidden_count and not show_hidden:
        header += f" · {hidden_count} hidden"
    if pill_text:
        header += f" · [{pill_text}]"
    if query:
        header += f" — / {query}"
    else:
        header += " — / filter"
    return header


def picker_pill_text(kind: str, ordinal: int, newest: int) -> str:
    """Return the open version's short pill text for the picker header."""
    if kind == "past":
        return f"⟲ PAST · v{ordinal}"
    if kind == "now":
        return f"● NOW · v{newest}"
    if kind == "now_dirty":
        return "◌ NOW"
    if kind == "deleted":
        return "✖ DELETED"
    return ""


def _version_name(ordinal: int) -> str:
    """Return the picker name for an ordinal (``now`` for the worktree)."""
    return "now" if ordinal == 0 else f"v{ordinal}"


def _cursor_key(row: Mapping[str, Any]) -> tuple[int, str]:
    """Return the ``(ordinal, class)`` identity for a cursor row."""
    try:
        ordinal = int(row.get("ordinal", -1) or 0)
    except (TypeError, ValueError):
        ordinal = -1
    return (ordinal, str(row.get("class", "") or ""))


def _normalize_picker_compare(
    *,
    open_ordinal: int,
    cursor_ordinal: int,
    cursor_is_now_alias: bool = False,
) -> tuple[int, int] | None:
    """Return the ``(base, target)`` pair for a picker ``=`` press.

    Comparisons always read older to newer (``0`` means now); ``None``
    means the cursor sits on the open version, so there is nothing to
    compare. When the cursor is newer than the open version, the
    cursor's version becomes the shown target and the previously open
    version becomes the base. A cursor on the ``≡ now`` alias of an open
    now is the open row itself, so there is nothing to compare.
    """
    open_ordinal = int(open_ordinal or 0)
    cursor_ordinal = int(cursor_ordinal or 0)
    if cursor_is_now_alias and open_ordinal == 0:
        return None
    if cursor_ordinal == 0:
        if open_ordinal == 0:
            return None
        return (open_ordinal, 0)
    if cursor_ordinal == open_ordinal:
        return None
    if open_ordinal == 0:
        return (cursor_ordinal, 0)
    return (min(open_ordinal, cursor_ordinal), max(open_ordinal, cursor_ordinal))


def picker_footer_preview(
    cursor_row: Mapping[str, Any] | None,
    *,
    open_ordinal: int,
    open_class: str = "",
    width: int = 0,
) -> str:
    """Return the live footer previewing the cursor row's actions.

    When *width* is positive and the full preview would overflow it,
    the middle hints give way so the actions and ``esc close`` stay on
    one line.
    """
    tail = "· . hidden · / filter · esc close"
    if cursor_row is None:
        full = f"⏎ open {tail}"
        short = "⏎ open · esc close"
    else:
        cursor_ordinal, cursor_class = _cursor_key(cursor_row)
        is_alias = bool(cursor_row.get("is_now_alias", False))
        # A cursor on the ≡ now alias of an open now is the open now row.
        if is_alias and int(open_ordinal or 0) == 0:
            cursor_ordinal = 0
            label = "now"
        else:
            label = str(cursor_row.get("label", "") or _version_name(cursor_ordinal))
        same = cursor_ordinal == int(open_ordinal or 0) and (
            cursor_ordinal != 0 or cursor_class == str(open_class or "")
        )
        if is_alias and int(open_ordinal or 0) == 0:
            same = True
        endpoints = _normalize_picker_compare(
            open_ordinal=open_ordinal,
            cursor_ordinal=cursor_ordinal,
            cursor_is_now_alias=is_alias,
        )
        if same or endpoints is None:
            verb = "● open" if same else "⏎ open"
            full = f"{verb} {label} {tail}"
            short = f"{verb} {label} · esc close"
        else:
            base, target = endpoints
            full = (
                f"⏎ open {label} · = compare {_version_name(base)}"
                f" → {_version_name(target)} {tail}"
            )
            short = (
                f"⏎ open {label} · = compare {_version_name(base)}"
                f" → {_version_name(target)} · esc close"
            )
    if width > 0 and cell_len(full) > width:
        return short
    return full


__all__ = [
    "PSEUDO_CLASSES",
    "PSEUDO_LABELS",
    "build_picker_rows",
    "filter_picker_rows",
    "hidden_picker_rows",
    "hidden_summary_text",
    "picker_footer_preview",
    "picker_header_text",
    "picker_pill_text",
    "visible_picker_rows",
]
