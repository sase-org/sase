"""Unit tests for the generic timeline list model and picker endpoints."""

from __future__ import annotations

from sase.pager.history.diff import diff_endpoints
from sase.pager.history.timeline import filter_rows, picker_window, visible_rows


def _row(ordinal: int, hidden: bool = False, haystack: str = "") -> dict[str, object]:
    return {"ordinal": ordinal, "hidden": hidden, "haystack": haystack}


def test_visible_rows_needs_dot_for_hidden() -> None:
    rows = (_row(0), _row(3), _row(2, hidden=True))

    assert visible_rows(rows, show_hidden=False) == (_row(0), _row(3))
    assert visible_rows(rows, show_hidden=True) == rows


def test_filter_rows_requires_every_token() -> None:
    rows = (
        _row(3, haystack="planting athena sase-9.3"),
        _row(1, haystack="created beds"),
    )

    assert filter_rows(rows, "sase-9.3 planting") == (rows[0],)
    assert filter_rows(rows, "") == rows
    assert filter_rows(rows, "missing") == ()


def test_picker_window_stays_bounded() -> None:
    assert picker_window(100, 0, 20) == (0, 20)
    assert picker_window(100, 99, 20) == (80, 100)
    assert picker_window(5, 2, 20) == (0, 5)
    assert picker_window(0, 0, 20) == (0, 0)


def test_explicit_picker_base_reaches_now_target() -> None:
    assert diff_endpoints(
        ordinal=0,
        visible_ordinals=(1, 2, 3),
        dirty=False,
        compare_base=1,
        explicit_base=True,
    ) == (1, 0)


def test_implicit_now_base_keeps_default_endpoints() -> None:
    # A live pin's incidental compare_base (clean-now default diff)
    # must not reroute fold expansion or change jumps.
    assert diff_endpoints(
        ordinal=0,
        visible_ordinals=(1, 2),
        dirty=False,
        compare_base=1,
        explicit_base=False,
    ) == (1, 2)
    assert diff_endpoints(ordinal=0, visible_ordinals=(1, 2), dirty=True) == (2, 0)
