"""One version-identity model for pager history surfaces.

Pure and Textual-free: no IO, no clock, no memory imports. Every history
surface (subject chip, time band, footer, picker, trail, help) reads step
destinations, numbering, and dates from :class:`VersionMoment`, so the
surfaces can never disagree about which version is shown.

Conventions (shared with the memory provider):

* ``0`` means the live worktree (``now``); positive ordinals are
  committed versions. In a ``diff`` pair the base ``0`` means the empty
  base (the oldest version's own change) while a target ``0`` means now.
* ``newest`` (``N``) is the newest committed ordinal, hidden versions
  included. Hidden versions are skipped while stepping but never
  renumbered, so ``vK`` stays a stable identifier.
* A clean now *is* the newest version (``now ≡ vN``) when the
  timeline's ``worktree_oid``, ``head_oid``, and the newest row's
  ``blob_oid`` are all present and equal. Any missing or differing OID
  falls back to treating now and vN as separate stops.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

MomentKind = Literal["loading", "now", "now_dirty", "past", "deleted"]
MomentView = Literal["read", "diff"]
StepIntent = Literal["older", "newer", "first", "now"]

#: Pseudo-version classes on ordinal-0 timeline rows.
_DIRTY_CLASSES = ("uncommitted", "staged")

#: Memory-history subject-id prefixes (``note:``, ``web:`` ...). Kept
#: here so pager core can name them without importing memory modules.
MEMORY_SUBJECT_PREFIXES = ("note:", "web:", "strand:", "instructions:")


@dataclass(frozen=True, slots=True)
class VersionMoment:
    """One reading moment: which version is shown and where keys go.

    ``ordinal`` is the displayed version: ``newest`` when ``kind`` is
    ``"now"`` and now is the newest version, ``0`` for a dirty or
    detached now, the tombstone ordinal when ``kind`` is ``"deleted"``.
    ``older``/``newer``/``first``/``to_now`` are step destinations
    (``None`` means a boundary, ``0`` means now).
    """

    kind: MomentKind
    ordinal: int
    newest: int
    now_matches_newest: bool
    view: MomentView
    diff: tuple[int, int] | None
    committed_time: int | None
    commit: str | None
    commit_subject: str | None
    path_at_version: str | None
    newer_count: int
    older: int | None
    newer: int | None
    first: int | None
    to_now: int | None
    worktree_dirty: bool = False


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _as_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _committed_rows(rows: object) -> dict[int, dict[str, Any]]:
    """Index committed timeline rows by ordinal (pseudo rows excluded)."""
    indexed: dict[int, dict[str, Any]] = {}
    if not isinstance(rows, (list, tuple)):
        return indexed
    for row in rows:
        if not isinstance(row, dict):
            continue
        ordinal = _as_int(row.get("ordinal"))
        if ordinal > 0 and ordinal not in indexed:
            indexed[ordinal] = row
    return indexed


def _rows_show_dirty(rows: object) -> bool:
    """Return whether ordinal-0 rows report uncommitted or staged edits."""
    if not isinstance(rows, (list, tuple)):
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _as_int(row.get("ordinal")) != 0:
            continue
        if str(row.get("class", "") or "") in _DIRTY_CLASSES:
            return True
    return False


def _row_is_tombstone(row: dict[str, Any]) -> bool:
    return str(row.get("class", "") or "") == "deleted"


def _provenance_subject(row: dict[str, Any]) -> str | None:
    provenance = row.get("provenance")
    if isinstance(provenance, dict):
        return _as_str(provenance.get("subject"))
    return None


def build_moment(
    *,
    rows: object = (),
    meta: object = None,
    visible_ordinals: object = (),
    pin: object = None,
    status: object = "live",
) -> VersionMoment:
    """Build the reading moment for one section's history state.

    ``rows`` is the loaded timeline (committed plus pseudo rows),
    ``meta`` the timeline metadata with ``worktree_oid``/``head_oid``,
    ``visible_ordinals`` the ordinals stepping may stop at, ``pin`` the
    current :class:`VersionPin`, and ``status`` the screen status
    (``live``, ``dirty-now``, ``tombstone``). Inputs are coerced, so a
    ragged wire still yields a moment; callers fail open on exceptions.
    """
    committed = _committed_rows(rows)
    meta_map = dict(meta) if isinstance(meta, dict) else {}
    visible: list[int] = []
    if isinstance(visible_ordinals, (list, tuple)):
        for entry in visible_ordinals:
            ordinal = _as_int(entry)
            if ordinal > 0 and ordinal in committed and ordinal not in visible:
                visible.append(ordinal)
    visible.sort()

    pin_ordinal = _as_int(getattr(pin, "ordinal", 0))
    raw_view = str(getattr(pin, "view", "read") or "read")
    view: MomentView = cast(
        MomentView, raw_view if raw_view in ("read", "diff") else "read"
    )
    pin_base: int | None = None
    try:
        compare_base = getattr(pin, "compare_base", None)
        pin_base = int(compare_base) if compare_base is not None else None
    except (TypeError, ValueError):
        pin_base = None
    pin_explicit = bool(getattr(pin, "explicit_base", False))

    if not committed:
        return VersionMoment(
            kind="loading",
            ordinal=0,
            newest=0,
            now_matches_newest=False,
            view=view,
            diff=None,
            committed_time=None,
            commit=None,
            commit_subject=None,
            path_at_version=None,
            newer_count=0,
            older=None,
            newer=None,
            first=None,
            to_now=None,
        )

    newest = max(committed)
    newest_row = committed[newest]
    newest_blob = _as_str(newest_row.get("blob_oid"))
    worktree_oid = _as_str(meta_map.get("worktree_oid"))
    head_oid = _as_str(meta_map.get("head_oid"))

    dirty = str(status or "") == "dirty-now" or _rows_show_dirty(rows)
    # A dirty now (including staged-only edits whose worktree equals HEAD)
    # never coincides with the newest version: `(` must step onto HEAD.
    now_matches_newest = bool(
        newest_blob
        and worktree_oid
        and head_oid
        and worktree_oid == head_oid == newest_blob
        and not dirty
    )
    tombstone_ordinal: int | None = None
    if str(status or "") == "tombstone" or _row_is_tombstone(newest_row):
        tombstone_ordinal = newest

    # A pin to the newest ordinal on a now ≡ vN subject reads now.
    effective = pin_ordinal
    if effective == newest and now_matches_newest:
        effective = 0

    if tombstone_ordinal is not None and effective in (0, tombstone_ordinal):
        kind: MomentKind = "deleted"
    elif effective == 0:
        kind = "now_dirty" if dirty else "now"
    else:
        kind = "past"

    if kind == "deleted":
        shown_ordinal = tombstone_ordinal or newest
    elif kind == "now" and now_matches_newest:
        shown_ordinal = newest
    elif kind == "past":
        shown_ordinal = effective
    else:
        shown_ordinal = 0

    shown_row = committed.get(shown_ordinal) if shown_ordinal > 0 else None
    if shown_row is None:
        committed_time: int | None = None
        commit: str | None = None
        commit_subject: str | None = None
        path_at_version: str | None = None
    else:
        raw_time = _as_int(shown_row.get("committer_time"))
        committed_time = raw_time or None
        commit = _as_str(shown_row.get("commit"))
        commit_subject = _provenance_subject(shown_row)
        current_path = _as_str(meta_map.get("path"))
        row_path = _as_str(shown_row.get("path")) or _as_str(
            shown_row.get("source_path")
        )
        path_at_version = (
            row_path if row_path and current_path and row_path != current_path else None
        )

    if kind in ("now", "now_dirty"):
        newer_count = 0
    elif kind == "deleted":
        newer_count = 0
    else:
        newer_count = sum(1 for ordinal in visible if ordinal > effective)

    # Stepping skips hidden versions; on a now ≡ vN subject the newest
    # ordinal is now itself, so it is not a stop.
    navigable = [
        ordinal for ordinal in visible if not (now_matches_newest and ordinal == newest)
    ]

    if kind in ("now", "now_dirty"):
        older = max(navigable) if navigable else None
        newer: int | None = None
        to_now: int | None = None
    elif kind == "deleted":
        below = [ordinal for ordinal in navigable if ordinal < shown_ordinal]
        older = max(below) if below else None
        newer = None
        to_now = shown_ordinal
    else:
        below = [ordinal for ordinal in navigable if ordinal < effective]
        above = [ordinal for ordinal in navigable if ordinal > effective]
        older = max(below) if below else None
        if above:
            newer = min(above)
        elif now_matches_newest:
            newer = 0
        elif newest > effective:
            newer = newest
        else:
            newer = 0
        if tombstone_ordinal is not None:
            to_now = tombstone_ordinal
        else:
            to_now = 0

    first = min(visible) if visible else None
    diff: tuple[int, int] | None = None
    if view == "diff":
        diff = diff_endpoints(
            target=0 if kind in ("now", "now_dirty") else shown_ordinal,
            steppable=navigable,
            newest=newest,
            dirty=kind == "now_dirty",
            explicit_base=pin_base if pin_explicit else None,
        )

    return VersionMoment(
        kind=kind,
        ordinal=shown_ordinal,
        newest=newest,
        now_matches_newest=now_matches_newest,
        view=view,
        diff=diff,
        committed_time=committed_time,
        commit=commit,
        commit_subject=commit_subject,
        path_at_version=path_at_version,
        newer_count=newer_count,
        older=older,
        newer=newer,
        first=first,
        to_now=to_now,
        worktree_dirty=dirty,
    )


def diff_endpoints(
    *,
    target: int,
    steppable: list[int],
    newest: int,
    dirty: bool,
    explicit_base: int | None,
) -> tuple[int, int] | None:
    """Return the ``(base, target)`` pair for a diff view, oldest first.

    An explicit picker base is normalized to read forward in time; a
    base equal to the target falls back to the default endpoints.
    """
    if explicit_base is not None and explicit_base != target:
        if target == 0:
            # A picker base against the worktree keeps now as the target.
            return (explicit_base, 0)
        return (min(explicit_base, target), max(explicit_base, target))
    if target > 0:
        below = [ordinal for ordinal in steppable if ordinal < target]
        return (max(below) if below else 0, target)
    if dirty:
        return (newest, 0)
    below = [ordinal for ordinal in steppable if ordinal < newest]
    return (max(below) if below else 0, newest)


def _current_position(moment: VersionMoment) -> int:
    """Return the live ordinal for *moment* (``0`` means now)."""
    if moment.kind in ("now", "now_dirty"):
        return 0
    return moment.ordinal


def canonical_ordinal(ordinal: int, moment: VersionMoment) -> int:
    """Return ``0`` when *ordinal* is the newest on a now ≡ vN subject."""
    if moment.newest > 0 and ordinal == moment.newest and moment.now_matches_newest:
        return 0
    return ordinal


def step_target(moment: VersionMoment, intent: StepIntent) -> int | None:
    """Return the destination ordinal for *intent*, or ``None``.

    ``None`` means a boundary: there is nowhere to go, or the raw
    destination canonicalizes back to the current position.
    """
    if intent == "older":
        raw = moment.older
    elif intent == "newer":
        raw = moment.newer
    elif intent == "first":
        raw = moment.first
    elif intent == "now":
        raw = moment.to_now
    else:
        raise ValueError(f"unknown step intent: {intent!r}")
    if raw is None:
        return None
    if canonical_ordinal(raw, moment) == _current_position(moment):
        return None
    return raw


def boundary_notice(moment: VersionMoment, intent: StepIntent) -> str:
    """Return the boundary notice naming where stepping stopped."""
    if moment.kind == "deleted":
        return f"Already at v{moment.ordinal}, the deletion."
    if intent in ("newer", "now"):
        if moment.kind in ("now", "now_dirty"):
            if moment.now_matches_newest:
                return f"Already at now (≡ v{moment.newest})."
            return "Already at now."
        return f"Already at v{moment.ordinal}, the newest version."
    if moment.kind in ("now", "now_dirty"):
        if moment.now_matches_newest:
            return f"now ≡ v{moment.newest} is the only version."
        return "Already at now."
    return f"Already at v{moment.ordinal}, the oldest version."


def _pin_key(pin: object) -> tuple[object, ...] | None:
    if pin is None:
        return None
    return (
        _as_str(getattr(pin, "subject_id", None)),
        _as_int(getattr(pin, "ordinal", 0)),
        str(getattr(pin, "selector", "") or ""),
        _as_str(getattr(pin, "commit", None)),
        _as_str(getattr(pin, "blob_oid", None)),
        str(getattr(pin, "view", "read") or "read"),
        getattr(pin, "compare_base", None),
        bool(getattr(pin, "explicit_base", False)),
    )


def _timeline_fingerprint(rows: object, meta: dict[str, Any]) -> tuple[object, ...]:
    """Return a cheap identity for one loaded timeline (append-only)."""
    items: list[tuple[int, str | None, str | None]] = []
    if isinstance(rows, (list, tuple)):
        for row in rows:
            if not isinstance(row, dict):
                continue
            items.append(
                (
                    _as_int(row.get("ordinal")),
                    _as_str(row.get("commit")),
                    _as_str(row.get("blob_oid")),
                )
            )
    newest_item: tuple[int, str | None, str | None] | None = None
    oldest_item: tuple[int, str | None, str | None] | None = None
    positives = sorted(item for item in items if item[0] > 0)
    if positives:
        newest_item = positives[-1]
        oldest_item = positives[0]
    return (
        len(items),
        newest_item,
        oldest_item,
        _as_str(meta.get("worktree_oid")),
        _as_str(meta.get("head_oid")),
    )


def moment_for_state(state: object) -> VersionMoment | None:
    """Return the cached moment for a history state, rebuilding on change.

    The moment is rebuilt once per (generation, pin, status, timeline
    identity) and reused across repaints; the subject line repaints on
    scroll, so it must never rebuild per paint. Never raises: ``None``
    means surfaces render as they would with no history.
    """
    try:
        rows = getattr(state, "timeline", ())
        meta = getattr(state, "timeline_meta", None)
        meta_map = dict(meta) if isinstance(meta, dict) else {}
        key = (
            getattr(state, "generation", 0),
            _pin_key(getattr(state, "current_pin", None)),
            str(getattr(state, "status", "") or ""),
            _timeline_fingerprint(rows, meta_map),
        )
        if getattr(state, "cached_moment_key", None) == key:
            cached = getattr(state, "cached_moment", None)
            if isinstance(cached, VersionMoment):
                return cached
        moment = build_moment(
            rows=rows,
            meta=meta_map,
            visible_ordinals=getattr(state, "visible_ordinals", ()),
            pin=getattr(state, "current_pin", None),
            status=getattr(state, "status", "live"),
        )
        try:
            state.cached_moment = moment  # type: ignore[attr-defined]
            state.cached_moment_key = key  # type: ignore[attr-defined]
        except Exception:
            pass
        return moment
    except Exception:
        return None


__all__ = [
    "MEMORY_SUBJECT_PREFIXES",
    "MomentKind",
    "MomentView",
    "StepIntent",
    "VersionMoment",
    "boundary_notice",
    "build_moment",
    "canonical_ordinal",
    "diff_endpoints",
    "moment_for_state",
    "step_target",
]
