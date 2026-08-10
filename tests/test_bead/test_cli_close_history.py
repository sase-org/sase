"""``sase bead`` rendering of archived close history and reopen provenance."""

from __future__ import annotations

import argparse
import json

import pytest

from sase.bead.cli_detail import render_issue_detail
from sase.bead.cli_detail_json import issue_to_wire_dict
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_query import (
    _render_list_compact,
    _render_search_compact,
    _search_field_value,
    handle_bead_blocked,
    handle_bead_ready,
)
from sase.bead.filter_query import BEAD_HAS_VALUES
from sase.bead.model import (
    BeadSearchMatch,
    CloseRecord,
    Dependency,
    Issue,
    IssueType,
    ReopenCause,
    Resolution,
    Status,
)
from tests.test_bead.cli_show_style_test_helpers import (
    REOPENED_TASK_ID,
    REOPENING_REPORTER,
    REOPENING_TIMESTAMP,
    build_reopened_task,
    read_golden,
    render,
    strip_sgr,
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


def _reopened_issue() -> Issue:
    issues, target_id = build_reopened_task()
    return issues[target_id]


def _lines(text: str) -> list[str]:
    return text.split("\n")


class TestDetailSection:
    def test_the_section_renders_every_record_newest_first(self) -> None:
        out = _detail(_reopened_issue())

        assert "PREVIOUSLY CLOSED" in out
        first = out.index("↺ Closed 2026-07-30T09:12:04Z · canceled")
        second = out.index("↺ Closed 2026-07-16T11:00:00Z · (unrecorded)")
        assert first < second

    def test_a_record_reads_closed_then_why_then_reopened(self) -> None:
        out = _lines(_detail(_reopened_issue()))
        start = out.index("  ↺ Closed 2026-07-30T09:12:04Z · canceled")

        assert out[start + 1 : start + 4] == [
            "    Reason:",
            "      Not reproducible on main; the retry shim already covers this.",
            f"    Reopened {REOPENING_TIMESTAMP} by a +1 from @{REOPENING_REPORTER}",
        ]

    def test_a_record_without_a_reason_still_reports_the_absence(self) -> None:
        out = _lines(_detail(_reopened_issue()))
        start = out.index("  ↺ Closed 2026-07-16T11:00:00Z · (unrecorded)")

        assert out[start + 1 : start + 3] == [
            "    Reason: (none)",
            "    Reopened 2026-07-18T12:00:00Z by `sase bead open`",
        ]

    def test_the_section_sits_above_the_description(self) -> None:
        issue = _reopened_issue()
        issue.description = "Body prose."

        out = _detail(issue)

        assert out.index("PREVIOUSLY CLOSED") < out.index("DESCRIPTION")

    def test_a_closed_again_bead_shows_the_current_close_first(self) -> None:
        issue = _reopened_issue()
        issue.status = Status.CLOSED
        issue.closed_at = "2026-08-09T00:00:00Z"
        issue.resolution = Resolution.DONE

        out = _detail(issue)

        assert out.index("RESOLUTION") < out.index("PREVIOUSLY CLOSED")

    def test_a_bead_that_was_never_reopened_renders_no_section(self) -> None:
        issue = Issue(id="bd-plain", title="Plain Task", issue_type=IssueType.TASK)

        assert "PREVIOUSLY CLOSED" not in _detail(issue)


class TestDetailBadgeAndEvidenceMarker:
    def test_the_header_carries_both_badges(self) -> None:
        header = _lines(_detail(_reopened_issue()))[0]

        assert header.endswith("[READY] [+2] [↺2]")

    def test_only_the_joining_entry_is_marked_as_the_reopening_one(self) -> None:
        out = _lines(_detail(_reopened_issue()))
        marked = [line for line in out if "reopened this task" in line]

        assert marked == [
            f"  +1 {REOPENING_REPORTER} · {REOPENING_TIMESTAMP}  ↺ reopened this task"
        ]

    def test_a_reporter_match_alone_does_not_mark_an_entry(self) -> None:
        issue = _reopened_issue()
        issue.close_history = [
            CloseRecord(
                closed_at="2026-07-30T09:12:04Z",
                reopened_at="2026-08-05T17:04:12Z",
                reopened_via=ReopenCause.PLUS_ONE,
                reopened_by=REOPENING_REPORTER,
            )
        ]

        assert "reopened this task" not in _detail(issue)


def test_rich_detail_strips_back_to_the_plain_bytes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The module's SGR-additive contract must hold for the new section."""
    issues, target_id = build_reopened_task()

    plain = render(
        target_id,
        issues,
        style="plain",
        color="always",
        wrap="40",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = render(
        target_id,
        issues,
        style="rich",
        color="always",
        wrap="40",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert strip_sgr(rich) == plain
    assert "PREVIOUSLY CLOSED" in plain


def test_show_reopened_task_rich_ansi_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = build_reopened_task()

    out = render(
        target_id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert out == read_golden("show_style_reopened_task.ansi")


class TestDetailJson:
    def test_every_record_field_is_emitted_in_storage_order(self) -> None:
        payload = issue_to_wire_dict(_reopened_issue())

        assert payload["close_history"] == [
            {
                "closed_at": "2026-07-16T11:00:00Z",
                "reopened_at": "2026-07-18T12:00:00Z",
                "reopened_via": "open",
            },
            {
                "closed_at": "2026-07-30T09:12:04Z",
                "close_reason": (
                    "Not reproducible on main; the retry shim already covers this."
                ),
                "resolution": "canceled",
                "reopened_at": REOPENING_TIMESTAMP,
                "reopened_via": "plus_one",
                "reopened_by": REOPENING_REPORTER,
            },
        ]

    def test_the_key_is_unconditional(self) -> None:
        issue = Issue(id="bd-plain", title="Plain Task", issue_type=IssueType.TASK)

        assert issue_to_wire_dict(issue)["close_history"] == []

    def test_the_join_is_derived_for_the_reader(self) -> None:
        payload = issue_to_wire_dict(_reopened_issue())
        evidence = payload["plus_one_evidence"]
        assert isinstance(evidence, list)

        assert [entry["reopened_bead"] for entry in evidence] == [False, True]

    def test_the_envelope_stays_valid_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        issues, target_id = build_reopened_task()

        out = render(
            target_id,
            issues,
            style="rich",
            color="always",
            format_="json",
            monkeypatch=monkeypatch,
            capsys=capsys,
        )

        issue = json.loads(out)["issue"]
        assert len(issue["close_history"]) == 2


class TestRowBadges:
    def test_the_list_row_carries_both_badges(self) -> None:
        out = _render_list_compact([_reopened_issue()], use_color=False)

        assert " [+2] [↺2]" in out

    def test_the_search_row_carries_both_badges(self) -> None:
        match = BeadSearchMatch(issue=_reopened_issue(), matched_fields=["title"])

        out = _render_search_compact([match], "flaky", use_color=False)

        assert " [+2] [↺2]" in out

    def test_the_ready_row_carries_both_badges(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_query_view(monkeypatch, ready=[_reopened_issue()])

        handle_bead_ready(_no_args())

        out = capsys.readouterr().out
        assert f"◇  S {REOPENED_TASK_ID} ·" in out
        assert " [+2] [↺2]" in out

    def test_the_blocked_row_carries_both_badges(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        issue = _reopened_issue()
        issue.dependencies = [
            Dependency(
                issue_id=issue.id,
                depends_on_id="bd-blocker",
                created_at="2026-08-01T00:00:00Z",
            )
        ]
        _install_query_view(monkeypatch, blocked=[issue])

        handle_bead_blocked(_no_args())

        out = capsys.readouterr().out
        assert f"●  S {REOPENED_TASK_ID} ·" in out
        assert " [+2] [↺2]" in out

    def test_a_bead_that_was_never_reopened_keeps_its_row_unchanged(self) -> None:
        issue = Issue(id="bd-plain", title="Plain Task", issue_type=IssueType.TASK)

        assert "↺" not in _render_list_compact([issue], use_color=False)


class TestSearchText:
    def test_archived_reasons_and_resolutions_are_searchable(self) -> None:
        value = _search_field_value(_reopened_issue(), "close_history")

        assert "retry shim already covers this" in value
        assert "canceled" in value
        assert "2026-07-30T09:12:04Z" in value

    def test_the_reopened_has_filter_value_is_accepted(self) -> None:
        assert "reopened" in BEAD_HAS_VALUES


class _StubView:
    def __init__(self, *, ready: list[Issue], blocked: list[Issue]) -> None:
        self._ready = ready
        self._blocked = blocked

    def __enter__(self) -> _StubView:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def ready(self) -> list[Issue]:
        return self._ready

    def blocked(self) -> list[Issue]:
        return self._blocked


def _install_query_view(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ready: list[Issue] | None = None,
    blocked: list[Issue] | None = None,
) -> None:
    view = _StubView(ready=ready or [], blocked=blocked or [])
    monkeypatch.setattr("sase.bead.cli_query.get_read_view", lambda: view)


def _no_args() -> argparse.Namespace:
    """These handlers read no options; the namespace is a positional formality."""

    return argparse.Namespace()
