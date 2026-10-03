"""Rail-glance feed parsing: recency map and deleted subjects.

Pure helpers behind the phase rail-glance Notes rail: one ``subjects()``
plus one ``feed()`` per scope load is reduced here to a ``{path:
(class, committer_time)}`` recency map and the trailing ``DELETED``
group. Feed iteration is defensive: a malformed feed omits the column
and keeps the rail. Never raises.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._memory_pane_rail_glance_shared import DeletedSubject


def _feed_changesets(feed: Any) -> tuple[dict[str, Any], ...]:
    """Return the feed's changesets, newest first, or ``()`` when malformed."""
    if not isinstance(feed, dict):
        return ()
    changesets = feed.get("changesets", ())
    if not isinstance(changesets, (list, tuple)):
        return ()
    return tuple(row for row in changesets if isinstance(row, dict))


def _feed_entries(changeset: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return one changeset's authored plus consequence entries."""
    entries: list[dict[str, Any]] = []
    for key in ("authored", "consequences"):
        rows = changeset.get(key, ())
        if isinstance(rows, (list, tuple)):
            entries.extend(row for row in rows if isinstance(row, dict))
    return tuple(entries)


def _entry_time(changeset: dict[str, Any]) -> int | None:
    """Return one changeset's committer time, or ``None`` when unusable."""
    try:
        moment = int(changeset.get("committer_time", 0) or 0)
    except (TypeError, ValueError):
        return None
    return moment if moment > 0 else None


def _display_for_entry(
    subject_id: str, path: str, displays: dict[str, str] | None
) -> str:
    """Return the DELETED row name for one deleted feed entry."""
    if displays is not None:
        try:
            display = displays.get(subject_id, "")
            if display:
                return str(display)
        except Exception:
            pass
    try:
        return Path(path).stem or path
    except Exception:
        return path


def build_recency_map(feed: Any) -> dict[str, tuple[str, int]]:
    """Return ``{path: (class, committer_time)}`` for the newest entry.

    The feed arrives newest first, so the first entry seen per path
    wins. Entries without a path or a usable time are skipped. Notes,
    web descriptors, and strands all match by file path, which is what
    the rail rows carry. Never raises: a malformed feed yields ``{}``,
    omitting the column while the rail keeps working.
    """
    recency: dict[str, tuple[str, int]] = {}
    try:
        for changeset in _feed_changesets(feed):
            moment = _entry_time(changeset)
            if moment is None:
                continue
            for entry in _feed_entries(changeset):
                path = entry.get("path", "")
                if not isinstance(path, str) or not path or path in recency:
                    continue
                class_name = entry.get("class", "")
                if not isinstance(class_name, str) or not class_name:
                    continue
                recency[path] = (class_name, moment)
    except Exception:
        return {}
    return recency


def subject_displays(subjects: Any) -> dict[str, str]:
    """Return ``{subject_id: display_name}`` from a subjects wire dict."""
    displays: dict[str, str] = {}
    try:
        rows = subjects.get("subjects", ()) if isinstance(subjects, dict) else ()
    except Exception:
        return {}
    if not isinstance(rows, (list, tuple)):
        return {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        subject_id = row.get("id", "")
        display = row.get("display_name", "")
        if isinstance(subject_id, str) and subject_id and isinstance(display, str):
            if display:
                displays[subject_id] = display
    return displays


def collect_deleted_subjects(
    feed: Any, *, displays: dict[str, str] | None = None
) -> tuple[DeletedSubject, ...]:
    """Return subjects whose latest entry is a deletion, newest first.

    The feed arrives newest first, so the first entry seen per
    subject id is its latest: a subject deleted and later recreated
    is never listed. Never raises.
    """
    latest: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    try:
        for changeset in _feed_changesets(feed):
            moment = _entry_time(changeset)
            if moment is None:
                continue
            for entry in _feed_entries(changeset):
                subject_id = entry.get("subject_id", "")
                if not isinstance(subject_id, str) or not subject_id:
                    continue
                if subject_id not in latest:
                    latest[subject_id] = (changeset, entry)
    except Exception:
        return ()
    deleted: list[DeletedSubject] = []
    for subject_id, (changeset, entry) in latest.items():
        try:
            if entry.get("class") != "deleted":
                continue
            path = entry.get("path", "")
            if not isinstance(path, str) or not path:
                continue
            moment = _entry_time(changeset)
            if moment is None:
                continue
            try:
                ordinal = int(entry.get("ordinal", 0) or 0)
            except (TypeError, ValueError):
                ordinal = 0
            commit = entry.get("commit", changeset.get("commit", ""))
            deleted.append(
                DeletedSubject(
                    subject_id=subject_id,
                    path=path,
                    display=_display_for_entry(subject_id, path, displays),
                    committer_time=moment,
                    ordinal=ordinal,
                    commit=str(commit) if isinstance(commit, str) else "",
                )
            )
        except Exception:
            continue
    return tuple(deleted)


__all__ = [
    "build_recency_map",
    "collect_deleted_subjects",
    "subject_displays",
]
