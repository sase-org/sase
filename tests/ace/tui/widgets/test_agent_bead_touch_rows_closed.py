"""Standing-close pill tests for agent bead-touch rows (bead sase-19p.3).

Split from ``test_agent_bead_touch_rows``; shared helpers live in
``_agent_bead_touch_rows_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._agent_artifacts_lane import (
    append_agent_artifacts_lane,
)
from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    MAX_VISIBLE_BEADS,
    append_agent_bead_touch_rows,
    _visible_bead_entries,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    COLOR_BEAD_CLOSED_CAP,
    COLOR_BEAD_CLOSED_GLYPH,
    COLOR_BEAD_CLOSED_MUTED_CAP,
    COLOR_BEAD_CLOSED_MUTED_GLYPH,
    COLOR_BEAD_CLOSED_MUTED_PILL,
    COLOR_BEAD_CLOSED_PILL,
    COLOR_BEAD_CLOSED_STALE,
    COLOR_BEAD_CREATED_CHIP,
    COLOR_BEAD_REOPENED_SINCE,
    COLOR_BEAD_RESOLUTION,
    COLOR_BEAD_SUBHEADER,
    COLOR_SUMMARY,
)
from tests.ace.tui.widgets._agent_bead_touch_rows_shared import (
    make_bead_touch_close,
    make_bead_touch_entry,
    make_header_hint_state,
    pin_utc_timezone,
)
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers

__all__ = [
    "test_lane_header_announces_standing_close_count",
    "test_lane_header_without_closes_is_unchanged",
    "test_narrow_console_keeps_pill_contiguous",
    "test_no_close_row_renders_exactly_as_before",
    "test_non_standing_row_keeps_struck_closed_and_reopened_since",
    "test_overflow_footer_uses_hidden_earliest_and_hidden_closed",
    "test_standing_canceled_row_shows_grey_pill_and_resolution",
    "test_standing_close_keeps_labeled_title_close_and_read",
    "test_standing_close_without_reason_falls_back_to_title",
    "test_standing_done_row_shows_pill_and_drops_closed_chip",
    "test_visible_selection_keeps_older_standing_close_and_hints",
]


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_utc_timezone(monkeypatch)


# --- closed pill (sase-19p.3) --------------------------------------------------


def test_standing_done_row_shows_pill_and_drops_closed_chip() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-19f.2",
                "2026-09-25T17:34:01+00:00",
                verbs={"closed": 1, "noted": 2},
                title="Render agent-closed beads distinctly",
                own=True,
                agent_close=make_bead_touch_close("2026-09-25T17:34:01+00:00"),
            ),
        ),
    )
    plain = text.plain
    assert "✓ sase-19f.2 ▐CLOSED▌ · assigned · noted ×2" in plain
    assert "· closed" not in plain
    assert_span_covers(text, "✓", COLOR_BEAD_CLOSED_GLYPH)
    assert_span_covers(text, "▐", COLOR_BEAD_CLOSED_CAP)
    assert_span_covers(text, "CLOSED", COLOR_BEAD_CLOSED_PILL)
    assert_span_covers(text, "▌", COLOR_BEAD_CLOSED_CAP)
    assert_span_covers(text, "assigned", COLOR_SUMMARY)


def test_standing_canceled_row_shows_grey_pill_and_resolution() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-1a2",
                "2026-09-25T17:20:45+00:00",
                verbs={"closed": 1, "created": 1},
                title="duplicate",
                agent_close=make_bead_touch_close(
                    "2026-09-25T17:20:45+00:00",
                    resolution="canceled",
                    reason="duplicate of sase-19z",
                ),
            ),
        ),
    )
    plain = text.plain
    assert "✓ sase-1a2 ▐CLOSED▌ · canceled · created" in plain
    assert_span_covers(text, "✓", COLOR_BEAD_CLOSED_MUTED_GLYPH)
    assert_span_covers(text, "▐", COLOR_BEAD_CLOSED_MUTED_CAP)
    assert_span_covers(text, "CLOSED", COLOR_BEAD_CLOSED_MUTED_PILL)
    assert_span_covers(text, "canceled", COLOR_BEAD_RESOLUTION)
    assert "↳ canceled: duplicate of sase-19z" in plain


def test_non_standing_row_keeps_struck_closed_and_reopened_since() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-17m.4",
                "2026-09-25T16:02:55+00:00",
                verbs={"noted": 1, "closed": 1},
                title="Legacy close attribution",
                agent_close=make_bead_touch_close(
                    "2026-09-25T16:02:55+00:00", standing=False
                ),
            ),
        ),
    )
    plain = text.plain
    assert "▐CLOSED▌" not in plain
    assert "· noted · closed · reopened since" in plain
    assert "↳ Legacy close attribution" in plain
    assert_span_covers(text, "✓", COLOR_BEAD_SUBHEADER)
    assert_span_covers(text, "closed", COLOR_BEAD_CLOSED_STALE)
    assert_span_covers(text, "reopened since", COLOR_BEAD_REOPENED_SINCE)


def test_no_close_row_renders_exactly_as_before() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-19f",
                "2026-09-25T16:58:02+00:00",
                verbs={"noted": 1},
                title="Agent-closed beads in the Context card",
            ),
        ),
    )
    plain = text.plain
    assert "✎ sase-19f · noted" in plain
    assert "▐CLOSED▌" not in plain
    assert "↳ Agent-closed beads in the Context card" in plain
    assert_span_covers(text, "✎", COLOR_BEAD_SUBHEADER)


def test_standing_close_keeps_labeled_title_close_and_read() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-19f.2",
                "2026-09-25T17:34:01+00:00",
                verbs={"closed": 1},
                title="Bead title",
                read_reasons=("Need the scope",),
                agent_close=make_bead_touch_close(
                    "2026-09-25T17:34:01+00:00", reason="Phase checks green"
                ),
            ),
        ),
    )
    plain = text.plain
    assert "↳ Bead title" in plain
    assert "↳ closed: Phase checks green" in plain
    assert "↳ read: Need the scope" in plain


def test_standing_close_without_reason_falls_back_to_title() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-19f.2",
                "2026-09-25T17:34:01+00:00",
                verbs={"closed": 1},
                title="Bead title",
                agent_close=make_bead_touch_close("2026-09-25T17:34:01+00:00"),
            ),
        ),
    )
    assert "↳ Bead title" in text.plain


def test_lane_header_announces_standing_close_count() -> None:
    text = Text()
    append_agent_artifacts_lane(
        text,
        bead_touch_entries=(
            make_bead_touch_entry(
                "sase-19f.2",
                "2026-09-25T17:34:01+00:00",
                verbs={"closed": 1},
                title="t",
                agent_close=make_bead_touch_close("2026-09-25T17:34:01+00:00"),
            ),
            make_bead_touch_entry(
                "sase-1a2",
                "2026-09-25T17:20:45+00:00",
                verbs={"closed": 1},
                title="t",
                agent_close=make_bead_touch_close(
                    "2026-09-25T17:20:45+00:00", resolution="canceled"
                ),
            ),
            make_bead_touch_entry(
                "sase-19f",
                "2026-09-25T16:58:02+00:00",
                verbs={"noted": 1},
                title="t",
            ),
        ),
    )
    plain = text.plain
    assert "▸ ARTIFACTS · 3 beads (✓ 2 closed)\n" in plain
    assert_span_covers(text, "✓ 2 closed", COLOR_BEAD_CLOSED_GLYPH)


def test_lane_header_without_closes_is_unchanged() -> None:
    text = Text()
    append_agent_artifacts_lane(
        text,
        bead_touch_entries=(
            make_bead_touch_entry(
                "sase-19f",
                "2026-09-25T16:58:02+00:00",
                verbs={"noted": 1},
                title="t",
            ),
        ),
    )
    assert "▸ ARTIFACTS · 1 bead\n" in text.plain
    assert "closed" not in text.plain.splitlines()[0]


def test_visible_selection_keeps_older_standing_close_and_hints() -> None:
    entries = tuple(
        make_bead_touch_entry(
            f"sase-{index}",
            f"2026-05-24T14:{30 - index:02d}:00+00:00",
            verbs={"noted": 1},
            title=f"title {index}",
        )
        for index in range(MAX_VISIBLE_BEADS + 1)
    ) + (
        make_bead_touch_entry(
            "sase-old",
            "2026-05-24T13:00:00+00:00",
            verbs={"closed": 1},
            title="old close",
            agent_close=make_bead_touch_close("2026-05-24T13:00:00+00:00"),
        ),
    )
    visible = _visible_bead_entries(entries)
    assert len(visible) == MAX_VISIBLE_BEADS
    assert visible[-1].bead_id == "sase-old"

    state = make_header_hint_state(start=7)
    text = Text()
    append_agent_bead_touch_rows(text, entries=entries, hint_state=state)
    plain = text.plain
    assert "sase-old" in plain
    assert "▐CLOSED▌" in plain
    assert state.hint_mappings[7 + MAX_VISIBLE_BEADS - 1] == "bead:sase-old"
    assert state.hint_counter == 7 + MAX_VISIBLE_BEADS


def test_overflow_footer_uses_hidden_earliest_and_hidden_closed() -> None:
    many = tuple(
        make_bead_touch_entry(
            f"sase-c{index}",
            f"2026-05-24T14:{30 - index:02d}:00+00:00",
            verbs={"closed": 1},
            title="t",
            agent_close=make_bead_touch_close(
                f"2026-05-24T14:{30 - index:02d}:00+00:00"
            ),
        )
        for index in range(MAX_VISIBLE_BEADS + 2)
    )
    text = Text()
    append_agent_bead_touch_rows(text, entries=many)
    plain = text.plain
    assert f"+ 2 more · {many[-1].last_at[11:16]} earliest (✓ 2 closed)" in plain
    assert_span_covers(text, "✓ 2 closed", COLOR_BEAD_CLOSED_GLYPH)


def test_narrow_console_keeps_pill_contiguous() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-19f.2",
                "2026-09-25T17:34:01+00:00",
                verbs={"closed": 1, "noted": 2},
                title="Render agent-closed beads distinctly",
                own=True,
                agent_close=make_bead_touch_close("2026-09-25T17:34:01+00:00"),
            ),
        ),
        line_cell_limit=40,
    )
    output = StringIO()
    console = Console(file=output, width=40, color_system=None)
    console.print(text, end="")
    rendered = output.getvalue()
    assert "▐CLOSED▌" in rendered
    assert "▐CLOSED" not in rendered.replace("▐CLOSED▌", "")
    for line in rendered.splitlines():
        assert cell_len(line) <= 40 or "sase-19f.2" in line
