"""Pure Changes-lens builder tests: rows, window, filter, chips, totals."""

from __future__ import annotations

import datetime

from sase.ace.tui.modals.memory_pane_changes_card import (
    _changes_provenance_text,
    _changes_section_title,
    _changes_totals_text,
)
from sase.ace.tui.modals.memory_pane_changes_feed import (
    _changes_day_label,
    _changes_lens_rows,
    _changes_row_id,
    _changes_row_is_selectable,
)
from sase.ace.tui.modals.memory_pane_changes_header import (
    _changes_lens_footer,
    _changes_lens_header_detail,
)
from sase.ace.tui.modals.memory_pane_changes_lens import MORE_ROW_ID
from tests.ace.tui.modals._memory_pane_changes_lens_helpers import (
    DAY_ONE,
    make_changeset,
    make_feed,
)


def test_lens_rows_group_days_with_changesets() -> None:
    listed, total, older, regen = _changes_lens_rows(
        make_feed(), now_epoch=DAY_ONE + 7200
    )
    assert total == 2
    assert older == 0
    assert regen == 1
    kinds = [row["kind"] for row in listed]
    assert kinds[0] == "day"
    assert listed[0]["title"] == "Today"
    assert kinds.count("changeset") == 2
    assert kinds[-1] == "regen"


def test_lens_rows_survive_missing_feed() -> None:
    assert _changes_lens_rows(None) == ((), 0, 0, 0)
    assert _changes_lens_rows({})[1] == 0


def test_day_headers_are_not_selectable() -> None:
    listed, _, _, _ = _changes_lens_rows(make_feed())
    day = next(row for row in listed if row["kind"] == "day")
    changeset = next(row for row in listed if row["kind"] == "changeset")
    assert _changes_row_is_selectable(day) is False
    assert _changes_row_is_selectable(changeset) is True
    assert _changes_row_is_selectable(None) is False


def test_day_labels_name_today_and_yesterday() -> None:
    today_key = datetime.datetime.fromtimestamp(DAY_ONE).strftime("%Y-%m-%d")
    assert _changes_day_label(today_key, "Whatever", now_epoch=DAY_ONE) == "Today"
    yesterday = datetime.datetime.fromtimestamp(DAY_ONE) - datetime.timedelta(days=1)
    assert (
        _changes_day_label(
            yesterday.strftime("%Y-%m-%d"), "Whatever", now_epoch=DAY_ONE
        )
        == "Yesterday"
    )
    assert (
        _changes_day_label("2020-01-01", "Wed Jan 01", now_epoch=DAY_ONE)
        == "Wed Jan 01"
    )


def test_window_bounds_newest_and_appends_more_row() -> None:
    feed = make_feed(
        *[
            make_changeset(commit=f"{index:040d}", committer_time=DAY_ONE + index)
            for index in range(250)
        ]
    )
    listed, total, older, _ = _changes_lens_rows(feed, limit=100)
    assert total == 250
    assert older == 150
    assert listed[-1]["kind"] == "more"
    assert listed[-1]["id"] == MORE_ROW_ID
    assert listed[-1]["older"] == 150


def test_filter_matches_whole_feed() -> None:
    feed = make_feed()
    listed, total, _, _ = _changes_lens_rows(feed, query="glossary")
    assert total == 2
    assert sum(1 for row in listed if row["kind"] == "changeset") == 1
    listed_all, _, _, _ = _changes_lens_rows(feed, query="sase-1bu.7")
    assert sum(1 for row in listed_all if row["kind"] == "changeset") == 1
    listed_none, _, _, _ = _changes_lens_rows(feed, query="no-such-thing")
    assert [row["kind"] for row in listed_none] == ["regen"]


def test_all_scopes_merge_and_tag_home() -> None:
    listed, total, _, _ = _changes_lens_rows(make_feed())
    views = [row["view"] for row in listed if row["kind"] == "changeset"]
    assert total == 2
    home = next(view for view in views if view.scope_key == "home")
    assert home.home is True


def test_failed_scope_shows_as_chip() -> None:
    detail = _changes_lens_header_detail(
        scope_label="project:sase",
        shown=2,
        total=2,
        failed_scopes=("home",),
    )
    assert "home unavailable" in detail
    assert "project:sase" in detail


def test_header_detail_names_window_and_regen() -> None:
    detail = _changes_lens_header_detail(
        scope_label="project:sase", shown=100, total=489, older=389, regen_folded=9
    )
    assert "last 100 of 489" in detail
    assert "9 regen-only folded" in detail
    assert _changes_lens_header_detail() == "no changes"


def test_changes_row_ids_are_stable() -> None:
    assert _changes_row_id("d" * 40, "project:sase") == _changes_row_id(
        "d" * 40, "project:sase"
    )
    assert _changes_row_id("d" * 40, "project:sase") != _changes_row_id(
        "e" * 40, "project:sase"
    )


def test_provenance_uses_artifact_icons() -> None:
    listed, _, _, _ = _changes_lens_rows(make_feed())
    view = next(row["view"] for row in listed if row["kind"] == "changeset")
    chips = _changes_provenance_text(view)
    assert "◈ sase-1bu.7" in chips
    assert "⬡ athena.sase-1bu.7" in chips
    assert "◉ ddddddd" in chips


def test_totals_count_subjects_and_regenerated() -> None:
    listed, _, _, _ = _changes_lens_rows(make_feed())
    view = next(row["view"] for row in listed if row["kind"] == "changeset")
    totals = _changes_totals_text(view)
    assert "1 subject" in totals
    assert "+20w" in totals
    assert "⟳ 1 regenerated" in totals


def test_section_titles_number_subjects() -> None:
    listed, _, _, _ = _changes_lens_rows(make_feed())
    view = next(row["view"] for row in listed if row["kind"] == "changeset")
    (subject,) = view.authored
    title = _changes_section_title(1, subject)
    assert title.startswith(".1 ◆ glossary/artifact")
    assert "+20w" in title


def test_lens_footer_names_configured_keys() -> None:
    from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps

    footer = _changes_lens_footer(MemoryPanelKeymaps())
    assert "j/k changeset" in footer
    assert "⏎/.N open" in footer
    assert "p/P scope" in footer
    assert "esc notes" in footer
    # The one-line footer ellipsizes past ~103 cells: the whole strip
    # must fit, including the newest verb.
    assert len(footer) <= 100
