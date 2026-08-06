"""Tests for the shared reopen and close-history presentation vocabulary."""

from __future__ import annotations

import pytest

from sase.bead.model import CloseRecord, Resolution, ReopenCause, TaskPlusOneEvidence
from sase.bead.reopen_presentation import (
    REOPEN_ACCENT,
    REOPEN_CLI_STYLE,
    REOPEN_EVIDENCE_MARKER,
    REOPEN_GLYPH,
    REOPEN_RICH_STYLE,
    REOPEN_SECTION_LABEL,
    close_history_display_order,
    close_history_search_text,
    close_record_label,
    close_record_reopened_label,
    evidence_reopened_bead,
    reopen_badge,
)


def test_reopen_constants_are_distinct_from_plus_one_and_status_accents() -> None:
    assert REOPEN_ACCENT == "#FF8700"
    assert REOPEN_GLYPH == "↺"
    assert REOPEN_SECTION_LABEL == "PREVIOUSLY CLOSED"
    assert REOPEN_EVIDENCE_MARKER == "↺ reopened this task"
    assert REOPEN_RICH_STYLE == f"bold {REOPEN_ACCENT}"
    assert REOPEN_CLI_STYLE == "\x1b[1;38;5;208m"


@pytest.mark.parametrize(
    ("count", "badge"),
    [
        (0, ""),
        (1, "↺1"),
        (2, "↺2"),
    ],
)
def test_reopen_badge_is_empty_only_at_zero(count: int, badge: str) -> None:
    assert reopen_badge(count) == badge


def test_close_record_label_reports_resolution_or_unrecorded() -> None:
    resolved = CloseRecord(
        closed_at="2026-07-30T09:12:04Z",
        reopened_at="2026-08-05T17:04:11Z",
        reopened_via=ReopenCause.PLUS_ONE,
        close_reason="Not reproducible on main.",
        resolution=Resolution.CANCELED,
        reopened_by="claude.probe",
    )
    assert close_record_label(resolved) == "↺ Closed 2026-07-30T09:12:04Z · canceled"

    unresolved = CloseRecord(
        closed_at="2026-07-30T09:12:04Z",
        reopened_at="2026-08-05T17:04:11Z",
        reopened_via=ReopenCause.OPEN,
    )
    assert (
        close_record_label(unresolved) == "↺ Closed 2026-07-30T09:12:04Z · (unrecorded)"
    )


@pytest.mark.parametrize(
    ("record", "label"),
    [
        (
            CloseRecord(
                closed_at="2026-07-30T09:12:04Z",
                reopened_at="2026-08-05T17:04:11Z",
                reopened_via=ReopenCause.PLUS_ONE,
                reopened_by="claude.probe",
            ),
            "Reopened 2026-08-05T17:04:11Z by a +1 from @claude.probe",
        ),
        (
            CloseRecord(
                closed_at="2026-07-30T09:12:04Z",
                reopened_at="2026-08-05T17:04:11Z",
                reopened_via=ReopenCause.PLUS_ONE,
                reopened_by=None,
            ),
            "Reopened 2026-08-05T17:04:11Z by a +1",
        ),
        (
            CloseRecord(
                closed_at="2026-07-30T09:12:04Z",
                reopened_at="2026-08-05T17:04:11Z",
                reopened_via=ReopenCause.OPEN,
            ),
            "Reopened 2026-08-05T17:04:11Z by `sase bead open`",
        ),
        (
            CloseRecord(
                closed_at="2026-07-30T09:12:04Z",
                reopened_at="2026-08-05T17:04:11Z",
                reopened_via=ReopenCause.UPDATE,
            ),
            "Reopened 2026-08-05T17:04:11Z by a status update",
        ),
        (
            CloseRecord(
                closed_at="2026-07-30T09:12:04Z",
                reopened_at="2026-08-05T17:04:11Z",
                reopened_via=ReopenCause.EPIC_PRECLAIM,
            ),
            "Reopened 2026-08-05T17:04:11Z by an epic work preclaim",
        ),
    ],
)
def test_close_record_reopened_label_is_cause_specific(
    record: CloseRecord, label: str
) -> None:
    assert close_record_reopened_label(record) == label


def test_close_history_display_order_is_newest_first_over_storage_order() -> None:
    first = CloseRecord(
        closed_at="2026-07-01T00:00:00Z",
        reopened_at="2026-07-10T00:00:00Z",
        reopened_via=ReopenCause.OPEN,
    )
    second = CloseRecord(
        closed_at="2026-07-20T00:00:00Z",
        reopened_at="2026-07-30T00:00:00Z",
        reopened_via=ReopenCause.UPDATE,
    )
    third = CloseRecord(
        closed_at="2026-08-01T00:00:00Z",
        reopened_at="2026-08-05T00:00:00Z",
        reopened_via=ReopenCause.PLUS_ONE,
        reopened_by="claude.probe",
    )

    assert close_history_display_order([first, second, third]) == (
        third,
        second,
        first,
    )
    assert close_history_display_order([]) == ()


def test_close_history_search_text_flattens_reasons_resolutions_and_timestamps() -> (
    None
):
    history = [
        CloseRecord(
            closed_at="2026-07-01T00:00:00Z",
            reopened_at="2026-07-10T00:00:00Z",
            reopened_via=ReopenCause.OPEN,
            close_reason="Not reproducible on main.",
            resolution=Resolution.CANCELED,
        ),
        CloseRecord(
            closed_at="2026-07-20T00:00:00Z",
            reopened_at="2026-07-30T00:00:00Z",
            reopened_via=ReopenCause.UPDATE,
        ),
    ]

    text = close_history_search_text(history)
    assert "Not reproducible on main." in text
    assert "canceled" in text
    assert "2026-07-01T00:00:00Z" in text
    assert "2026-07-10T00:00:00Z" in text
    assert "2026-07-20T00:00:00Z" in text
    assert "2026-07-30T00:00:00Z" in text


def test_close_history_search_text_is_empty_for_empty_history() -> None:
    assert close_history_search_text([]) == ""


def test_evidence_reopened_bead_joins_on_reporter_and_timestamp() -> None:
    reopening_record = CloseRecord(
        closed_at="2026-07-30T09:12:04Z",
        reopened_at="2026-08-05T17:04:11Z",
        reopened_via=ReopenCause.PLUS_ONE,
        reopened_by="claude.probe",
    )
    matching_evidence = TaskPlusOneEvidence(
        timestamp="2026-08-05T17:04:11Z",
        reporter="claude.probe",
        note="Saw the same flake in CI run 4821 with a clean worktree.",
    )
    assert evidence_reopened_bead(matching_evidence, [reopening_record]) is True


def test_evidence_reopened_bead_rejects_non_matching_reporter() -> None:
    reopening_record = CloseRecord(
        closed_at="2026-07-30T09:12:04Z",
        reopened_at="2026-08-05T17:04:11Z",
        reopened_via=ReopenCause.PLUS_ONE,
        reopened_by="claude.probe",
    )
    other_reporter = TaskPlusOneEvidence(
        timestamp="2026-08-05T17:04:11Z",
        reporter="agent.beta",
        note="Different reporter, same timestamp.",
    )
    assert evidence_reopened_bead(other_reporter, [reopening_record]) is False


def test_evidence_reopened_bead_rejects_non_matching_timestamp() -> None:
    reopening_record = CloseRecord(
        closed_at="2026-07-30T09:12:04Z",
        reopened_at="2026-08-05T17:04:11Z",
        reopened_via=ReopenCause.PLUS_ONE,
        reopened_by="claude.probe",
    )
    other_timestamp = TaskPlusOneEvidence(
        timestamp="2026-08-06T00:00:00Z",
        reporter="claude.probe",
        note="Same reporter, different timestamp.",
    )
    assert evidence_reopened_bead(other_timestamp, [reopening_record]) is False


def test_evidence_reopened_bead_rejects_empty_history() -> None:
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-05T17:04:11Z",
        reporter="claude.probe",
        note="No close history at all.",
    )
    assert evidence_reopened_bead(evidence, []) is False


def test_evidence_reopened_bead_rejects_non_plus_one_cause() -> None:
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-05T17:04:11Z",
        reporter="claude.probe",
        note="A record with matching fields but the wrong cause.",
    )
    non_plus_one_record = CloseRecord(
        closed_at="2026-07-30T09:12:04Z",
        reopened_at="2026-08-05T17:04:11Z",
        reopened_via=ReopenCause.UPDATE,
        reopened_by="claude.probe",
    )
    assert evidence_reopened_bead(evidence, [non_plus_one_record]) is False
