"""History pill, context, and time-verb rendering for the pager chrome.

No Textual imports here: everything is a plain function from document/section
state to a Rich :class:`~rich.text.Text`, so the shapes are unit-testable
without booting an App.
"""

from __future__ import annotations

from typing import Any, cast

from rich.cells import cell_len
from rich.text import Text


def state_moment(state: dict[str, object] | None) -> Any | None:
    """Return the ``VersionMoment`` carried by a chrome state dict."""
    if not isinstance(state, dict):
        return None
    moment = state.get("moment")
    if moment is not None and hasattr(moment, "kind"):
        return moment
    return None


def _moment_kind(moment: Any | None, state: dict[str, object] | None) -> str:
    if moment is not None:
        return str(getattr(moment, "kind", "") or "")
    if isinstance(state, dict):
        if bool(state.get("tombstone")):
            return "deleted"
        if bool(state.get("dirty")):
            return "now_dirty"
        ordinal = int(cast(Any, state.get("ordinal", 0)) or 0)
        if ordinal > 0 and str(state.get("kind", "") or "") != "now":
            return "past"
        return "now"
    return ""


def _moment_numbers(
    moment: Any | None, state: dict[str, object] | None
) -> tuple[int, int]:
    """Return ``(shown_ordinal, newest)`` for a pill or context."""
    if moment is not None:
        return (
            int(getattr(moment, "ordinal", 0) or 0),
            int(getattr(moment, "newest", 0) or 0),
        )
    if isinstance(state, dict):
        return (
            int(cast(Any, state.get("ordinal", 0)) or 0),
            int(cast(Any, state.get("total", 0)) or 0),
        )
    return (0, 0)


def _pill_capsule(label: str, *, bg: str, fg: str) -> Text:
    """Render one solid pill capsule with a padding cell on each side."""
    return Text(f" {label} ", style=f"bold {fg} on {bg}")


def pill_forms(
    moment: Any | None, state: dict[str, object] | None, styles: Any
) -> list[Text]:
    """Return the pill's fixed forms, longest first (never cropped)."""
    kind = _moment_kind(moment, state)
    if kind not in ("past", "now", "now_dirty", "deleted"):
        return []
    ordinal, newest = _moment_numbers(moment, state)
    if kind == "past":
        return [
            _pill_capsule(
                f"⟲ PAST · v{ordinal} of {newest}",
                bg=styles.past_pill_bg,
                fg=styles.past_pill_fg,
            ),
            _pill_capsule(
                f"⟲ PAST · v{ordinal}/{newest}",
                bg=styles.past_pill_bg,
                fg=styles.past_pill_fg,
            ),
            _pill_capsule(
                f"⟲ v{ordinal}/{newest}", bg=styles.past_pill_bg, fg=styles.past_pill_fg
            ),
            _pill_capsule(
                f"⟲ v{ordinal}", bg=styles.past_pill_bg, fg=styles.past_pill_fg
            ),
        ]
    if kind == "now":
        return [
            _pill_capsule(
                f"● NOW · v{newest}", bg=styles.now_pill_bg, fg=styles.now_pill_fg
            ),
            _pill_capsule("● NOW", bg=styles.now_pill_bg, fg=styles.now_pill_fg),
        ]
    if kind == "now_dirty":
        return [
            _pill_capsule(
                "◌ NOW · uncommitted",
                bg=styles.uncommitted_pill_bg,
                fg=styles.uncommitted_pill_fg,
            ),
            _pill_capsule(
                "◌ NOW", bg=styles.uncommitted_pill_bg, fg=styles.uncommitted_pill_fg
            ),
        ]
    if kind == "deleted":
        return [
            _pill_capsule(
                f"✖ DELETED · v{ordinal}",
                bg=styles.deleted_pill_bg,
                fg=styles.deleted_pill_fg,
            ),
            _pill_capsule(
                "✖ DELETED", bg=styles.deleted_pill_bg, fg=styles.deleted_pill_fg
            ),
            _pill_capsule(
                f"✖ v{ordinal}", bg=styles.deleted_pill_bg, fg=styles.deleted_pill_fg
            ),
        ]
    return []


def history_badge(
    moment: Any | None,
    state: dict[str, object] | None,
    styles: Any,
    budget: int,
) -> Text | None:
    """Render the state pill for *moment*, longest form fitting *budget*.

    The pill is a solid capsule — one padding cell on each side, bold
    text — and is never cropped: when nothing fits, the shortest form
    is returned anyway. Without a moment, *state* supplies the same
    numbers in dict form.
    """
    forms = pill_forms(moment, state, styles)
    if not forms:
        return None
    budget = max(int(budget), 0)
    for form in forms:
        if cell_len(form.plain) <= budget:
            return form
    return forms[-1]


def history_context(
    moment: Any | None,
    state: dict[str, object] | None,
    styles: Any,
    *,
    short: bool = False,
) -> Text | None:
    """Render the dim context after the pill for *moment*.

    In the diff view the context gains ``Δ vA → vB`` with the base in
    the delete tone, ``→`` dim, and the target in the insert tone. The
    short form keeps only that ``Δ`` segment; every other view shortens
    to nothing. When the time band is folded away, the past and deleted
    context gains the short date, because the band's absolute date is
    not on screen.
    """
    kind = _moment_kind(moment, state)
    if kind in ("", "loading"):
        return None
    age = str(state.get("age", "") or "") if isinstance(state, dict) else ""
    # The short date joins the context only when the time band is folded
    # away: otherwise the band's absolute date is already on screen.
    band_folded = bool(isinstance(state, dict) and state.get("band_folded"))
    delta = _delta_segment(moment, state, styles)
    context = Text()
    if kind == "now":
        context.append("latest", style="dim")
        if age:
            context.append(" · ", style="dim")
            context.append(age, style="dim")
    elif kind == "now_dirty":
        _ordinal, newest = _moment_numbers(moment, state)
        context.append(f"on top of v{newest}", style=styles.uncommitted)
    elif kind == "past":
        date = _short_date(moment) if band_folded else ""
        if date:
            context.append(date, style=styles.past)
            context.append(" · ", style="dim")
        if age:
            context.append(age, style=styles.past)
        elif not date:
            context.append(f"v{_moment_numbers(moment, state)[0]}", style="dim")
    elif kind == "deleted":
        ordinal, _newest = _moment_numbers(moment, state)
        date = _short_date(moment) if band_folded else ""
        if date:
            context.append(date, style=styles.tombstone)
            context.append(" · ", style="dim")
        if age:
            context.append(age, style=styles.tombstone)
        else:
            context.append(f"v{ordinal}", style=styles.tombstone)
    else:  # pragma: no cover - unknown kinds fail open to no context
        return None
    if delta is not None:
        if short:
            return delta
        if context.plain:
            context.append(" · ", style="dim")
        context.append_text(delta)
    if short:
        return None
    return context if context.plain else None


def _short_date(moment: Any | None) -> str:
    """Return the ``Aug 24`` short date for a moment, or ``""``."""
    if moment is None:
        return ""
    committed = getattr(moment, "committed_time", None)
    if not committed:
        return ""
    try:
        import time as _time

        return _time.strftime("%b %d", _time.localtime(int(committed))).replace(
            " 0", " "
        )
    except (TypeError, ValueError, OverflowError):
        return ""


def _delta_segment(
    moment: Any | None, state: dict[str, object] | None, styles: Any
) -> Text | None:
    """Return the colour-matched ``Δ vA → vB`` segment for a diff view."""
    view = ""
    if moment is not None:
        view = str(getattr(moment, "view", "read") or "read")
    elif isinstance(state, dict):
        view = str(state.get("view", "read") or "read")
    if view != "diff":
        return None
    base: int | None = None
    target: int | None = None
    if moment is not None and getattr(moment, "diff", None):
        base, target = moment.diff
    elif isinstance(state, dict):
        raw_base = state.get("diff_base")
        try:
            base = int(cast(Any, raw_base)) if raw_base is not None else None
        except (TypeError, ValueError):
            base = None
        raw_target = state.get("diff_target")
        try:
            target = int(cast(Any, raw_target)) if raw_target is not None else None
        except (TypeError, ValueError):
            target = None
        if target is None:
            target, _newest = _moment_numbers(moment, state)
    if base is None or target is None:
        return None
    base_label = (
        "start" if base <= 0 and target > 0 else ("now" if base == 0 else f"v{base}")
    )
    if target == 0:
        target_label = "now"
        target_style = styles.uncommitted
    else:
        target_label = f"v{target}"
        target_style = styles.insert
    segment = Text()
    segment.append("Δ ", style="dim")
    segment.append(base_label, style=styles.delete)
    segment.append(" → ", style="dim")
    segment.append(target_label, style=target_style)
    return segment


def time_verbs_for_moment(moment: Any | None) -> list[tuple[str, str]]:
    """Return the ordered destination footer verbs for a moment.

    ``( vK`` steps older, ``) vK``/``) now`` steps newer, ``} now``
    jumps back to the live file (a tombstone reads ``} deleted``), and
    ``}`` appears only when its destination differs from ``)`` and from
    the current position. On the deletion itself there is no ``}`` verb.
    A verb appears only when its key would do something.
    """
    verbs: list[tuple[str, str]] = []
    if moment is None:
        return verbs
    kind = str(getattr(moment, "kind", "") or "")
    if kind == "loading":
        return verbs
    older = getattr(moment, "older", None)
    newer = getattr(moment, "newer", None)
    to_now = getattr(moment, "to_now", None)
    view = str(getattr(moment, "view", "read") or "read")
    try:
        shown = int(getattr(moment, "ordinal", 0) or 0)
    except (TypeError, ValueError):
        shown = 0
    current = 0 if kind in ("now", "now_dirty") else shown
    if isinstance(older, int):
        verbs.append((f"( v{older}", ""))
    if isinstance(newer, int):
        verbs.append((") now" if newer == 0 else f") v{newer}", ""))
    if isinstance(to_now, int) and to_now != newer and to_now != current:
        if to_now > 0:
            verbs.append(("} deleted", ""))
        else:
            verbs.append(("} now", ""))
    verbs.append(("=", "read" if view == "diff" else "diff"))
    verbs.append(("@", "timeline"))
    return verbs


#: Honest states with no usable history: plain chips, styled through
#: the palette. Untracked and ignored read as uncommitted-adjacent; the
#: rest stay dim.
_FOLDED_HONEST_LABELS: dict[str, tuple[str, str]] = {
    "untracked": ("UNTRACKED", "uncommitted"),
    "ignored": ("IGNORED", "uncommitted"),
    "no_vcs": ("NO VCS", "dim"),
    "shallow": ("SHALLOW", "dim"),
    "template": ("TEMPLATE", "dim"),
    "indexing": ("indexing…", "dim"),
    "unavailable": ("history unavailable", "dim"),
}


def honest_chip(state: dict[str, object] | None, styles: Any) -> Text | None:
    """Return the honest-state chip (untracked, no VCS, …), if any."""
    if not isinstance(state, dict):
        return None
    folded = state.get("folded_honest")
    if not (isinstance(folded, tuple) and len(folded) == 2):
        return None
    label, role = _FOLDED_HONEST_LABELS.get(str(folded[0] or ""), ("history", "dim"))
    style = getattr(styles, role, role) if role != "dim" else "dim"
    return Text(label, style=style)


__all__ = [
    "history_badge",
    "history_context",
    "honest_chip",
    "pill_forms",
    "state_moment",
    "time_verbs_for_moment",
]
