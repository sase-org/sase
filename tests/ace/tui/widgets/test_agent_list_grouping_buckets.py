"""Tests for BY_DATE / BY_STATUS bucket banner rendering."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent_groups import GroupingMode
from sase.core.time import local_now
from sase.ace.tui.widgets._agent_list_styling import (
    _PATCH_BANNER_BAR_STYLE,
    _PATCH_BANNER_RULE_STYLE,
    _NAME_ROOT_BANNER_BRANCH_STYLE,
    _NAME_ROOT_BANNER_LABEL_STYLE,
    _PROJECT_BANNER_BAR_STYLE,
    _PROJECT_BANNER_RULE_STYLE,
    _STATUS_BUCKET_GLYPHS,
)
from sase.ace.tui.widgets.agent_list import AgentList

from ._agent_list_grouping_helpers import BR, make_agent


def _status_bucket_banner_labels(widget: AgentList) -> list[str]:
    labels: list[str] = []
    for option in widget._options:
        plain = option.prompt.plain  # type: ignore[union-attr]
        for bucket, glyph in _STATUS_BUCKET_GLYPHS.items():
            if plain.startswith(f"{glyph} {bucket}"):
                labels.append(bucket)
                break
    return labels


def test_by_date_mode_emits_bucket_banner_per_date_group() -> None:
    """In BY_DATE mode L0 banners are date buckets, Patch layer is dropped."""
    now = datetime(2026, 4, 25, 12, 0, 0)
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="a", start_time=now),  # Today
            make_agent(
                cl_name="b", start_time=datetime(2026, 4, 15, 9, 0, 0)
            ),  # Earlier
        ],
        current_idx=0,
        grouping_mode=GroupingMode.BY_DATE,
        now=now,
    )
    # Two L0 bucket banners (Today, Earlier), each with its date-aware
    # subgroup banner (1-hour under Today, week range under Earlier).
    # A spacer row separates the two L0 banners as in STANDARD mode.
    assert widget._row_entries == [
        BR,  # Today
        BR,  # 12:00
        (0, None),
        BR,  # spacer
        BR,  # Earlier
        BR,  # Apr 13-19
        (1, None),
    ]


def test_by_date_bucket_label_omits_project_bar() -> None:
    """BY_DATE bucket banners drop the ``▌`` project bar — bucket name leads."""
    now = datetime(2026, 4, 25, 12, 0, 0)
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="a", start_time=now),
            make_agent(cl_name="b", start_time=datetime(2026, 4, 25, 13, 0, 0)),
        ],
        current_idx=0,
        grouping_mode=GroupingMode.BY_DATE,
        now=now,
    )
    options = list(widget._options)
    plain = options[0].prompt.plain  # type: ignore[union-attr]
    # Bucket name leads — no ``▌`` bar prefix from STANDARD project mode.
    assert plain.startswith("Today")
    assert "▌" not in plain
    # Still uses the L0 sky-blue palette so visual hierarchy stays the same.
    spans = {s.style for s in options[0].prompt.spans}  # type: ignore[union-attr]
    assert _PROJECT_BANNER_BAR_STYLE in spans
    assert _PROJECT_BANNER_RULE_STYLE in spans


def test_by_status_mode_emits_status_bucket_banners() -> None:
    """BY_STATUS mode buckets agents by status; L0 = bucket, no Patch layer."""
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="a", status="RUNNING"),
            make_agent(cl_name="b", status="QUESTION"),
            make_agent(cl_name="c", status="DONE"),
        ],
        current_idx=0,
        grouping_mode=GroupingMode.BY_STATUS,
    )
    # Absent buckets are omitted.
    assert widget._row_entries == [
        BR,  # Stopped
        (1, None),
        BR,  # spacer
        BR,  # Running
        (0, None),
        BR,  # spacer
        BR,  # Done
        (2, None),
    ]


_STARTING_START_TIMES = pytest.mark.parametrize(
    "starting_start_time",
    [local_now(), datetime(2020, 1, 1, 0, 0, 0), None],
    ids=["fresh", "stale", "missing"],
)


@_STARTING_START_TIMES
def test_by_status_mode_hides_starting_bucket(
    starting_start_time: datetime | None,
) -> None:
    widget = AgentList()
    widget.update_list(
        [
            make_agent(
                cl_name="done",
                status="DONE",
                start_time=datetime(2026, 4, 26, 11, 0, 0),
            ),
            make_agent(
                cl_name="waiting",
                status="WAITING",
                start_time=datetime(2026, 4, 26, 10, 0, 0),
            ),
            make_agent(
                cl_name="queued",
                status="QUEUED",
                start_time=datetime(2026, 4, 26, 10, 30, 0),
            ),
            make_agent(
                cl_name="starting",
                status="STARTING",
                start_time=starting_start_time,
            ),
            make_agent(
                cl_name="running",
                status="RUNNING",
                start_time=datetime(2026, 4, 26, 9, 0, 0),
            ),
            make_agent(
                cl_name="failed",
                status="FAILED",
                start_time=datetime(2026, 4, 26, 8, 0, 0),
            ),
            make_agent(cl_name="question", status="QUESTION", start_time=None),
        ],
        current_idx=0,
        grouping_mode=GroupingMode.BY_STATUS,
    )

    assert _status_bucket_banner_labels(widget) == [
        "Stopped",
        "Failed",
        "Running",
        "Queued",
        "Waiting",
        "Done",
    ]
    assert all("starting" not in option.prompt.plain for option in widget._options)  # type: ignore[union-attr]


@_STARTING_START_TIMES
def test_standard_mode_hides_starting_agent_rows(
    starting_start_time: datetime | None,
) -> None:
    widget = AgentList()
    widget.update_list(
        [
            make_agent(
                cl_name="hidden-start",
                status="STARTING",
                start_time=starting_start_time,
            ),
            make_agent(cl_name="visible-run", status="RUNNING"),
        ],
        current_idx=0,
    )

    rendered_text = "\n".join(option.prompt.plain for option in widget._options)  # type: ignore[union-attr]
    assert "STARTING" not in rendered_text
    assert "hidden-start" not in rendered_text
    assert "visible-run" in rendered_text


def test_by_status_stopped_banner_carries_status_glyph() -> None:
    """``Stopped`` bucket leads with the ``▲`` status glyph."""
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="a", status="QUESTION")],
        current_idx=0,
        grouping_mode=GroupingMode.BY_STATUS,
    )
    options = list(widget._options)
    plain = options[0].prompt.plain  # type: ignore[union-attr]
    assert plain.startswith(f"{_STATUS_BUCKET_GLYPHS['Stopped']} Stopped")


def test_by_status_running_banner_carries_status_glyph() -> None:
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="a", status="RUNNING")],
        current_idx=0,
        grouping_mode=GroupingMode.BY_STATUS,
    )
    options = list(widget._options)
    plain = options[0].prompt.plain  # type: ignore[union-attr]
    assert plain.startswith(f"{_STATUS_BUCKET_GLYPHS['Running']} Running")


def test_by_date_mode_drops_patch_banner_even_when_cl_name_present() -> None:
    """The Patch banner disappears in BY_DATE mode regardless of cl_name."""
    now = datetime(2026, 4, 25, 12, 0, 0)
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="fix-bug-id", start_time=now)],
        current_idx=0,
        grouping_mode=GroupingMode.BY_DATE,
        now=now,
    )
    # Bucket banner + subgroup banner + agent — no Patch banner inserted.
    assert widget._row_entries == [BR, BR, (0, None)]
    options = list(widget._options)
    plain = options[0].prompt.plain  # type: ignore[union-attr]
    assert "fix-bug-id" not in plain


def test_by_status_name_root_banner_uses_existing_palette() -> None:
    """Name-root banners under a bucket reuse the teal STANDARD-mode style."""
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="", agent_name="coder.claude", status="RUNNING"),
            make_agent(cl_name="", agent_name="coder.codex", status="RUNNING"),
        ],
        current_idx=0,
        grouping_mode=GroupingMode.BY_STATUS,
    )
    options = list(widget._options)
    # Layout: bucket banner (Running), name-root banner (coder), agents.
    assert widget._row_entries == [BR, BR, (0, None), (1, None)]
    name_root_text = options[1].prompt
    plain = name_root_text.plain  # type: ignore[union-attr]
    assert "▸ coder " in plain
    spans = {s.style for s in name_root_text.spans}  # type: ignore[union-attr]
    assert _NAME_ROOT_BANNER_LABEL_STYLE in spans
    assert _NAME_ROOT_BANNER_BRANCH_STYLE in spans


def test_standard_mode_banner_unchanged_after_phase_2() -> None:
    """Regression guard: STANDARD mode behavior is byte-identical to Phase 1."""
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="fix-bug-id", project_file="/repo/sase_100/proj.sase")],
        current_idx=0,
        grouping_mode=GroupingMode.STANDARD,
    )
    options = list(widget._options)
    proj_plain = options[0].prompt.plain  # type: ignore[union-attr]
    cs_plain = options[1].prompt.plain  # type: ignore[union-attr]
    assert proj_plain.startswith("▌ sase_100")
    assert "fix-bug-id" in cs_plain
    cs_styles = {s.style for s in options[1].prompt.spans}  # type: ignore[union-attr]
    assert _PATCH_BANNER_BAR_STYLE in cs_styles
    assert _PATCH_BANNER_RULE_STYLE in cs_styles
