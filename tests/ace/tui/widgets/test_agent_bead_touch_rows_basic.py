"""Basic row tests for agent bead-touch rows (bead sase-14j.5).

Split from ``test_agent_bead_touch_rows``; shared helpers live in
``_agent_bead_touch_rows_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    append_agent_bead_touch_rows,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    COLOR_BEAD_CLOSED_PILL,
    COLOR_BEAD_CREATED_CAP,
    COLOR_BEAD_CREATED_CHIP,
    COLOR_BEAD_CREATED_PILL,
    COLOR_BEAD_PRIMARY,
    COLOR_BEAD_SUBHEADER,
    COLOR_REASON,
    COLOR_SUMMARY,
)
from tests.ace.tui.widgets._agent_bead_touch_rows_shared import (
    make_bead_touch_close,
    make_bead_touch_entry,
    pin_utc_timezone,
)
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers

__all__ = [
    "test_assigned_only_bead_renders_without_verbs",
    "test_assigned_only_bead_shows_resolved_title",
    "test_created_plus_closed_keeps_closed_pill_and_created_chip",
    "test_created_row_shows_pill_title_and_why",
    "test_created_row_without_reason_falls_back_to_title",
    "test_creation_reason_sanitizes_controls_and_bounds_lines",
    "test_empty_entries_appends_nothing",
    "test_read_reason_keeps_title_with_explicit_label",
    "test_row_order_palette_and_title",
    "test_truncated_creation_reason_links_to_bead_detail",
]


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_utc_timezone(monkeypatch)


# --- rows --------------------------------------------------------------------


def test_empty_entries_appends_nothing() -> None:
    text = Text()
    append_agent_bead_touch_rows(text, entries=())
    assert text.plain == ""


def test_row_order_palette_and_title() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-14g",
                "2026-05-24T16:41:02+00:00",
                verbs={"created": 1, "noted": 2},
                title="Custom gate with a failed command becomes unreachable",
            ),
            make_bead_touch_entry(
                "sase-l6.4",
                "2026-05-24T16:12:55+00:00",
                verbs={"closed": 1, "noted": 3},
                title="Stream SASE CONTEXT lanes progressively",
                own=True,
            ),
        ),
    )
    plain = text.plain
    assert plain.index("sase-14g") < plain.index("sase-l6.4")
    assert "16:41:02  ✚ sase-14g ▐CREATED▌ · noted ×2" in plain
    assert "16:12:55  ✓ sase-l6.4 · assigned · closed · noted ×3" in plain
    assert "↳ Custom gate with a failed command becomes unreachable" in plain
    assert "↳ Stream SASE CONTEXT lanes progressively" in plain
    assert_span_covers(text, "✚", COLOR_BEAD_SUBHEADER)
    assert_span_covers(text, "CREATED", COLOR_BEAD_CREATED_PILL)
    assert_span_covers(text, "▐", COLOR_BEAD_CREATED_CAP)
    assert_span_covers(text, "sase-14g", COLOR_BEAD_PRIMARY)
    assert_span_covers(text, "noted ×2", COLOR_SUMMARY)
    assert_span_covers(text, "assigned", COLOR_SUMMARY)
    assert_span_covers(text, "Stream SASE CONTEXT lanes progressively", COLOR_REASON)


def test_assigned_only_bead_renders_without_verbs() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text, entries=(make_bead_touch_entry("sase-14j.5", "", own=True, title=""),)
    )
    plain = text.plain
    assert "sase-14j.5 · assigned" in plain
    assert "×" not in plain
    assert "↳" not in plain
    assert_span_covers(text, "assigned", COLOR_SUMMARY)


def test_assigned_only_bead_shows_resolved_title() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-14j.5",
                "",
                own=True,
                title="File the retry race before the queue change lands",
            ),
        ),
    )
    plain = text.plain
    assert "sase-14j.5 · assigned" in plain
    assert "↳ File the retry race before the queue change lands" in plain
    assert "created" not in plain
    assert "CREATED" not in plain
    assert "why:" not in plain


def test_read_reason_keeps_title_with_explicit_label() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-14j.5",
                "2026-05-24T14:00:00+00:00",
                verbs={"read": 1},
                title="Bead title",
                read_reasons=("Need the scope",),
            ),
        ),
    )
    plain = text.plain
    assert "↳ Bead title" in plain
    assert "↳ read: Need the scope" in plain


def test_created_row_shows_pill_title_and_why() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-14g",
                "2026-05-24T16:41:02+00:00",
                verbs={"created": 1, "noted": 2},
                title="Fix retry race",
                creation_reason="A second agent reproduced dropped retries",
            ),
        ),
    )
    plain = text.plain
    assert "✚ sase-14g ▐CREATED▌ · noted ×2" in plain
    assert "· created" not in plain
    assert "↳ Fix retry race" in plain
    assert "↳ why: A second agent reproduced dropped retries" in plain
    assert_span_covers(text, "CREATED", COLOR_BEAD_CREATED_PILL)
    assert_span_covers(text, "▐", COLOR_BEAD_CREATED_CAP)
    assert_span_covers(text, "Fix retry race", COLOR_REASON)


def test_created_row_without_reason_falls_back_to_title() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-14g",
                "2026-05-24T16:41:02+00:00",
                verbs={"created": 1},
                title="Fix retry race",
            ),
        ),
    )
    plain = text.plain
    assert "▐CREATED▌" in plain
    assert "↳ Fix retry race" in plain
    assert "why:" not in plain


def test_created_plus_closed_keeps_closed_pill_and_created_chip() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-1a2",
                "2026-09-25T17:20:45+00:00",
                verbs={"created": 1, "closed": 1},
                title="Fix retry race",
                creation_reason="A second agent reproduced dropped retries",
                agent_close=make_bead_touch_close("2026-09-25T17:20:45+00:00"),
            ),
        ),
    )
    plain = text.plain
    assert "✓ sase-1a2 ▐CLOSED▌ · created" in plain
    assert "▐CREATED▌" not in plain
    assert "↳ Fix retry race" in plain
    assert "↳ why: A second agent reproduced dropped retries" in plain
    assert_span_covers(text, "CLOSED", COLOR_BEAD_CLOSED_PILL)
    assert_span_covers(text, "created", COLOR_BEAD_CREATED_CHIP)


def test_creation_reason_sanitizes_controls_and_bounds_lines() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-14g",
                "2026-05-24T16:41:02+00:00",
                verbs={"created": 1},
                title="Fix\x00 retry\x1b races",
                creation_reason="  why\x07 with\x1b[31m markup  ",
            ),
        ),
        line_cell_limit=40,
    )
    plain = text.plain
    assert "\x00" not in plain
    assert "\x07" not in plain
    assert "\x1b" not in plain
    assert "↳ Fix retry races" in plain
    assert "why:" in plain
    assert "… full reason in bead detail" not in plain
    for line in plain.splitlines():
        assert cell_len(line) <= 40 or "sase-14g" in line


def test_truncated_creation_reason_links_to_bead_detail() -> None:
    long_reason = " ".join(f"word-{index:02d}" for index in range(60))
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-14g",
                "2026-05-24T16:41:02+00:00",
                verbs={"created": 1},
                title="Fix retry race",
                creation_reason=long_reason,
                creation_reason_truncated=True,
            ),
        ),
        line_cell_limit=60,
    )
    plain = text.plain
    assert "↳ why: word-00" in plain
    assert "… full reason in bead detail" in plain
