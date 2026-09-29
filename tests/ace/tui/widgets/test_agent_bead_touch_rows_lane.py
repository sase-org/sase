"""Artifacts-lane and clan tests for agent bead-touch rows (bead sase-14j.5).

Split from ``test_agent_bead_touch_rows``; shared helpers live in
``_agent_bead_touch_rows_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._agent_artifacts_lane import (
    append_agent_artifacts_lane,
)
from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    append_agent_bead_touch_rows,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    COLOR_SUMMARY,
    REASON_LINE_CELL_LIMIT,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_clan_context import (
    clan_context_entry_hint_target,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
)
from sase.ace.tui.models._agent_clan_sections import ClanContextEntry
from tests.ace.tui.widgets._agent_bead_touch_rows_shared import (
    make_artifact_read_display,
    make_artifact_read_event,
    make_bead_touch_entry,
    pin_utc_timezone,
    render_header_lines,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers

__all__ = [
    "test_bead_id_never_truncates_at_narrow_widths",
    "test_bead_read_migrates_out_of_reads",
    "test_beads_lead_reads_in_lane_and_header",
    "test_cheap_header_renders_beads_without_index_read",
    "test_clan_hint_target_rejects_invalid_bead_id",
    "test_clan_hint_target_returns_bead_ref",
    "test_empty_beads_renders_no_subsection_or_count",
    "test_long_title_wraps_within_cell_limit",
]


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_utc_timezone(monkeypatch)


# --- lane --------------------------------------------------------------------


def test_beads_lead_reads_in_lane_and_header() -> None:
    text = Text()
    append_agent_artifacts_lane(
        text,
        artifact_reads=(
            make_artifact_read_display(
                make_artifact_read_event(
                    ref="plan:202608/design.md",
                    timestamp="2026-05-24T14:22:08+00:00",
                    read_id="read-1",
                )
            ),
        ),
        bead_touch_entries=(
            make_bead_touch_entry(
                "sase-14g", "2026-05-24T16:41:02+00:00", verbs={"created": 1}, title="t"
            ),
        ),
    )
    plain = text.plain
    assert "▸ ARTIFACTS · 1 bead · 1 read\n" in plain
    assert plain.index("  Beads:") < plain.index("  Reads:")
    assert_span_covers(text, "  Beads:", COLOR_SUMMARY)


def test_bead_read_migrates_out_of_reads() -> None:
    bead_read = make_artifact_read_display(
        make_artifact_read_event(
            ref="bead:sase-14j.4",
            timestamp="2026-05-24T14:22:08+00:00",
            read_id="read-bead",
            resolved_path=None,
        )
    )
    text = Text()
    append_agent_artifacts_lane(
        text,
        artifact_reads=(bead_read,),
        bead_touch_entries=(
            make_bead_touch_entry(
                "sase-14j.4", "2026-05-24T14:22:08+00:00", verbs={"read": 1}, title="t"
            ),
        ),
    )
    plain = text.plain
    assert "▸ ARTIFACTS · 1 bead\n" in plain
    assert "  Reads:" not in plain
    assert plain.count("sase-14j.4") == 1
    assert "← bead:sase-14j.4" not in plain
    assert "← sase-14j.4" in plain


def test_empty_beads_renders_no_subsection_or_count() -> None:
    text = Text()
    append_agent_artifacts_lane(
        text,
        artifact_reads=(
            make_artifact_read_display(
                make_artifact_read_event(
                    ref="plan:202608/design.md",
                    timestamp="2026-05-24T14:22:08+00:00",
                    read_id="read-1",
                )
            ),
        ),
        bead_touch_entries=(),
    )
    assert "  Beads:" not in text.plain
    assert "bead" not in text.plain.splitlines()[0]


def test_bead_id_never_truncates_at_narrow_widths() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="worker"),
        summary=DetailHeaderSummary(
            bead_touch_entries=(
                make_bead_touch_entry(
                    "sase-14j.5",
                    "2026-05-24T16:41:02+00:00",
                    verbs={"created": 1, "noted": 2},
                    title="Custom gate with a failed command becomes unreachable",
                ),
            ),
        ),
    )
    for width in (120, 28):
        rendered = "\n".join(render_header_lines(header, width=width))
        assert "sase-14j.5" in rendered
        row = next(line for line in rendered.splitlines() if "sase-14j.5" in line)
        assert "…" not in row


def test_long_title_wraps_within_cell_limit() -> None:
    long_title = " ".join(f"title-word-{index:02d}" for index in range(18))
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-14j.5",
                "2026-05-24T14:00:00+00:00",
                verbs={"noted": 1},
                title=long_title,
            ),
        ),
    )
    assert "…" not in text.plain
    assert long_title in " ".join(text.plain.split())
    for line in text.plain.splitlines():
        assert cell_len(line) <= REASON_LINE_CELL_LIMIT


def test_cheap_header_renders_beads_without_index_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("cheap header must not read the touch index")

    monkeypatch.setattr(
        "sase.ace.tui.bead_touches.load_bead_touches_for_agent_context", fail
    )
    monkeypatch.setattr("sase.ace.tui._bead_touches_loader.query_touch_index", fail)
    header, _ = build_header_text(
        make_agent(agent_name="worker"),
        cheap=True,
        summary=DetailHeaderSummary(
            bead_touch_entries=(
                make_bead_touch_entry(
                    "sase-14j.5",
                    "2026-05-24T16:41:02+00:00",
                    verbs={"created": 1},
                    title="t",
                ),
            ),
        ),
    )
    assert "  Beads:\n" in header.plain
    assert "sase-14j.5" in header.plain


# --- clan --------------------------------------------------------------------


def test_clan_hint_target_returns_bead_ref() -> None:
    entry = ClanContextEntry(
        key="sase-14j.5",
        label="sase-14j.5",
        member_labels=("a",),
        values=(
            make_bead_touch_entry(
                "sase-14j.5", "2026-05-24T14:00:00+00:00", verbs={"noted": 1}
            ),
        ),
    )
    assert (
        clan_context_entry_hint_target(
            "ARTIFACTS",
            entry,
            member_workspaces={},
            fallback_workspace=None,
        )
        == "bead:sase-14j.5"
    )


def test_clan_hint_target_rejects_invalid_bead_id() -> None:
    entry = ClanContextEntry(
        key="bad",
        label="bad",
        member_labels=("a",),
        values=(make_bead_touch_entry("not a bead id!!", "", verbs={"noted": 1}),),
    )
    assert (
        clan_context_entry_hint_target(
            "ARTIFACTS",
            entry,
            member_workspaces={},
            fallback_workspace=None,
        )
        is None
    )
