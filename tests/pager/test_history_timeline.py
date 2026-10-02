"""Unit tests for the generic timeline list model and picker endpoints."""

from __future__ import annotations

from rich.cells import cell_len

from sase.memory.history.timeline_picker import build_picker_rows
from sase.pager._timeline_picker_rows import format_picker_row, picker_columns
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


def _picker_rows() -> tuple[dict[str, object], ...]:
    timeline = {
        "versions": [
            {
                "ordinal": 0,
                "class": "uncommitted",
                "commit": "",
                "committer_time": 0,
                "path": "sase/memory/gotchas.md",
                "summary": {},
                "provenance": {},
            },
            {
                "ordinal": 25,
                "class": "authored",
                "commit": "5" * 40,
                "committer_time": 1790486400,
                "path": "sase/memory/gotchas.md",
                "summary": {
                    "section_paths": ["Default Keymap Config"],
                    "words_added": 194,
                    "words_removed": 0,
                },
                "provenance": {
                    "agent": "bbugyi200.athena.sase-sq.1",
                    "bead": "sase-sq.1",
                    "subject": "feat(tui): keymaps",
                },
            },
            {
                "ordinal": 9,
                "class": "authored",
                "commit": "9" * 40,
                "committer_time": 1790054400,
                "path": "sase/memory/gotchas.md",
                "summary": {
                    "section_paths": ["Code Conventions and Gotchas"],
                    "words_added": 51,
                    "words_removed": 0,
                },
                "provenance": {
                    "agent": "bbugyi200.athena.sase-1dr.9",
                    "bead": "sase-1dr.9",
                    "subject": "docs: gotchas",
                },
            },
        ]
    }
    return build_picker_rows(  # type: ignore[return-value]
        timeline, now_epoch=1790700000, now_matches_newest=True, newest=25
    )


def test_picker_columns_shed_sha_then_by_then_age() -> None:
    rows = _picker_rows()

    wide = picker_columns(rows, 160)
    assert (wide.show_sha, wide.show_by, wide.show_age) == (True, True, True)

    shedding = [picker_columns(rows, width) for width in (160, 110, 80, 60, 50)]
    # Shedding never re-adds a dropped column as width shrinks.
    for earlier, later in zip(shedding, shedding[1:], strict=False):
        assert int(later.show_sha) <= int(earlier.show_sha)
        assert int(later.show_by) <= int(earlier.show_by)
        assert int(later.show_age) <= int(earlier.show_age)
    narrowest = shedding[-1]
    assert narrowest.change_w >= 0
    # At 50 cells the SHA is long gone.
    assert narrowest.show_sha is False


def test_picker_rows_never_exceed_the_list_width() -> None:
    rows = _picker_rows()

    for width in (50, 60, 80, 110, 160):
        columns = picker_columns(rows, width)
        for row in rows:
            for is_cursor in (False, True):
                line = format_picker_row(
                    row,
                    columns,
                    is_open=True,
                    is_cursor=is_cursor,
                    open_style="magenta",
                )
                assert cell_len(line.plain) <= width, (width, line.plain)


def test_picker_row_marks_open_cursor_and_now_alias() -> None:
    rows = _picker_rows()
    columns = picker_columns(rows, 160)
    committed = rows[1]
    assert committed["is_now_alias"] is True

    open_line = format_picker_row(
        committed, columns, is_open=True, is_cursor=False, open_style="magenta"
    )
    assert open_line.plain.startswith("● ")
    assert "≡ now" in open_line.plain

    both = format_picker_row(
        committed, columns, is_open=True, is_cursor=True, open_style="magenta"
    )
    assert both.plain.startswith("●▸")

    plain = format_picker_row(
        rows[2], columns, is_open=False, is_cursor=False, open_style="magenta"
    )
    assert plain.plain.startswith("  ")
    assert "≡ now" not in plain.plain

    now_line = format_picker_row(
        rows[0], columns, is_open=True, is_cursor=False, open_style="magenta"
    )
    assert "uncommitted · not durable until committed" in now_line.plain


def test_picker_row_labels_align_right() -> None:
    rows = _picker_rows()
    columns = picker_columns(rows, 160)

    labels = [
        format_picker_row(row, columns, is_open=False, is_cursor=False).plain[
            2 : 2 + columns.label_w
        ]
        for row in rows
    ]
    assert labels[0].endswith("now")
    assert labels[1].endswith("v25")
    assert labels[2].endswith("v9")


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
