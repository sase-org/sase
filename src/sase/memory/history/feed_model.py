"""Pure changes-feed view-model shared by the pager and the TUI.

Extracted from :mod:`sase.memory.history.feed_document` (epic design
``plan:202610/memory_history_tui.md`` §13, ``changes-lens`` phase): the
pager feed document consumes this model, and the Memory pane Changes
lens renders its rail rows from it. Both surfaces therefore group
days, fold regen-only changesets, and label subjects identically.

This module is pure and Textual-free. It renders plain strings from
plain feed dicts, so builder goldens never need git or the Rust core.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from sase.memory.history.render_text import (
    short_display_for_subject_id,
    summary_text,
)
from sase.memory.history.vocabulary import HOME_TAG, glyph_for

#: Number of lens rows rendered before the trailing "older" row extends
#: the window (epic plan §4.5/D8: newest 100, extend by 100 on demand).
FEED_WINDOW = 100

#: Maximum per-changeset subject sections shown inline on the Changes
#: card before the ``+N more`` line (epic plan §4.5).
MAX_INLINE_SECTIONS = 6


def day_key(epoch: int) -> str:
    """Return the grouping key (local ``YYYY-MM-DD``) for *epoch*."""
    if not epoch:
        return "undated"
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")


def day_header(epoch: int) -> str:
    """Return the day section title (``Mon Sep 28``) for *epoch*."""
    if not epoch:
        return "undated"
    return datetime.datetime.fromtimestamp(epoch).strftime("%a %b %d")


def format_clock(epoch: int) -> str:
    """Return a local clock time (``11:03``) for *epoch*."""
    if not epoch:
        return "--:--"
    return datetime.datetime.fromtimestamp(epoch).strftime("%H:%M")


def words_suffix(summary: dict[str, Any], class_name: str) -> str:
    """Return the word-delta suffix (``+31w -4w``) for a version."""
    if class_name == "created":
        return ""
    try:
        added = int(summary.get("words_added", 0) or 0)
    except (TypeError, ValueError):
        added = 0
    try:
        removed = int(summary.get("words_removed", 0) or 0)
    except (TypeError, ValueError):
        removed = 0
    parts = []
    if added:
        parts.append(f"+{added}w")
    if removed:
        parts.append(f"-{removed}w")
    return " ".join(parts)


def entry_selector(entry: dict[str, Any]) -> str:
    """Return the core selector identifying one feed entry's subject."""
    path = entry.get("path")
    if isinstance(path, str) and path:
        return path
    subject_id = entry.get("subject_id")
    if isinstance(subject_id, str) and subject_id:
        return subject_id
    return ""


def entry_revision(entry: dict[str, Any], changeset_commit: str | None) -> str:
    """Return the version revision (``vN`` or SHA) for one feed entry."""
    try:
        ordinal = int(entry.get("ordinal", 0) or 0)
    except (TypeError, ValueError):
        ordinal = 0
    if ordinal > 0:
        return f"v{ordinal}"
    commit = entry.get("commit")
    if isinstance(commit, str) and commit:
        return commit
    if isinstance(changeset_commit, str) and changeset_commit:
        return changeset_commit
    return "now"


def has_provenance(changeset: dict[str, Any]) -> bool:
    """Return whether a changeset row carries bead/agent/commit labels."""
    provenance = changeset.get("provenance", {})
    if isinstance(provenance, dict) and (
        provenance.get("bead") or provenance.get("agent")
    ):
        return True
    commit = changeset.get("commit")
    return isinstance(commit, str) and bool(commit)


@dataclass(frozen=True, slots=True)
class _ProvenanceItem:
    """One bead/agent/commit chip on a changeset row."""

    visible: str
    ref: str


def provenance_items(changeset: dict[str, Any]) -> tuple[_ProvenanceItem, ...]:
    """Return the bead/agent/commit chips for one changeset (wire order)."""
    provenance = changeset.get("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}
    commit = changeset.get("commit")
    items: list[_ProvenanceItem] = []
    bead = provenance.get("bead")
    if isinstance(bead, str) and bead:
        items.append(_ProvenanceItem(visible=bead, ref=f"bead:{bead}"))
    agent = provenance.get("agent")
    if isinstance(agent, str) and agent:
        items.append(_ProvenanceItem(visible=agent, ref=f"agent:{agent}"))
    short = commit[:7] if isinstance(commit, str) and commit else ""
    if short:
        items.append(
            _ProvenanceItem(
                visible=short, ref=f"commit:{commit if isinstance(commit, str) else ''}"
            )
        )
    return tuple(items)


@dataclass(frozen=True, slots=True)
class _FeedSubjectView:
    """One authored subject inside a changeset."""

    subject_id: str
    display: str
    class_name: str
    glyph: str
    meaning: str
    words: str
    scope_key: str
    selector: str
    revision: str


def _authored_subjects(
    changeset: dict[str, Any], scope_key: str
) -> tuple[_FeedSubjectView, ...]:
    """Return the authored subject views for one changeset (wire order)."""
    raw = changeset.get("authored", ())
    if not isinstance(raw, (list, tuple)):
        return ()
    commit = changeset.get("commit")
    changeset_commit = commit if isinstance(commit, str) else None
    views: list[_FeedSubjectView] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        subject_id = str(entry.get("subject_id", "") or "")
        class_name = str(entry.get("class", "") or "unclassified")
        summary = entry.get("summary", {})
        summary_map = dict(summary) if isinstance(summary, dict) else {}
        try:
            meaning = summary_text(summary_map, class_name)
        except Exception:
            meaning = ""
        views.append(
            _FeedSubjectView(
                subject_id=subject_id,
                display=short_display_for_subject_id(subject_id),
                class_name=class_name,
                glyph=glyph_for(class_name),
                meaning=str(meaning or ""),
                words=words_suffix(summary_map, class_name),
                scope_key=scope_key,
                selector=entry_selector(dict(entry)),
                revision=entry_revision(dict(entry), changeset_commit),
            )
        )
    return tuple(views)


def changeset_word_delta(changeset: dict[str, Any]) -> str:
    """Return the summed word delta (``+200w -3w``) across authored rows."""
    raw = changeset.get("authored", ())
    if not isinstance(raw, (list, tuple)):
        return ""
    added = 0
    removed = 0
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        class_name = str(entry.get("class", "") or "")
        if class_name == "created":
            continue
        summary = entry.get("summary", {})
        summary_map = dict(summary) if isinstance(summary, dict) else {}
        try:
            added += int(summary_map.get("words_added", 0) or 0)
        except (TypeError, ValueError):
            pass
        try:
            removed += int(summary_map.get("words_removed", 0) or 0)
        except (TypeError, ValueError):
            pass
    parts = []
    if added:
        parts.append(f"+{added}w")
    if removed:
        parts.append(f"-{removed}w")
    return " ".join(parts)


def _consequence_displays(changeset: dict[str, Any]) -> tuple[str, ...]:
    """Return the short display names of generated consequences."""
    raw = changeset.get("consequences", ())
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(
        short_display_for_subject_id(str(item.get("subject_id", "") or ""))
        for item in raw
        if isinstance(item, dict)
    )


def _is_regen_only(changeset: dict[str, Any]) -> bool:
    """Return whether a changeset folds into the regen-only count row."""
    return bool(changeset.get("regen_only", False))


def _is_home_scope(scope_key: str) -> bool:
    """Return whether *scope_key* is the home scope (tagged ``⌂``)."""
    return scope_key == "home"


@dataclass(frozen=True, slots=True)
class _ChangesetView:
    """One changeset row's view-model for the feed and the Changes lens."""

    scope_key: str
    commit: str
    committer_time: int
    clock: str
    subject_line: str
    bead: str
    agent: str
    home: bool
    regen_only: bool
    boilerplate: bool
    day_key: str
    day_title: str
    first_subject: str
    extra_subjects: int
    word_delta: str
    provenance: tuple[_ProvenanceItem, ...]
    authored: tuple[_FeedSubjectView, ...]
    consequences: tuple[str, ...]


def changeset_view(changeset: dict[str, Any]) -> _ChangesetView:
    """Return the view-model for one raw changeset dict. Never raises."""
    try:
        scope_key = str(changeset.get("scope_key", "") or "")
    except Exception:
        scope_key = ""
    try:
        commit = str(changeset.get("commit", "") or "")
    except Exception:
        commit = ""
    try:
        epoch = int(changeset.get("committer_time", 0) or 0)
    except (TypeError, ValueError):
        epoch = 0
    provenance = changeset.get("provenance", {})
    provenance_map = provenance if isinstance(provenance, dict) else {}
    try:
        subject_line = str(provenance_map.get("subject", "") or "(no subject)")
    except Exception:
        subject_line = "(no subject)"
    try:
        bead = str(provenance_map.get("bead", "") or "")
        agent = str(provenance_map.get("agent", "") or "")
    except Exception:
        bead, agent = "", ""
    try:
        authored = _authored_subjects(changeset, scope_key)
    except Exception:
        authored = ()
    try:
        consequences = _consequence_displays(changeset)
    except Exception:
        consequences = ()
    first = authored[0].display if authored else ""
    extra = max(0, len(authored) - 1)
    try:
        delta = changeset_word_delta(changeset)
    except Exception:
        delta = ""
    try:
        provenance_chips = provenance_items(changeset)
    except Exception:
        provenance_chips = ()
    return _ChangesetView(
        scope_key=scope_key,
        commit=commit,
        committer_time=epoch,
        clock=format_clock(epoch),
        subject_line=subject_line,
        bead=bead,
        agent=agent,
        home=_is_home_scope(scope_key),
        regen_only=_is_regen_only(changeset),
        boilerplate=bool(changeset.get("boilerplate", False)),
        day_key=day_key(epoch),
        day_title=day_header(epoch),
        first_subject=first,
        extra_subjects=extra,
        word_delta=delta,
        provenance=provenance_chips,
        authored=authored,
        consequences=consequences,
    )


@dataclass(frozen=True, slots=True)
class _FeedDay:
    """One day group: visible changesets plus folded regen-only rows."""

    key: str
    title: str
    epoch: int
    visible: tuple[_ChangesetView, ...]
    hidden: tuple[_ChangesetView, ...]


def group_feed(feed: dict[str, Any]) -> tuple[_FeedDay, ...]:
    """Group raw changesets by local day (wire order preserved).

    Regen-only changesets split into the day's ``hidden`` fold; every
    other changeset stays ``visible``. Never raises.
    """
    try:
        raw = feed.get("changesets", ())
        changesets = [dict(item) for item in raw if isinstance(item, dict)]
    except Exception:
        return ()
    order: list[str] = []
    groups: dict[str, dict[str, Any]] = {}
    for changeset in changesets:
        try:
            epoch = int(changeset.get("committer_time", 0) or 0)
        except (TypeError, ValueError):
            epoch = 0
        key = day_key(epoch)
        group = groups.get(key)
        if group is None:
            group = {"epoch": epoch, "title": day_header(epoch), "items": []}
            groups[key] = group
            order.append(key)
        group["items"].append(changeset)
        try:
            newest = int(group["epoch"] or 0)
        except (TypeError, ValueError):
            newest = 0
        if epoch > newest:
            group["epoch"] = epoch
            group["title"] = day_header(epoch)
    days: list[_FeedDay] = []
    for key in order:
        group = groups[key]
        items = list(group["items"])
        visible = tuple(
            changeset_view(item) for item in items if not _is_regen_only(item)
        )
        hidden = tuple(changeset_view(item) for item in items if _is_regen_only(item))
        try:
            epoch = int(group["epoch"] or 0)
        except (TypeError, ValueError):
            epoch = 0
        days.append(
            _FeedDay(
                key=key,
                title=str(group["title"]),
                epoch=epoch,
                visible=visible,
                hidden=hidden,
            )
        )
    return tuple(days)


def flatten_visible(days: tuple[_FeedDay, ...]) -> tuple[_ChangesetView, ...]:
    """Return every visible changeset across days, newest day first."""
    rows: list[_ChangesetView] = []
    for day in days:
        rows.extend(day.visible)
    return tuple(rows)


def dedupe_changesets(
    changesets: tuple[_ChangesetView, ...] | list[_ChangesetView],
) -> tuple[_ChangesetView, ...]:
    """Dedupe changesets by ``(scope, commit)`` keeping the first row."""
    seen: set[tuple[str, str]] = set()
    kept: list[_ChangesetView] = []
    for view in changesets:
        try:
            key = (str(view.scope_key), str(view.commit))
        except Exception:
            continue
        if key in seen:
            continue
        seen.add(key)
        kept.append(view)
    return tuple(kept)


def filter_changesets(
    changesets: tuple[_ChangesetView, ...] | list[_ChangesetView],
    query: str,
) -> tuple[_ChangesetView, ...]:
    """Filter changesets by commit subject, subject names, bead, agent."""
    needle = str(query or "").strip().lower()
    if not needle:
        return tuple(changesets)
    kept: list[_ChangesetView] = []
    for view in changesets:
        try:
            haystacks = [
                view.subject_line.lower(),
                view.bead.lower(),
                view.agent.lower(),
                view.commit.lower(),
            ]
            haystacks.extend(subject.display.lower() for subject in view.authored)
            haystacks.extend(subject.subject_id.lower() for subject in view.authored)
        except Exception:
            continue
        if any(needle in hay for hay in haystacks):
            kept.append(view)
    return tuple(kept)


def window_changesets(
    changesets: tuple[_ChangesetView, ...] | list[_ChangesetView],
    limit: int,
) -> tuple[tuple[_ChangesetView, ...], int]:
    """Return ``(shown, older_count)`` for a bounded window of rows."""
    rows = tuple(changesets)
    try:
        count = max(0, int(limit))
    except (TypeError, ValueError):
        count = FEED_WINDOW
    return (rows[:count], max(0, len(rows) - min(len(rows), count)))


def changeset_row_text(view: _ChangesetView, *, width: int = 0) -> str:
    """Return the one-line rail text for one changeset row.

    Shows clock, class glyph of the first authored subject, the first
    subject plus ``+N more``, the word delta, and ``⌂`` for home.
    Pure: never raises.
    """
    try:
        glyph = view.authored[0].glyph if view.authored else "·"
        if view.first_subject:
            stem = view.first_subject
            if view.extra_subjects:
                stem += f" +{view.extra_subjects} more"
        else:
            stem = view.subject_line
        row = f"  {view.clock} {glyph} {stem}"
        if view.word_delta:
            row += f"  {view.word_delta}"
        if view.home:
            row += f"  {HOME_TAG}"
        if width and len(row) > width:
            row = row[: max(0, width - 1)] + "…"
        return row
    except Exception:
        return ""


def regen_count_text(hidden_count: int) -> str:
    """Return the collapsed regen-only count line for a day."""
    noun = "changeset" if hidden_count == 1 else "changesets"
    return f"  ⋯ {hidden_count} regenerated-only {noun} hidden"


def older_window_text(older_count: int) -> str:
    """Return the trailing window-extension row text."""
    return f"  ··· {older_count} older · j loads more"


__all__ = [
    "FEED_WINDOW",
    "MAX_INLINE_SECTIONS",
    "changeset_row_text",
    "changeset_view",
    "changeset_word_delta",
    "day_header",
    "day_key",
    "dedupe_changesets",
    "entry_revision",
    "entry_selector",
    "filter_changesets",
    "flatten_visible",
    "format_clock",
    "group_feed",
    "has_provenance",
    "older_window_text",
    "provenance_items",
    "regen_count_text",
    "window_changesets",
    "words_suffix",
]
