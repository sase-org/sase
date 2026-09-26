"""Pure tests for the card-block cursor and block-mode decision."""

from __future__ import annotations

from sase.ace.tui.widgets.decks.block_model import (
    BlockCursor,
    arrived_ids,
    cycle_block_id,
    decide_block_mode,
    derive_spread_block,
    land_cursor,
    reconcile_cursor,
    select_cursor,
    step_cursor,
)
from sase.ace.tui.widgets.decks.model import RenderMode

IDS = ("b0", "b1", "b2")


def test_land_newest_following_all_known() -> None:
    cursor = land_cursor(IDS)
    assert cursor == BlockCursor(
        block_id="b2", following=True, known_ids=frozenset(IDS)
    )


def test_land_empty_is_none() -> None:
    assert land_cursor(()) is None


def test_reconcile_new_subject_lands() -> None:
    parked = BlockCursor(block_id="b0", following=False, known_ids=frozenset(IDS))
    assert reconcile_cursor(IDS, parked, new_subject=True) == land_cursor(IDS)


def test_reconcile_none_cursor_lands() -> None:
    assert reconcile_cursor(IDS, None, new_subject=False) == land_cursor(IDS)


def test_reconcile_following_advances_to_newest() -> None:
    following = land_cursor(("b0", "b1"))
    assert following is not None
    assert reconcile_cursor(
        ("b0", "b1", "b2"), following, new_subject=False
    ) == BlockCursor(
        block_id="b2", following=True, known_ids=frozenset(("b0", "b1", "b2"))
    )


def test_reconcile_vanished_id_lands_newest() -> None:
    parked = BlockCursor(
        block_id="gone", following=False, known_ids=frozenset(("gone", "b1"))
    )
    assert reconcile_cursor(("b0", "b1"), parked, new_subject=False) == BlockCursor(
        block_id="b1", following=True, known_ids=frozenset(("b0", "b1"))
    )


def test_reconcile_parked_keeps_cursor_unchanged() -> None:
    parked = BlockCursor(
        block_id="b0", following=False, known_ids=frozenset(("b0", "b1"))
    )
    # A new shell arrived, but the reader stays put (object identity kept).
    assert reconcile_cursor(("b0", "b1", "b2"), parked, new_subject=False) is parked


def test_reconcile_empty_ids_is_none() -> None:
    parked = BlockCursor(block_id="b0", following=False, known_ids=frozenset(IDS))
    assert reconcile_cursor((), parked, new_subject=False) is None
    assert reconcile_cursor((), None, new_subject=True) is None


def test_step_older_and_newer_wrap() -> None:
    cursor = land_cursor(IDS)
    assert cursor is not None
    older = step_cursor(IDS, cursor, -1)
    assert older is not None
    assert older.block_id == "b1"
    assert older.following is False
    assert older.known_ids == frozenset(IDS)
    oldest = step_cursor(IDS, older, -1)
    assert oldest is not None and oldest.block_id == "b0"
    wrapped = step_cursor(IDS, oldest, -1)
    assert wrapped is not None and wrapped.block_id == "b2"
    assert wrapped.following is True
    forward = step_cursor(IDS, oldest, +1)
    assert forward is not None and forward.block_id == "b1"


def test_step_marks_all_known() -> None:
    parked = BlockCursor(
        block_id="b0", following=False, known_ids=frozenset(("b0", "b1"))
    )
    stepped = step_cursor(("b0", "b1", "b2"), parked, +1)
    assert stepped is not None
    assert stepped.block_id == "b1"
    assert arrived_ids(("b0", "b1", "b2"), stepped) == ()


def test_step_empty_keeps_cursor() -> None:
    parked = BlockCursor(block_id="b0", following=False, known_ids=frozenset(("b0",)))
    assert step_cursor((), parked, +1) is parked


def test_select_click() -> None:
    selected = select_cursor(IDS, "b0")
    assert selected == BlockCursor(
        block_id="b0", following=False, known_ids=frozenset(IDS)
    )
    newest = select_cursor(IDS, "b2")
    assert newest is not None and newest.following is True


def test_select_unknown_is_none() -> None:
    assert select_cursor(IDS, "gone") is None
    assert select_cursor(IDS, None) is None
    assert select_cursor((), "b0") is None


def test_arrivals_only_while_not_following() -> None:
    assert arrived_ids(IDS, land_cursor(IDS)) == ()
    parked = BlockCursor(
        block_id="b1", following=False, known_ids=frozenset(("b0", "b1"))
    )
    assert arrived_ids(("b0", "b1", "b2"), parked) == ("b2",)
    assert arrived_ids(("b0", "b1"), parked) == ()
    assert arrived_ids(IDS, None) == IDS


def test_cycle_wraps() -> None:
    assert cycle_block_id(IDS, "b2", +1) == "b0"
    assert cycle_block_id(IDS, "b0", -1) == "b2"
    assert cycle_block_id(IDS, "b1", +1) == "b2"
    assert cycle_block_id(IDS, "b1", -1) == "b0"
    assert cycle_block_id((), "b0", +1) is None


def test_cycle_unknown_anchor() -> None:
    assert cycle_block_id(IDS, None, +1) == "b0"
    assert cycle_block_id(IDS, None, -1) == "b2"
    assert cycle_block_id(IDS, "gone", +1) == "b0"
    assert cycle_block_id(IDS, "gone", -1) == "b2"


def test_derive_at_bottom_is_newest() -> None:
    anchors = (("b0", 0), ("b1", 40), ("b2", 90))
    assert derive_spread_block(anchors, scroll_y=0, at_real_bottom=True) == "b2"


def test_derive_mid_scroll() -> None:
    anchors = (("b0", 0), ("b1", 40), ("b2", 90))
    assert derive_spread_block(anchors, scroll_y=0, at_real_bottom=False) == "b0"
    assert derive_spread_block(anchors, scroll_y=45, at_real_bottom=False) == "b1"
    assert derive_spread_block(anchors, scroll_y=200, at_real_bottom=False) == "b2"


def test_derive_above_first_header_is_none() -> None:
    anchors = (("b0", 10), ("b1", 40))
    assert derive_spread_block(anchors, scroll_y=5, at_real_bottom=False) is None
    assert derive_spread_block((), scroll_y=0, at_real_bottom=True) is None


def test_derive_mapping_anchors() -> None:
    assert (
        derive_spread_block({"b0": 0, "b1": 40}, scroll_y=41, at_real_bottom=False)
        == "b1"
    )


def _mode(**kwargs: object) -> RenderMode:
    base: dict[str, object] = {
        "block_count": 3,
        "card_rows": 20,
        "viewport_rows": 20,
        "block_spread_max_screens": 1.5,
        "previous": None,
        "same_card": False,
    }
    base.update(kwargs)
    return decide_block_mode(**base)  # type: ignore[arg-type]


def test_mode_single_block_always_spread() -> None:
    assert _mode(block_count=0) is RenderMode.SPREAD
    assert _mode(block_count=1) is RenderMode.SPREAD
    assert _mode(block_count=1, block_spread_max_screens=0) is RenderMode.SPREAD


def test_mode_zero_screens_always_paged() -> None:
    assert _mode(block_spread_max_screens=0) is RenderMode.PAGED
    assert _mode(block_spread_max_screens=0, card_rows=1) is RenderMode.PAGED


def test_mode_threshold() -> None:
    assert _mode(card_rows=30) is RenderMode.SPREAD
    assert _mode(card_rows=31) is RenderMode.PAGED


def test_mode_unmeasured_keeps_previous_for_same_card() -> None:
    assert (
        _mode(card_rows=None, previous=RenderMode.SPREAD, same_card=True)
        is RenderMode.SPREAD
    )
    assert (
        _mode(card_rows=None, previous=RenderMode.PAGED, same_card=True)
        is RenderMode.PAGED
    )
    assert (
        _mode(card_rows=None, previous=RenderMode.SPREAD, same_card=False)
        is RenderMode.PAGED
    )


def test_mode_hysteresis_band() -> None:
    # Budget is 1.5 * 20 = 30 rows: the ±10% band is (27, 33).
    assert (
        _mode(
            card_rows=32,
            previous=RenderMode.SPREAD,
            same_card=True,
        )
        is RenderMode.SPREAD
    )
    assert (
        _mode(
            card_rows=34,
            previous=RenderMode.SPREAD,
            same_card=True,
        )
        is RenderMode.PAGED
    )
    assert (
        _mode(
            card_rows=27,
            previous=RenderMode.PAGED,
            same_card=True,
        )
        is RenderMode.SPREAD
    )
    assert (
        _mode(
            card_rows=29,
            previous=RenderMode.PAGED,
            same_card=True,
        )
        is RenderMode.PAGED
    )
