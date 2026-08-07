"""Snooze metadata on every bead-detail surface.

The wake conditions are the whole point of the status, so a surface that
renders a snoozed bead without them is a bug rather than a style choice.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.console import Console

from sase.ace.tui.widgets.artifacts.beads_detail import (
    bead_preview_markdown,
    bead_properties_header,
)
from sase.ace.tui.widgets.artifacts.beads_rendering import task_text
from sase.bead.cli_detail import render_issue_detail
from sase.bead.cli_detail_json import issue_to_wire_dict
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.model import (
    Issue,
    IssueType,
    PhaseSize,
    SnoozeRecord,
    Status,
    TaskPlusOneEvidence,
)
from sase.bead_pages.rendering_identity import render_snooze

_PINNED_NOW = datetime(2026, 8, 6, 12, 0, 0)
_UNTIL = "2026-08-09T12:00:00-04:00"


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.core.time.local_now", lambda: _PINNED_NOW)


def _snoozed_task(
    *,
    plus_one_target: int | None = 3,
    plus_one_count: int = 1,
    reason: str = "waiting on the upstream fix",
) -> Issue:
    return Issue(
        id="alpha-1",
        title="A deferrable task",
        status=Status.SNOOZED,
        issue_type=IssueType.TASK,
        size=PhaseSize.SMALL,
        created_at="2026-08-01T09:00:00Z",
        updated_at="2026-08-06T09:00:00Z",
        plus_one_evidence=[
            TaskPlusOneEvidence(
                timestamp="2026-08-05T09:00:00Z",
                reporter=f"reporter-{index}",
                note="Reproduced independently",
            )
            for index in range(plus_one_count)
        ],
        snooze=SnoozeRecord(
            until=_UNTIL,
            snoozed_at="2026-08-06T09:00:00-04:00",
            snoozed_by="bryanbugyi34@gmail.com",
            plus_one_target=plus_one_target,
            plus_one_baseline=1,
            reason=reason,
        ),
    )


def _detail(issue: Issue) -> str:
    return render_issue_detail(
        IssueDetail(
            issue=issue,
            ancestors=(),
            phases=(),
            child_epics=(),
            depends_on=(),
            blocks=(),
            plan=None,
        ),
        relativize_design=False,
    )


def test_cli_detail_shows_both_wake_conditions_and_the_reason() -> None:
    block = _detail(_snoozed_task())

    assert "SNOOZE" in block
    assert "Until: 2026-08-09 12:00:00 EDT · in 3d" in block
    assert "+1 target: 2 more (3 total)" in block
    assert "Snoozed by: bryanbugyi34@gmail.com" in block
    assert "waiting on the upstream fix" in block


def test_cli_detail_omits_the_block_for_a_bead_that_is_not_snoozed() -> None:
    issue = Issue(id="alpha-2", title="Ordinary", issue_type=IssueType.TASK)

    assert "SNOOZE" not in _detail(issue)


def test_cli_detail_omits_the_plus_one_row_when_no_target_was_set() -> None:
    block = _detail(_snoozed_task(plus_one_target=None))

    assert "SNOOZE" in block
    assert "+1 target" not in block


def test_detail_json_derives_the_remaining_plus_ones_from_the_live_count() -> None:
    payload = issue_to_wire_dict(_snoozed_task())

    assert payload["snooze"] == {
        "until": _UNTIL,
        "snoozed_at": "2026-08-06T09:00:00-04:00",
        "snoozed_by": "bryanbugyi34@gmail.com",
        "plus_one_target": 3,
        "plus_one_baseline": 1,
        "reason": "waiting on the upstream fix",
        "plus_ones_remaining": 2,
    }


def test_detail_json_reports_null_for_a_bead_that_is_not_snoozed() -> None:
    issue = Issue(id="alpha-2", title="Ordinary", issue_type=IssueType.TASK)

    assert issue_to_wire_dict(issue)["snooze"] is None


def test_the_published_page_renders_the_wake_time_without_a_relative_form() -> None:
    lines = render_snooze(_snoozed_task())

    body = "\n".join(lines)
    assert "## Snooze" in body
    assert "2026-08-09 12:00:00 EDT" in body
    # A page is byte-stable, so it must not carry a label that ages.
    assert "in 3d" not in body
    assert "> **+1 target:** 2 more (3 total)" in body
    assert "waiting on the upstream fix" in body

    assert render_snooze(Issue(id="a", title="t", issue_type=IssueType.TASK)) == []


def test_the_beads_pane_detail_carries_a_wake_chip_and_a_snooze_property() -> None:
    console = Console(width=120, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                _snoozed_task(),
                None,
                project="alpha",
                project_name="Alpha",
            )
        )
    rendered = capture.get()

    assert "◈ in 3d" in rendered
    assert "Snooze" in rendered
    assert "snoozed · wakes in 3d" in rendered


def test_the_beads_pane_preview_repeats_the_snooze_line() -> None:
    preview = bead_preview_markdown(_snoozed_task(), None, project="alpha")

    assert "**Snooze:** 2026-08-09 12:00:00 EDT · in 3d" in preview
    assert "**Readiness:** snoozed · wakes in 3d" in preview


def test_the_filter_query_derives_its_snoozed_token_from_the_status_order() -> None:
    from sase.bead.filter_query import (
        DEFAULT_BEAD_FILTER_QUERY,
        parse_bead_filter_query,
    )

    assert parse_bead_filter_query("status:snoozed").statuses == ("snoozed",)
    assert parse_bead_filter_query("-status:snoozed").excluded_statuses == ("snoozed",)
    # A snoozed task is live work the user chose to defer, so the default
    # filter keeps showing it; hiding it would make the status a black hole.
    assert "snoozed" not in DEFAULT_BEAD_FILTER_QUERY


def test_a_list_row_reads_correctly_without_opening_detail() -> None:
    row = task_text(_snoozed_task(), triage=False, plan_link=False).plain

    assert "◈ snoozed" in row
    assert "◈ in 3d" in row
