"""Unit tests for the identity-preserving selection helper.

Covers the contract documented in
``src/sase/ace/tui/util/selection.py``:

1. Identity hit wins over neighbor fallback.
2. Neighbor fallback (clamped prior visual row) wins when identity gone.
3. Empty list short-circuits to ``0``.
4. Edge positions (row 0 / last row) round-trip correctly.
"""

from __future__ import annotations

from sase.ace.tui.util.selection import restore_selection_by_identity


def test_identity_present_returns_its_index() -> None:
    items = ["alpha", "beta", "gamma"]
    assert (
        restore_selection_by_identity(
            items,
            prior_identity="beta",
            prior_visual_row=0,
            identity_fn=lambda s: s,
        )
        == 1
    )


def test_identity_missing_falls_back_to_clamped_visual_row() -> None:
    items = ["alpha", "beta"]
    # Saved row was 5; new list has 2 entries; clamp to row 1 (last
    # surviving row), not row 0.
    assert (
        restore_selection_by_identity(
            items,
            prior_identity="missing",
            prior_visual_row=5,
            identity_fn=lambda s: s,
        )
        == 1
    )


def test_identity_missing_visual_row_in_range_kept() -> None:
    items = ["a", "b", "c", "d"]
    assert (
        restore_selection_by_identity(
            items,
            prior_identity="missing",
            prior_visual_row=2,
            identity_fn=lambda s: s,
        )
        == 2
    )


def test_empty_list_returns_zero() -> None:
    assert (
        restore_selection_by_identity(
            [],
            prior_identity="anything",
            prior_visual_row=42,
            identity_fn=lambda s: s,
        )
        == 0
    )


def test_no_prior_identity_uses_visual_row() -> None:
    items = ["a", "b", "c"]
    assert (
        restore_selection_by_identity(
            items,
            prior_identity=None,
            prior_visual_row=2,
            identity_fn=lambda s: s,
        )
        == 2
    )


def test_no_prior_anything_returns_zero() -> None:
    items = ["a", "b"]
    assert (
        restore_selection_by_identity(
            items,
            prior_identity=None,
            prior_visual_row=None,
            identity_fn=lambda s: s,
        )
        == 0
    )


def test_negative_visual_row_clamps_to_zero() -> None:
    items = ["a", "b", "c"]
    assert (
        restore_selection_by_identity(
            items,
            prior_identity="missing",
            prior_visual_row=-3,
            identity_fn=lambda s: s,
        )
        == 0
    )


def test_identity_at_first_row_round_trips() -> None:
    items = ["first", "second"]
    assert (
        restore_selection_by_identity(
            items,
            prior_identity="first",
            prior_visual_row=1,
            identity_fn=lambda s: s,
        )
        == 0
    )


def test_identity_at_last_row_round_trips() -> None:
    items = ["a", "b", "c"]
    assert (
        restore_selection_by_identity(
            items,
            prior_identity="c",
            prior_visual_row=0,
            identity_fn=lambda s: s,
        )
        == 2
    )


def test_identity_fn_can_extract_tuple_keys() -> None:
    """Mirror the AXE tab where identity is a tagged tuple."""
    items = [("axe", None), ("lumberjack", "hooks"), ("bgcmd", 7)]
    assert (
        restore_selection_by_identity(
            items,
            prior_identity=("bgcmd", 7),
            prior_visual_row=0,
            identity_fn=lambda t: t,
        )
        == 2
    )
