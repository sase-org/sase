"""Pure spread versus paged decision and measurement."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

from rich.console import Console, ConsoleOptions, Group
from rich.syntax import Syntax
from rich.text import Text

from .card_part import CardPart
from .model import RenderMode

SPREAD_HYSTERESIS = 0.10

_MEASURE_CACHE_MAX_ENTRIES = 64
_measure_cache: OrderedDict[tuple[str, int], int] = OrderedDict()


def spread_budget_rows(spread_max_screens: float, viewport_rows: int) -> float:
    """Return the spread budget in rows for a viewport height."""
    return float(spread_max_screens) * max(1, int(viewport_rows))


def decide_render_mode(
    *,
    card_count: int,
    has_solo_card: bool,
    total_rows: int | None,
    viewport_rows: int,
    spread_max_screens: float,
    previous: RenderMode | None,
    same_subject: bool,
) -> RenderMode:
    """Decide spread versus paged rendering with hysteresis."""
    if card_count <= 1:
        return RenderMode.SPREAD
    if has_solo_card or spread_max_screens <= 0:
        return RenderMode.PAGED
    if total_rows is None:
        if same_subject and previous is not None:
            return previous
        return RenderMode.PAGED
    budget = spread_max_screens * max(1, viewport_rows)
    if same_subject and previous is RenderMode.SPREAD:
        if total_rows > budget * (1 + SPREAD_HYSTERESIS):
            return RenderMode.PAGED
        return RenderMode.SPREAD
    if same_subject and previous is RenderMode.PAGED:
        if total_rows <= budget * (1 - SPREAD_HYSTERESIS):
            return RenderMode.SPREAD
        return RenderMode.PAGED
    if total_rows <= budget:
        return RenderMode.SPREAD
    return RenderMode.PAGED


def lower_bound_rows(renderables: Iterable[object], *, stop_after: float) -> int:
    """Return a cheap lower bound of rendered rows, stopping early."""
    total = 0
    for node in renderables:
        total += _lower_bound_node(node)
        if total > stop_after:
            break
    return total


def _lower_bound_node(node: object) -> int:
    # CardPart and Group: sum children.
    if isinstance(node, (Group, CardPart)):
        renderables = getattr(node, "renderables", ())
        subtotal = 0
        for child in renderables:
            subtotal += _lower_bound_node(child)
        return subtotal
    if isinstance(node, Text):
        plain = node.plain
        if not plain:
            return 0
        return plain.count("\n") + 1
    if isinstance(node, Syntax):
        code = getattr(node, "code", "")
        if not code:
            return 0
        return str(code).count("\n") + 1
    # Lazy syntax renderables expose source via code/plain/content_digest.
    lazy_code = getattr(node, "code", None)
    if isinstance(lazy_code, str):
        if not lazy_code:
            return 0
        return lazy_code.count("\n") + 1
    lazy_plain = getattr(node, "plain", None)
    if isinstance(lazy_plain, str):
        if not lazy_plain:
            return 0
        return lazy_plain.count("\n") + 1
    lazy_content = getattr(node, "_content", None)
    if isinstance(lazy_content, str):
        if not lazy_content:
            return 0
        return lazy_content.count("\n") + 1
    return 1


def measure_main_rows(
    cards: Iterable[CardPart],
    *,
    width: int,
    console: Console,
    options: ConsoleOptions,
    budget: float,
    cache_key_prefix: str | None,
) -> int:
    """Measure spread rows with a cheap lower bound first, then exact render."""
    card_list = list(cards)
    if not card_list:
        return 0
    separator_rows = 2 * (len(card_list) - 1)
    stop_after = budget * (1 + SPREAD_HYSTERESIS) - separator_rows
    flat: list[object] = []
    for card in card_list:
        flat.extend(list(card.renderables))
    lower = lower_bound_rows(flat, stop_after=max(0.0, stop_after))
    lower_total = lower + separator_rows
    if lower_total > budget * (1 + SPREAD_HYSTERESIS):
        return lower_total
    # Exact measurement, cached per card.
    from ...util.renderable_digest import renderable_content_digest

    total = separator_rows
    render_width = max(1, int(width))
    for card in card_list:
        if cache_key_prefix:
            digest = f"{cache_key_prefix}:{card.card_id}"
        else:
            try:
                digest = renderable_content_digest(card)
            except Exception:
                digest = f"card:{card.card_id}"
        key = (digest, render_width)
        cached = _measure_cache.get(key)
        if cached is not None:
            _measure_cache.move_to_end(key)
            total += cached
            continue
        try:
            lines = console.render_lines(
                Group(*card.renderables),
                options.update_width(render_width),
                pad=False,
            )
            height = len(lines)
        except Exception:
            height = _lower_bound_node(card)
        _measure_cache[key] = height
        _measure_cache.move_to_end(key)
        if len(_measure_cache) > _MEASURE_CACHE_MAX_ENTRIES:
            _measure_cache.popitem(last=False)
        total += height
    return total


__all__ = [
    "SPREAD_HYSTERESIS",
    "decide_render_mode",
    "lower_bound_rows",
    "measure_main_rows",
    "spread_budget_rows",
]
