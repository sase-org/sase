"""Pinned card head and two-row time strip for the Memory pane.

Pure renderers built only from :mod:`sase.pager.history_kit` (epic design
``plan:202610/memory_history_tui.md`` §9 and §4.2). Nothing here touches the
filesystem, git, or a mounted widget -- callers apply these renderables
from ``memory_panel_view``.

The head is the title row plus the path line (path at the shown version,
the pager's pill, its context, and chips). The strip is two reserved rows
below it: the band's first row, then the newest meaning row (dimmed) at
clean now, the meaning/cause row in the past, or blank but reserved.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from rich.console import RenderableType
from rich.text import Text

#: Card heights under this reserve one strip row instead of two
#: (``chrome_row_budget`` in the pager).
TIME_STRIP_FOLD_HEIGHT = 14

#: Reserved strip rows in the full and folded states.
TIME_STRIP_ROWS = 2
TIME_STRIP_FOLDED_ROWS = 1


@dataclass(frozen=True)
class TimeStripSnapshot:
    """One immutable card moment for the pinned head (now only)."""

    subject_id: str
    path_label: str
    timeline: dict[str, Any] | None
    now_epoch: int
    failed: bool = False
    failure_reason: str = ""


def subject_id_for_selector(raw_selector: str, *, is_strand: bool = False) -> str:
    """Return the band subject id for a panel selector."""
    selector = str(raw_selector or "")
    if is_strand:
        return f"strand:{selector}"
    if selector.endswith(".md") or "/" in selector:
        return f"note:{selector}"
    if ":" in selector:
        return f"strand:{selector}"
    return f"note:{selector}"


def _history_styles(theme: Any) -> Any:
    """Return the memoized kit styles for *theme*."""
    from sase.pager.history_kit import history_styles_for_theme

    return history_styles_for_theme(theme)


def get_time_strip_styles(theme: Any) -> Any:
    """Return the kit styles for *theme* (memoized per theme in the kit)."""
    return _history_styles(theme)


def _dirty_from_timeline(timeline: dict[str, Any] | None) -> bool:
    if not isinstance(timeline, dict):
        return False
    # The panel summary carries a precomputed dirty flag (the ordinal-0
    # pseudo row is filtered out before caching).
    try:
        if bool(timeline.get("dirty")):
            return True
    except Exception:
        pass
    try:
        from sase.pager.history_kit import dirty_now_from_timeline

        return bool(dirty_now_from_timeline(timeline))
    except Exception:
        return False


def _newest_row(timeline: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(timeline, dict):
        return None
    try:
        from sase.pager.history_kit import newest_committed_row

        return newest_committed_row(timeline)
    except Exception:
        return None


def _pill_state(
    timeline: dict[str, Any] | None,
    *,
    total_visible: int,
    now_epoch: int,
) -> dict[str, object] | None:
    """Return the pill/context state dict for a now card, if any."""
    if not isinstance(timeline, dict):
        return None
    try:
        from sase.pager.history_kit import format_age
    except Exception:
        format_age = None  # type: ignore[assignment]
    newest = _newest_row(timeline)
    dirty = _dirty_from_timeline(timeline)
    total = 0
    if newest is not None:
        try:
            total = int(newest.get("ordinal", 0) or 0)
        except (TypeError, ValueError):
            total = 0
    if total_visible > 0:
        total = max(total, int(total_visible))
    if total <= 0:
        versions = timeline.get("versions", ())
        if isinstance(versions, (list, tuple)):
            committed = [
                row
                for row in versions
                if isinstance(row, dict) and int(row.get("ordinal", 0) or 0) > 0
            ]
            total = len(committed)
    age = ""
    if newest is not None and format_age is not None:
        try:
            then = int(newest.get("committer_time", 0) or 0)
        except (TypeError, ValueError):
            then = 0
        if then:
            try:
                age = str(format_age(int(now_epoch), int(then)))
            except Exception:
                age = ""
    state: dict[str, object] = {
        "kind": "now",
        "ordinal": 0,
        "total": int(total),
        "dirty": bool(dirty),
        "tombstone": False,
        "age": age,
    }
    return state


def build_time_band_for_timeline(
    timeline: dict[str, Any] | None,
    *,
    subject_id: str,
    now_epoch: int = 0,
    loading: bool = False,
    current_ordinal: int = 0,
    moment: Any | None = None,
) -> Any | None:
    """Build the kit band model for a card (never recomputes numbers).

    *current_ordinal* 0 with no *moment* is the now card; a past pin
    passes its kit moment so the band shows the timeline row, meaning
    row, and tombstone chrome in the pager's own words.
    """
    from sase.pager.history_kit import build_time_band_data

    if timeline is None and not loading:
        return None
    epoch = int(now_epoch) or int(time.time())
    dirty = _dirty_from_timeline(timeline) if isinstance(timeline, dict) else False
    total_visible = 0
    if isinstance(timeline, dict):
        versions = timeline.get("versions", ())
        if isinstance(versions, (list, tuple)):
            total_visible = len(
                [
                    row
                    for row in versions
                    if isinstance(row, dict) and int(row.get("ordinal", 0) or 0) > 0
                ]
            )
    try:
        return build_time_band_data(
            subject_id=subject_id or "note:",
            timeline=timeline,
            current_ordinal=int(current_ordinal),
            dirty=dirty,
            loading=bool(loading),
            now_epoch=epoch,
            total_visible=int(total_visible),
            moment=moment,
        )
    except Exception:
        return None


def _render_path_line(
    path_label: str,
    *,
    pill: Text | None,
    context: Text | None,
    chips: list[Text] | None = None,
    width: int = 0,
) -> Text:
    """Build the card path line: path, pill, context, and chips.

    The path sheds from the left when narrow; the pill switches to
    shorter forms via its budget and is never cropped.
    """
    line = Text(no_wrap=True, overflow="crop")
    path = str(path_label or "")
    if width > 0 and len(path) > 0:
        # Reserve a rough budget for the pill/context; the pill itself
        # picks the longest form fitting its own budget.
        pill_budget = max(0, int(width) - len(path) - 4)
        if pill is not None and pill_budget < len(pill.plain):
            # Ellipsize the path from the left to protect the pill.
            keep = max(0, int(width) - len(pill.plain) - 8)
            if keep < len(path):
                path = "…" + path[-(keep - 1) :] if keep > 1 else "…"
    if path:
        line.append(path, style="dim")
    if pill is not None and pill.plain:
        if line.plain:
            line.append("   ")
        line.append_text(pill)
    if context is not None and context.plain:
        if line.plain:
            line.append("  ")
        line.append_text(context)
    for chip in chips or []:
        if chip.plain:
            line.append("  ")
            line.append_text(chip)
    return line


def _pill_for_state(
    state: dict[str, object] | None, styles: Any, *, budget: int
) -> Text | None:
    if state is None:
        return None
    try:
        from sase.pager.history_kit import history_badge

        return history_badge(None, state, styles, int(budget))
    except Exception:
        return None


def _context_for_state(state: dict[str, object] | None, styles: Any) -> Text | None:
    if state is None:
        return None
    try:
        from sase.pager.history_kit import history_context

        return history_context(None, state, styles)
    except Exception:
        return None


def render_card_head(
    path_label: str,
    snapshot: TimeStripSnapshot,
    styles: Any,
    *,
    width: int = 0,
    moment: Any | None = None,
    extra_chips: list[Text] | None = None,
) -> Text:
    """Build the path line for a card in the pager's words.

    Without *moment* this is the now card. A past pin passes its kit
    moment so the pill and context read ``⟲ PAST`` (or the tombstone)
    exactly as the pager renders them.
    """
    timeline = snapshot.timeline
    if timeline is None and not snapshot.failed:
        return Text(str(path_label or ""), style="dim")
    budget = max(0, int(width) - len(str(path_label or "")) - 6) if width else 80
    budget = max(int(budget), 8)
    if moment is not None:
        try:
            from sase.pager.history_kit import history_badge, history_context

            pill = history_badge(moment, None, styles, budget)
            context = history_context(moment, None, styles)
        except Exception:
            pill, context = None, None
    else:
        state = _pill_state(
            timeline if isinstance(timeline, dict) else None,
            total_visible=0,
            now_epoch=int(snapshot.now_epoch),
        )
        pill = _pill_for_state(state, styles, budget=budget)
        context = _context_for_state(state, styles)
    chips: list[Text] = []
    if isinstance(timeline, dict) and bool(timeline.get("is_template")):
        chips.append(Text("TEMPLATE", style="dim"))
    if snapshot.failed:
        chips.append(Text("stale", style="dim"))
    for chip in extra_chips or []:
        if chip is not None and chip.plain:
            chips.append(chip)
    return _render_path_line(
        str(path_label or ""), pill=pill, context=context, chips=chips, width=width
    )


def render_time_strip(
    data: Any | None,
    *,
    width: int,
    rows: int,
    styles: Any,
) -> Text:
    """Render the reserved strip rows from the kit band model.

    Covers every honest now state in the pager's words. At clean now
    row 2 is the newest version's meaning row, dimmed. Loading shows
    ``indexing…``; failures keep the last good band with a retry row.
    The result always reserves *rows* lines so the body never moves.
    """
    from sase.pager.history_kit import render_time_band

    width = max(0, int(width))
    rows = max(1, min(int(rows), TIME_STRIP_ROWS))
    blank = Text("", no_wrap=True)
    if width == 0:
        return blank
    if data is None:
        # No memo yet: the strip reserves its rows around indexing….
        band = build_time_band_for_timeline(None, subject_id="note:", loading=True)
        if band is None:
            indexing = Text("indexing…", style="dim")
        else:
            try:
                indexing = render_time_band(
                    band,
                    width=width,
                    rows=1,
                    styles=styles,
                )
            except Exception:
                indexing = Text("indexing…", style="dim")
        if rows == 1:
            return indexing
        out = Text(no_wrap=True)
        out.append_text(indexing)
        out.append("\n")
        return out
    try:
        mode = str(getattr(data, "mode", "") or "")
    except Exception:
        mode = ""
    if mode == "notice":
        try:
            first = render_time_band(data, width=width, rows=1, styles=styles)
        except Exception:
            first = Text("history unavailable", style="dim")
        if rows == 1:
            return first
        out = Text(no_wrap=True)
        out.append_text(first)
        out.append("\n")
        return out
    if mode == "now":
        try:
            first = render_time_band(data, width=width, rows=1, styles=styles)
        except Exception:
            first = Text("", no_wrap=True)
        if rows == 1:
            return first
        second = _newest_meaning_row(data, width=width, styles=styles)
        out = Text(no_wrap=True)
        out.append_text(first)
        out.append("\n")
        out.append_text(second)
        return out
    # Past/tombstone paths (kept for the stepping phase): the band owns
    # both rows.
    try:
        return render_time_band(data, width=width, rows=rows, styles=styles)
    except Exception:
        return Text("", no_wrap=True)


def _newest_meaning_row(data: Any, *, width: int, styles: Any) -> Text:
    """Return the dimmed newest-meaning row answering 'what changed last?'."""
    try:
        from dataclasses import replace

        from sase.pager.history_kit import meaning_row, time_band_targets

        newest = getattr(data, "newest", None)
        if newest is None:
            return Text("", no_wrap=True)
        proxy = replace(data, current=newest)  # type: ignore[arg-type]
        ordered = time_band_targets(data)
        row = meaning_row(proxy, ordered, {}, int(width), styles)
        if not row.plain:
            return Text("", no_wrap=True)
        # The whole row is dimmed: it answers, it does not announce.
        return Text(row.plain, style="dim", no_wrap=True, overflow="crop")
    except Exception:
        return Text("", no_wrap=True)


def time_strip_row_count(card_height: int) -> int:
    """Return the reserved strip rows for a card of *card_height* rows."""
    try:
        height = int(card_height)
    except (TypeError, ValueError):
        return TIME_STRIP_ROWS
    if height > 0 and height < TIME_STRIP_FOLD_HEIGHT:
        return TIME_STRIP_FOLDED_ROWS
    return TIME_STRIP_ROWS


def retry_text() -> Text:
    """Return the failure retry row shown with the last good snapshot."""
    return Text("history unavailable · r retry", style="dim")


__all__ = [
    "TIME_STRIP_FOLDED_ROWS",
    "TIME_STRIP_FOLD_HEIGHT",
    "TIME_STRIP_ROWS",
    "TimeStripSnapshot",
    "build_time_band_for_timeline",
    "get_time_strip_styles",
    "render_card_head",
    "render_time_strip",
    "retry_text",
    "subject_id_for_selector",
    "time_strip_row_count",
]
