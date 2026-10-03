"""Review-watermark presentation for the Changes lens (``watermark-tui``).

Pure, Textual-free helpers over the ``review_state`` wire
(``HistoryService.review_state``): per-scope review entries, the lens
header chip (``● N new`` / ``not reviewed yet · m to mark`` /
``✓ nothing new``), the unreviewed-row predicate behind the ``●``
rail dots, the ``marked N changesets reviewed`` toast, and the Config
hub ``MEMORY`` sub-tab badge labels (``●N``). The Changes lens mixin
(:mod:`sase.ace.tui.modals.memory_pane_changes_lens`) and the Config
hub pane own all fetching, workers, and widgets; this module never
touches git, the service, or the screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class ScopeReview:
    """One scope's review watermark plus its exact N-new count from core."""

    scope_key: str
    new_count: int
    watermark_time: int
    has_watermark: bool
    newest_commit: str


def review_entries(review_state: dict[str, Any] | None) -> tuple[ScopeReview, ...]:
    """Normalize a ``review_state`` wire into per-scope entries.

    ``None``, a non-dict, or a store-shaped failure yields ``()``: the
    lens then omits the chip and the dots (fail-open). Never raises.
    """
    if not isinstance(review_state, dict):
        return ()
    try:
        raw_scopes = review_state.get("scopes", ())
    except Exception:
        return ()
    if not isinstance(raw_scopes, (list, tuple)):
        return ()
    entries: list[ScopeReview] = []
    for raw in raw_scopes:
        if not isinstance(raw, dict):
            continue
        try:
            scope_key = str(raw.get("scope_key", "") or "")
        except Exception:
            continue
        if not scope_key:
            continue
        try:
            new_count = max(0, int(raw.get("new_count", 0) or 0))
        except (TypeError, ValueError):
            new_count = 0
        try:
            newest_commit = str(raw.get("newest_commit", "") or "")
        except Exception:
            newest_commit = ""
        watermark = raw.get("watermark")
        if isinstance(watermark, dict):
            try:
                watermark_time = int(watermark.get("committer_time", 0) or 0)
            except (TypeError, ValueError):
                watermark_time = 0
            has_watermark = True
        else:
            watermark_time, has_watermark = 0, False
        entries.append(
            ScopeReview(
                scope_key=scope_key,
                new_count=new_count,
                watermark_time=watermark_time,
                has_watermark=has_watermark,
                newest_commit=newest_commit,
            )
        )
    return tuple(entries)


def review_chip(entries: tuple[ScopeReview, ...]) -> str:
    """Return the Changes header review chip for *entries*.

    ``● N new`` names core's exact count summed across the shown
    scopes; a never-marked scope points at ``m``; a fully reviewed
    lens confirms ``✓ nothing new``; ``""`` means the review state is
    unavailable and the header omits the chip. Never raises.
    """
    try:
        listed = tuple(entries or ())
    except Exception:
        return ""
    if not listed:
        return ""
    try:
        if any(not entry.has_watermark for entry in listed):
            return "not reviewed yet · m to mark"
        total = sum(max(0, int(entry.new_count or 0)) for entry in listed)
    except Exception:
        return ""
    if total == 1:
        return "● 1 new"
    if total > 1:
        return f"● {total} new"
    return "✓ nothing new"


def entries_by_scope(
    entries: tuple[ScopeReview, ...],
) -> dict[str, ScopeReview]:
    """Index review entries by scope key (first entry wins). Never raises."""
    indexed: dict[str, ScopeReview] = {}
    try:
        for entry in entries or ():
            indexed.setdefault(entry.scope_key, entry)
    except Exception:
        pass
    return indexed


def changeset_is_unreviewed(
    view: Any,
    indexed: Mapping[str, ScopeReview],
) -> bool:
    """Return whether one changeset view carries the ``●`` dot.

    A scope never marked dots every row; otherwise a changeset is new
    when its committer time is strictly after the watermark's (the
    watermark commit itself, at an equal stamp, stays undotted).
    Unknown scopes and undated changesets never dot. This mirrors
    core's committer-time fallback; the header count stays exact.
    Never raises.
    """
    try:
        scope_key = str(getattr(view, "scope_key", "") or "")
        entry = indexed.get(scope_key)
        if entry is None:
            return False
        if not entry.has_watermark:
            return True
        try:
            epoch = int(getattr(view, "committer_time", 0) or 0)
        except (TypeError, ValueError):
            return False
        if not epoch:
            return False
        return epoch > int(entry.watermark_time or 0)
    except Exception:
        return False


def feed_newest_commit(views: tuple[Any, ...], scope_key: str) -> str:
    """Return the newest fetched changeset commit for *scope_key*.

    Falls back to the feed when a review entry carries no
    ``newest_commit``. Ties keep feed order (newest first). ``""``
    means the scope has no fetched changesets. Never raises.
    """
    best_commit = ""
    best_time = -1
    try:
        for view in views or ():
            try:
                if str(getattr(view, "scope_key", "") or "") != scope_key:
                    continue
                commit = str(getattr(view, "commit", "") or "")
            except Exception:
                continue
            if not commit:
                continue
            try:
                epoch = int(getattr(view, "committer_time", 0) or 0)
            except (TypeError, ValueError):
                epoch = 0
            if epoch > best_time:
                best_time, best_commit = epoch, commit
    except Exception:
        pass
    return best_commit


def mark_reviewed_toast(scope_label: str, count: int) -> str:
    """Return the ``marked N changesets reviewed · <scope>`` toast."""
    try:
        total = max(0, int(count or 0))
    except (TypeError, ValueError):
        total = 0
    noun = "changeset" if total == 1 else "changesets"
    try:
        label = str(scope_label or "")
    except Exception:
        label = ""
    if label:
        return f"marked {total} {noun} reviewed · {label}"
    return f"marked {total} {noun} reviewed"


def memory_badge_count(entries: tuple[ScopeReview, ...], scope_key: str) -> int | None:
    """Return the ``●N`` count for *scope_key*, or ``None`` to hide it.

    Hidden at zero, with no watermark, and when the scope is absent:
    the Config hub sub-tab never badges those states. Never raises.
    """
    try:
        for entry in entries or ():
            if entry.scope_key != scope_key:
                continue
            if not entry.has_watermark:
                return None
            total = int(entry.new_count or 0)
            return total if total > 0 else None
    except Exception:
        return None
    return None


def memory_badge_label(label: str, count: int | None) -> str:
    """Return *label* with the ``●N`` badge prepended, or bare when hidden."""
    try:
        text = str(label or "")
    except Exception:
        text = ""
    try:
        total = int(count) if count is not None else 0
    except (TypeError, ValueError):
        total = 0
    if total > 0:
        return f"●{total} {text}".rstrip()
    return text


__all__ = [
    "ScopeReview",
    "changeset_is_unreviewed",
    "entries_by_scope",
    "feed_newest_commit",
    "mark_reviewed_toast",
    "memory_badge_count",
    "memory_badge_label",
    "review_chip",
    "review_entries",
]
