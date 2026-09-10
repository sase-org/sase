"""Width-budgeted layout of breadcrumb tokens along the trail path row."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from rich.cells import cell_len
from rich.text import Text

from sase.pager._trail_chrome_model import CURRENT_MARKER as _CURRENT_MARKER
from sase.pager._trail_chrome_model import CURRENT_STYLE as _CURRENT_STYLE
from sase.pager._trail_chrome_model import MUTED_STYLE as _MUTED_STYLE
from sase.pager._trail_chrome_model import PagerTrailDisplayEntry
from sase.pager._trail_chrome_model import PagerTrailSnapshot
from sase.pager._trail_chrome_model import STATE_STYLES as _STATE_STYLES
from sase.pager._trail_chrome_text import fit_label as _fit_label

_ELLIPSIS = "…"
_SEPARATOR = " › "


def render_trail_path_row(
    snapshot: PagerTrailSnapshot,
    *,
    width: int,
) -> Text:
    """Render the chronological path row with exact counted gaps."""

    width = max(0, int(width))
    if width == 0:
        return Text(no_wrap=True, overflow="crop")

    all_indices = frozenset(range(snapshot.total))
    full = _render_path_for_indices(snapshot, all_indices, width=width, full=True)
    if full is not None:
        return full

    included: frozenset[int] = frozenset({snapshot.current_index})
    best = render_current_only(snapshot.current, width=width)
    for index in _path_priority(snapshot):
        trial = frozenset((*included, index))
        rendered = _render_path_for_indices(snapshot, trial, width=width, full=False)
        if rendered is not None:
            included = trial
            best = rendered
    return best


def _path_priority(snapshot: PagerTrailSnapshot) -> Iterable[int]:
    current = snapshot.current_index
    seen = {current}
    candidates = [current - 1, current + 1, 0]
    for candidate in candidates:
        if 0 <= candidate < snapshot.total and candidate not in seen:
            seen.add(candidate)
            yield candidate

    for distance in range(2, snapshot.total + 1):
        for candidate in (current - distance, current + distance):
            if 0 <= candidate < snapshot.total and candidate not in seen:
                seen.add(candidate)
                yield candidate


def _render_path_for_indices(
    snapshot: PagerTrailSnapshot,
    indices: frozenset[int],
    *,
    width: int,
    full: bool,
) -> Text | None:
    tokens = _path_tokens(snapshot, indices)
    if full:
        rendered = _render_path_tokens(tokens, full_labels=True)
        return rendered if cell_len(rendered.plain) <= width else None

    budgets = _label_budgets(tokens, width=width)
    if budgets is None:
        return None
    rendered = _render_path_tokens(tokens, label_budgets=budgets)
    if cell_len(rendered.plain) <= width:
        return rendered
    return None


def _path_tokens(
    snapshot: PagerTrailSnapshot,
    indices: frozenset[int],
) -> tuple[int | PagerTrailDisplayEntry, ...]:
    tokens: list[int | PagerTrailDisplayEntry] = []
    omitted = 0
    for index, entry in enumerate(snapshot.entries):
        if index not in indices:
            omitted += 1
            continue
        if omitted:
            tokens.append(omitted)
            omitted = 0
        tokens.append(entry)
    if omitted:
        tokens.append(omitted)
    return tuple(tokens)


def _label_budgets(
    tokens: tuple[int | PagerTrailDisplayEntry, ...],
    *,
    width: int,
) -> dict[int, int] | None:
    entries = [token for token in tokens if isinstance(token, PagerTrailDisplayEntry)]
    if not entries:
        return {}

    structural = _path_structural_width(tokens)
    minimum = sum(1 for entry in entries if entry.state == "current")
    minimum += sum(3 for entry in entries if entry.state != "current")
    if structural + minimum > width:
        return None

    by_id = {id(entry): entry for entry in entries}
    budgets: dict[int, int] = {id(entry): 0 for entry in entries}
    available = width - structural
    priority = _budget_priority(entries)
    for entry in priority:
        full_width = cell_len(entry.short_label)
        floor = 1 if entry.state == "current" else 3
        cap = _label_cap(entry, width=width)
        wanted = min(full_width, cap)
        give = min(wanted, available)
        if give < floor:
            return None
        budgets[id(entry)] = give
        available -= give

    if available > 0:
        for entry in priority:
            full_width = cell_len(entry.short_label)
            room = full_width - budgets[id(entry)]
            if room <= 0:
                continue
            give = min(room, available)
            budgets[id(entry)] += give
            available -= give
            if available <= 0:
                break

    return {entry_id: budgets[entry_id] for entry_id in by_id}


def _budget_priority(
    entries: Sequence[PagerTrailDisplayEntry],
) -> tuple[PagerTrailDisplayEntry, ...]:
    current = [entry for entry in entries if entry.state == "current"]
    back = [entry for entry in reversed(entries) if entry.state == "back"]
    forward = [entry for entry in entries if entry.state == "forward"]
    others = [
        entry for entry in entries if entry.state not in {"current", "back", "forward"}
    ]
    seen: set[int] = set()
    ordered: list[PagerTrailDisplayEntry] = []
    for group in (
        current,
        back[:1],
        forward[:1],
        entries[:1],
        back[1:],
        forward[1:],
        others,
    ):
        for entry in group:
            marker = id(entry)
            if marker in seen:
                continue
            seen.add(marker)
            ordered.append(entry)
    return tuple(ordered)


def _label_cap(entry: PagerTrailDisplayEntry, *, width: int) -> int:
    if entry.state == "current":
        return max(1, min(32, max(8, width // 3)))
    return max(3, min(18, max(6, width // 5)))


def _path_structural_width(
    tokens: tuple[int | PagerTrailDisplayEntry, ...],
) -> int:
    width = 0
    for index, token in enumerate(tokens):
        if index:
            width += cell_len(_SEPARATOR)
        if isinstance(token, int):
            width += cell_len(f"{_ELLIPSIS}{token}")
            continue
        width += _crumb_overhead(token)
    return width


def _crumb_overhead(entry: PagerTrailDisplayEntry) -> int:
    icon = entry.icon
    if entry.state == "current":
        return cell_len(f"[{_CURRENT_MARKER} {icon} ]")
    return cell_len(f"{icon} ")


def _render_path_tokens(
    tokens: tuple[int | PagerTrailDisplayEntry, ...],
    *,
    full_labels: bool = False,
    label_budgets: dict[int, int] | None = None,
) -> Text:
    text = Text(no_wrap=True, overflow="crop")
    for index, token in enumerate(tokens):
        if index:
            text.append(_SEPARATOR, style=_MUTED_STYLE)
        if isinstance(token, int):
            text.append(f"{_ELLIPSIS}{token}", style=_MUTED_STYLE)
            continue
        label = token.short_label
        if not full_labels:
            assert label_budgets is not None
            label = _fit_label(label, label_budgets[id(token)])
        _append_crumb(text, token, label=label)
    return text


def _append_crumb(text: Text, entry: PagerTrailDisplayEntry, *, label: str) -> None:
    if entry.state == "current":
        text.append("[", style=_CURRENT_STYLE)
        text.append(f"{_CURRENT_MARKER} ", style=_CURRENT_STYLE)
        text.append(f"{entry.icon} ", style=f"bold {entry.accent} reverse")
        text.append(label, style=_CURRENT_STYLE)
        text.append("]", style=_CURRENT_STYLE)
        return

    style = _STATE_STYLES[entry.state]
    text.append(f"{entry.icon} ", style=f"bold {entry.accent}")
    text.append(label, style=style)


def render_current_only(entry: PagerTrailDisplayEntry, *, width: int) -> Text:
    width = max(0, width)
    if width <= 0:
        return Text(no_wrap=True, overflow="crop")

    for bracketed, include_icon in (
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ):
        overhead = _current_only_overhead(entry, bracketed, include_icon)
        budget = width - overhead
        if budget < 1:
            continue
        label = _fit_label(entry.short_label, budget)
        rendered = Text(no_wrap=True, overflow="crop")
        if bracketed:
            rendered.append("[", style=_CURRENT_STYLE)
        rendered.append(f"{_CURRENT_MARKER} ", style=_CURRENT_STYLE)
        if include_icon:
            rendered.append(f"{entry.icon} ", style=f"bold {entry.accent} reverse")
        rendered.append(label, style=_CURRENT_STYLE)
        if bracketed:
            rendered.append("]", style=_CURRENT_STYLE)
        if cell_len(rendered.plain) <= width:
            return rendered

    if cell_len(_CURRENT_MARKER) <= width:
        return Text(_CURRENT_MARKER, style=_CURRENT_STYLE, no_wrap=True)
    return Text(no_wrap=True, overflow="crop")


def _current_only_overhead(
    entry: PagerTrailDisplayEntry,
    bracketed: bool,
    include_icon: bool,
) -> int:
    prefix = f"{_CURRENT_MARKER} "
    if bracketed:
        prefix = f"[{prefix}"
    if include_icon:
        prefix += f"{entry.icon} "
    suffix = "]" if bracketed else ""
    return cell_len(prefix) + cell_len(suffix)
