"""Exhaustive decide_render_mode table and measurement tests."""

from __future__ import annotations

from rich.console import Console, Group
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.widgets.decks.card_part import CardPart, context_card, reply_card
from sase.ace.tui.widgets.decks.model import RenderMode
from sase.ace.tui.widgets.decks.render_mode import (
    decide_render_mode,
    _lower_bound_rows,
    measure_main_rows,
    spread_budget_rows,
)


def _decide(**overrides):  # type: ignore[no-untyped-def]
    params = {
        "card_count": 2,
        "has_solo_card": False,
        "total_rows": 10,
        "viewport_rows": 20,
        "spread_max_screens": 1.5,
        "previous": None,
        "same_subject": False,
    }
    params.update(overrides)
    return decide_render_mode(**params)  # type: ignore[arg-type]


def test_single_card_always_spread() -> None:
    assert _decide(card_count=1, total_rows=10000) is RenderMode.SPREAD
    assert _decide(card_count=0, total_rows=10000) is RenderMode.SPREAD


def test_solo_forces_paged() -> None:
    assert _decide(has_solo_card=True, total_rows=1) is RenderMode.PAGED


def test_zero_spread_max_always_paged() -> None:
    assert _decide(spread_max_screens=0, total_rows=1) is RenderMode.PAGED
    assert _decide(spread_max_screens=0, card_count=1) is RenderMode.SPREAD


def test_exact_boundary_spread() -> None:
    # budget = 1.5 * 20 = 30. total == budget spreads on a new subject.
    assert _decide(total_rows=30, viewport_rows=20) is RenderMode.SPREAD
    assert _decide(total_rows=31, viewport_rows=20) is RenderMode.PAGED


def test_zero_viewport_clamps_to_one() -> None:
    assert spread_budget_rows(1.5, 0) == 1.5
    # budget 1.5, total 1 spreads, total 2 paged.
    assert _decide(total_rows=1, viewport_rows=0) is RenderMode.SPREAD
    assert _decide(total_rows=2, viewport_rows=0) is RenderMode.PAGED


def test_unknown_totals() -> None:
    assert (
        _decide(total_rows=None, previous=RenderMode.SPREAD, same_subject=True)
        is RenderMode.SPREAD
    )
    assert (
        _decide(total_rows=None, previous=RenderMode.PAGED, same_subject=True)
        is RenderMode.PAGED
    )
    assert (
        _decide(total_rows=None, previous=None, same_subject=True) is RenderMode.PAGED
    )
    assert (
        _decide(total_rows=None, previous=RenderMode.SPREAD, same_subject=False)
        is RenderMode.PAGED
    )


def test_hysteresis_spread_stays_until_upper_edge() -> None:
    # budget 30, upper edge 33. 33 stays spread, 34 flips.
    assert (
        _decide(total_rows=33, previous=RenderMode.SPREAD, same_subject=True)
        is RenderMode.SPREAD
    )
    assert (
        _decide(total_rows=34, previous=RenderMode.SPREAD, same_subject=True)
        is RenderMode.PAGED
    )
    # Just inside/outside 1.10 with a fractional budget.
    assert (
        _decide(
            total_rows=16,
            viewport_rows=10,
            previous=RenderMode.SPREAD,
            same_subject=True,
        )
        is RenderMode.SPREAD
    )
    assert (
        _decide(
            total_rows=17,
            viewport_rows=10,
            previous=RenderMode.SPREAD,
            same_subject=True,
        )
        is RenderMode.PAGED
    )


def test_hysteresis_paged_returns_below_lower_edge() -> None:
    # budget 30, lower edge 27. 27 spreads, 28 stays paged.
    assert (
        _decide(total_rows=27, previous=RenderMode.PAGED, same_subject=True)
        is RenderMode.SPREAD
    )
    assert (
        _decide(total_rows=28, previous=RenderMode.PAGED, same_subject=True)
        is RenderMode.PAGED
    )


def test_same_versus_new_subject() -> None:
    # Inside the band (28 rows, budget 30): new subject paged, spread stays.
    assert _decide(total_rows=28, same_subject=False) is RenderMode.SPREAD
    # 32 rows is above budget but below the upper edge: new subject paged.
    assert _decide(total_rows=32, same_subject=False) is RenderMode.PAGED
    assert (
        _decide(total_rows=32, previous=RenderMode.SPREAD, same_subject=True)
        is RenderMode.SPREAD
    )
    assert (
        _decide(total_rows=32, previous=RenderMode.SPREAD, same_subject=False)
        is RenderMode.PAGED
    )


def test_lower_bound_walker() -> None:
    assert _lower_bound_rows([Text("")], stop_after=10) == 0
    assert _lower_bound_rows([Text("a\nb")], stop_after=10) == 2
    assert _lower_bound_rows([Syntax("x\ny\nz", "python")], stop_after=10) == 3
    group = Group(Text("a"), Text("b\nc"))
    assert _lower_bound_rows([group], stop_after=10) == 3
    card = CardPart("c", "C", Text("a\nb"), Text("c"))
    assert _lower_bound_rows([card], stop_after=10) == 3
    assert _lower_bound_rows([object()], stop_after=10) == 1
    # Early exit: stops summing once past stop_after.
    many = [Text("line") for _ in range(20)]
    full = _lower_bound_rows(many, stop_after=1000)
    early = _lower_bound_rows(many, stop_after=5)
    assert early <= full
    assert early > 5


def test_lower_bound_below_exact_on_wrapped_text() -> None:
    console = Console(width=20)
    options = console.options.update_width(20)
    long_line = "word " * 30
    card = context_card(Text(long_line))
    lower = _lower_bound_rows(list(card.renderables), stop_after=1000)
    measured = measure_main_rows(
        [card],
        width=20,
        console=console,
        options=options,
        budget=1000,
        cache_key_prefix="lb-wrap",
    )
    assert lower <= measured


def test_measurement_cache_hit() -> None:
    from sase.ace.tui.widgets.decks import render_mode as rm

    rm._measure_cache.clear()
    console = Console(width=80)
    options = console.options
    card = context_card(Text("hello"))
    first = measure_main_rows(
        [card],
        width=80,
        console=console,
        options=options,
        budget=100,
        cache_key_prefix="cache-test",
    )
    size_after_first = len(rm._measure_cache)
    second = measure_main_rows(
        [card],
        width=80,
        console=console,
        options=options,
        budget=100,
        cache_key_prefix="cache-test",
    )
    assert first == second
    assert len(rm._measure_cache) == size_after_first
    assert size_after_first >= 1
    rm._measure_cache.clear()


def test_measurement_lower_bound_short_circuits_paged() -> None:
    console = Console(width=80)
    options = console.options
    big = context_card(Text("\n".join(f"line {i}" for i in range(200))))
    cards = [big, reply_card(Text("tail"))]
    # Tiny budget: the lower bound alone exceeds budget*1.10.
    total = measure_main_rows(
        cards,
        width=80,
        console=console,
        options=options,
        budget=10,
        cache_key_prefix="short-circuit",
    )
    assert total > 11
