"""Basics for the pager time band: vocabulary, sparkline, chrome, honest states."""

from __future__ import annotations

import datetime

from rich.cells import cell_len

from sase.memory.history import vocabulary as shared_vocabulary
from sase.memory.history import render_text as shared_render_text
from sase.pager import _time_band as time_band
from tests.pager.test_time_band._fixtures import NOW, make_timeline, make_version


def test_glyph_and_hidden_tables_match_shared_vocabulary() -> None:
    assert time_band.CLASS_GLYPHS == shared_vocabulary.CLASS_GLYPHS
    assert set(time_band.HIDDEN_CLASSES) == set(shared_vocabulary.HIDDEN_CLASSES)
    # Every shared class paints its shared glyph in a meaning row, so the
    # pager mirror cannot drift from the CLI vocabulary.
    for class_name, glyph in shared_vocabulary.CLASS_GLYPHS.items():
        timeline = make_timeline(
            make_version(1, class_name="created", volume=8),
            make_version(
                2,
                class_name=class_name,
                volume=4,
                bead="sase-1au.5",
                agent="athena",
                sections=("Section",),
            ),
        )
        data = time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=timeline,
            current_ordinal=2,
            now_epoch=NOW,
            total_visible=2,
        )
        assert data is not None
        row = time_band.render_time_band(data, width=200, rows=1).plain
        assert glyph in row, class_name


def test_format_age_matches_shared_renderer() -> None:
    # The pill context still renders relative ages through the shared
    # vocabulary, so the pager mirror must never drift from the CLI.
    for delta in (3, 90, 7200, 3 * 86400, 60 * 86400, 400 * 86400):
        expected = shared_render_text.format_age(1_000_000 + delta, 1_000_000)
        assert time_band.format_age(1_000_000 + delta, 1_000_000) == expected


def test_short_display_matches_shared_renderer() -> None:
    subjects = [
        "note:project:sase/tui",
        "strand:project:sase/glossary/stitch",
        "instructions:project:sase/.",
        "instructions:project:sase/src/sase/ace",
        "web:project:sase/glossary",
        "asset:project:sase/logo.png",
    ]
    for subject in subjects:
        assert time_band.short_display_for_subject_id(subject) == (
            shared_render_text.short_display_for_subject_id(subject)
        )


def test_sparkline_scales_logarithmically_and_marks_current() -> None:
    rendered = time_band.render_sparkline([0, 100], ["authored", "authored"], None, 2)
    assert (
        rendered.plain == time_band.SPARKLINE_BLOCKS[0] + time_band.SPARKLINE_BLOCKS[-1]
    )
    current = time_band.render_sparkline([1, 100], ["authored", "authored"], 1, 2)
    assert len(current.spans) >= 1
    assert any("reverse" in str(span.style) for span in current.spans)
    hidden = time_band.render_sparkline([5], ["moved"], None, 1)
    assert hidden.plain == time_band.HIDDEN_CELL
    deleted = time_band.render_sparkline([5], ["deleted"], None, 1)
    assert any("red" in str(span.style) for span in deleted.spans)


def test_sparkline_buckets_more_versions_than_cells() -> None:
    rendered = time_band.render_sparkline([1, 2, 3, 4, 5, 6], ["authored"] * 6, 5, 3)
    assert cell_len(rendered.plain) == 3
    assert time_band.render_sparkline([], [], None, 10).plain == ""
    assert time_band.render_sparkline([1], ["authored"], None, 0).plain == ""


def test_chrome_row_budget_matrix() -> None:
    # Hidden time state never takes rows; the trail keeps its own rule.
    assert time_band.chrome_row_budget(40, True, "hidden") == (2, 0)
    assert time_band.chrome_row_budget(40, False, "hidden") == (0, 0)
    assert time_band.chrome_row_budget(40, False, None) == (0, 0)
    # Now is always one row once the band is tall enough to show.
    assert time_band.chrome_row_budget(40, False, "now") == (0, 1)
    assert time_band.chrome_row_budget(50, True, "now") == (2, 1)
    # Past is two rows at full height, one row when constrained.
    assert time_band.chrome_row_budget(50, False, "past") == (0, 2)
    assert time_band.chrome_row_budget(50, True, "past") == (2, 2)
    assert time_band.chrome_row_budget(29, False, "past") == (0, 1)
    assert time_band.chrome_row_budget(39, True, "past") == (2, 1)
    assert time_band.chrome_row_budget(40, True, "past") == (2, 2)
    assert time_band.chrome_row_budget(30, False, "past") == (0, 2)
    # At 12 rows or fewer the band folds into the subject chip.
    for height in (12, 10, 5):
        assert time_band.chrome_row_budget(height, True, "past") == (1, 0)
        assert time_band.chrome_row_budget(height, False, "now") == (0, 0)


def test_honest_states_cover_every_kind() -> None:
    indexing = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=None,
        current_ordinal=0,
        loading=True,
        now_epoch=NOW,
    )
    assert indexing is not None and indexing.mode == "notice"
    cases = [
        ({"state": "untracked"}, "UNTRACKED"),
        ({"state": "ignored"}, "IGNORED"),
        ({"state": "NO_VCS"}, "NO VCS"),
        ({"state": "tracked", "error": "boom"}, "boom"),
    ]
    for wire, label in cases:
        data = time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=dict(wire),
            current_ordinal=0,
            now_epoch=NOW,
        )
        assert data is not None and data.mode == "notice"
        assert label in time_band.render_time_band(data, width=120, rows=1).plain
    shallow = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=make_timeline(
            make_version(1, volume=1),
            health={"shallow": True, "shallow_boundary_time": 0},
        ),
        current_ordinal=0,
        now_epoch=NOW,
        total_visible=1,
    )
    assert shallow is not None and shallow.honest_kind == "shallow"
    template = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=make_timeline(make_version(1, volume=1), is_template=True),
        current_ordinal=0,
        now_epoch=NOW,
        total_visible=1,
    )
    assert template is not None and template.honest_kind == "template"
    clean = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=make_timeline(make_version(1, volume=1)),
        current_ordinal=0,
        now_epoch=NOW,
        total_visible=1,
    )
    assert clean is not None and clean.honest_kind == "ok"


def test_notice_modes_for_states_without_history() -> None:
    for state, label in (
        ("untracked", "UNTRACKED"),
        ("ignored", "IGNORED"),
        ("NO_VCS", "NO VCS"),
    ):
        data = time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=make_timeline(state=state),
            current_ordinal=0,
            now_epoch=NOW,
        )
        assert data is not None and data.mode == "notice"
        rendered = time_band.render_time_band(data, width=120, rows=1)
        assert label in rendered.plain
    indexing = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=None,
        current_ordinal=0,
        loading=True,
        now_epoch=NOW,
    )
    assert indexing is not None and indexing.mode == "notice"
    assert "indexing" in time_band.render_time_band(indexing, width=120, rows=1).plain


def test_life_strip_shows_scrubber_date_owner_and_dirty() -> None:
    data = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=make_timeline(
            make_version(1, volume=8, committer_time=NOW - 3 * 86400),
            make_version(
                2,
                volume=2,
                bead="sase-1bc.12",
                agent="athena",
                committer_time=NOW - 3 * 86400,
            ),
        ),
        current_ordinal=0,
        dirty=True,
        now_epoch=NOW,
        total_visible=2,
    )
    assert data is not None and data.mode == "now"
    rendered = time_band.render_time_band(data, width=120, rows=1)
    expected_day = datetime.datetime.fromtimestamp(NOW - 3 * 86400).strftime(
        "%a %b %d %Y"
    )
    assert "v1" in rendered.plain and "◌ now" in rendered.plain
    assert f"last changed {expected_day}" in rendered.plain
    assert "athena.sase-1bc.12" in rendered.plain
    assert "edits not durable until committed" in rendered.plain
    clean = time_band.render_time_band(
        time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=make_timeline(make_version(1, volume=8)),
            current_ordinal=0,
            now_epoch=NOW,
            total_visible=1,
        ),
        width=120,
        rows=1,
    )
    assert "edits not durable" not in clean.plain
    assert "● now" in clean.plain
    assert "last changed" in clean.plain
