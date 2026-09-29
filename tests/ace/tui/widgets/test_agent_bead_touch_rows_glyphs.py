"""Glyph and verb-chip tests for agent bead-touch rows (bead sase-14j.5).

Split from ``test_agent_bead_touch_rows``; shared helpers live in
``_agent_bead_touch_rows_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    _bead_touch_glyph,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    ARTIFACT_READ_GLYPH,
    BEAD_CLOSED_GLYPH,
    BEAD_CREATED_GLYPH,
    BEAD_EDITED_GLYPH,
    BEAD_REMOVED_GLYPH,
    BEAD_REOPENED_GLYPH,
    MEMORY_GLYPH,
)
from tests.ace.tui.widgets._agent_bead_touch_rows_shared import (
    bead_chip_names,
    make_bead_touch_entry,
    pin_utc_timezone,
)

__all__ = [
    "test_bead_glyphs_are_single_cell",
    "test_created_row_reports_no_assignment_chip",
    "test_glyph_precedence_closed_over_created_over_edited_over_read",
    "test_single_counts_carry_no_suffix",
    "test_verb_chip_order_assigned_then_durable_then_read_then_viewed",
]


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_utc_timezone(monkeypatch)


# --- glyphs ------------------------------------------------------------------


def test_bead_glyphs_are_single_cell() -> None:
    for glyph in (
        BEAD_CREATED_GLYPH,
        BEAD_CLOSED_GLYPH,
        BEAD_REOPENED_GLYPH,
        BEAD_EDITED_GLYPH,
        BEAD_REMOVED_GLYPH,
        ARTIFACT_READ_GLYPH,
        MEMORY_GLYPH,
    ):
        assert cell_len(glyph) == 1


def test_glyph_precedence_closed_over_created_over_edited_over_read() -> None:
    assert (
        _bead_touch_glyph(
            make_bead_touch_entry(
                "sase-1",
                "2026-05-24T14:00:00+00:00",
                verbs={"created": 1, "closed": 1, "noted": 2},
            )
        )
        == BEAD_CLOSED_GLYPH
    )
    assert (
        _bead_touch_glyph(
            make_bead_touch_entry(
                "sase-1", "2026-05-24T14:00:00+00:00", verbs={"closed": 1, "noted": 3}
            )
        )
        == BEAD_CLOSED_GLYPH
    )
    assert (
        _bead_touch_glyph(
            make_bead_touch_entry(
                "sase-1", "2026-05-24T14:00:00+00:00", verbs={"reopened": 1, "noted": 1}
            )
        )
        == BEAD_REOPENED_GLYPH
    )
    assert (
        _bead_touch_glyph(
            make_bead_touch_entry(
                "sase-1", "2026-05-24T14:00:00+00:00", verbs={"noted": 2, "read": 1}
            )
        )
        == BEAD_EDITED_GLYPH
    )
    assert (
        _bead_touch_glyph(
            make_bead_touch_entry(
                "sase-1", "2026-05-24T14:00:00+00:00", verbs={"read": 2}
            )
        )
        == ARTIFACT_READ_GLYPH
    )
    assert (
        _bead_touch_glyph(
            make_bead_touch_entry(
                "sase-1", "2026-05-24T14:00:00+00:00", verbs={"viewed": 1}
            )
        )
        == MEMORY_GLYPH
    )
    assert (
        _bead_touch_glyph(
            make_bead_touch_entry(
                "sase-1", "2026-05-24T14:00:00+00:00", verbs={"removed": 1}
            )
        )
        == BEAD_REMOVED_GLYPH
    )
    assert (
        _bead_touch_glyph(make_bead_touch_entry("sase-1", "", own=True)) == MEMORY_GLYPH
    )


def test_verb_chip_order_assigned_then_durable_then_read_then_viewed() -> None:
    entry = make_bead_touch_entry(
        "sase-1",
        "2026-05-24T14:00:00+00:00",
        verbs={"noted": 3, "closed": 1, "read": 2, "viewed": 1},
        own=True,
    )
    assert bead_chip_names(entry) == [
        "assigned",
        "noted ×3",
        "closed",
        "read ×2",
        "viewed",
    ]


def test_created_row_reports_no_assignment_chip() -> None:
    entry = make_bead_touch_entry(
        "sase-1",
        "2026-05-24T14:00:00+00:00",
        verbs={"created": 1, "noted": 1},
        own=True,
    )
    # The ▐CREATED▌ pill carries creator credit, so no chip doubles it.
    assert bead_chip_names(entry) == ["noted"]


def test_single_counts_carry_no_suffix() -> None:
    entry = make_bead_touch_entry(
        "sase-1", "2026-05-24T14:00:00+00:00", verbs={"noted": 1, "dep": 1}
    )
    assert bead_chip_names(entry) == ["noted", "dep"]
