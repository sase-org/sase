"""Shared card-moment builder for the Memory pane time travel.

This module is private; the names it defines are public so the
``memory_pane_time_*`` sibling modules can share them without
importing ``_``-prefixed names across modules.
"""

from __future__ import annotations

from typing import Any


def moment_for_card(
    timeline: dict[str, Any] | None,
    *,
    subject_id: str,
    pin_ordinal: int,
    view: str = "read",
) -> Any | None:
    """Return the kit moment for *pin_ordinal* (0 means now), or ``None``.

    *view* selects the read body or its change: ``"diff"`` fills in the
    moment's own ``(base, target)`` endpoints through the pager's
    endpoint rules, so callers never re-derive them. Never raises:
    ``None`` means the card renders as it would with no history
    (fail-open per §5.4 rule 4).
    """
    if not isinstance(timeline, dict):
        return None
    if view not in ("read", "diff"):
        view = "read"
    try:
        from dataclasses import replace as _replace

        from sase.pager.history_kit import (
            build_moment,
            committed_pin_for_ordinal,
            dirty_now_from_timeline,
            is_deleted_row,
            live_pin_for_subject,
            visible_ordinals_for_timeline,
        )

        versions = timeline.get("versions", ())
        rows = [
            row
            for row in (versions if isinstance(versions, (list, tuple)) else ())
            if isinstance(row, dict) and int(row.get("ordinal", 0) or 0) > 0
        ]
        if not rows:
            return None
        visible = visible_ordinals_for_timeline(timeline)
        pinned_row: dict[str, Any] | None = None
        for row in rows:
            try:
                if int(row.get("ordinal", 0) or 0) == int(pin_ordinal):
                    pinned_row = row
                    break
            except (TypeError, ValueError):
                continue
        if int(pin_ordinal) <= 0:
            pin = live_pin_for_subject(subject_id)
            if view == "diff":
                pin = _replace(pin, view="diff")
            status = "live"
            # Summaries filter out the ordinal-0 pseudo row before
            # caching, so they carry a precomputed `dirty` flag next to
            # the wire the kit reads.
            if bool(timeline.get("dirty", False)) or bool(
                dirty_now_from_timeline(timeline)
            ):
                status = "dirty-now"
        else:
            commit = None
            blob = None
            if pinned_row is not None:
                raw_commit = pinned_row.get("commit")
                commit = str(raw_commit) if isinstance(raw_commit, str) else None
                raw_blob = pinned_row.get("blob_oid")
                blob = str(raw_blob) if isinstance(raw_blob, str) else None
            pin = committed_pin_for_ordinal(
                subject_id,
                int(pin_ordinal),
                commit=commit,
                blob_oid=blob,
                view=view,  # type: ignore[arg-type]
            )
            status = (
                "tombstone"
                if (pinned_row is not None and bool(is_deleted_row(pinned_row)))
                else "live"
            )
        meta = timeline.get("meta", {})
        return build_moment(
            rows=tuple(rows),
            meta=meta if isinstance(meta, dict) else {},
            visible_ordinals=tuple(visible),
            pin=pin,
            status=status,
        )
    except Exception:
        return None


__all__ = ["moment_for_card"]
