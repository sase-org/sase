"""Coverage for ``sase bead list`` summary presentation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from sase.ansi_style import ANSI_RESET, ansi_sgr
from sase.bead.model import IssueType, Status
from sase.bead_status_presentation import (
    BEAD_STATUS_VALUES,
    bead_status_display_order,
    bead_status_presentation,
)
from sase.bead_summary_presentation import (
    BEAD_STATUS_ADJECTIVES,
    BEAD_TYPE_NOUNS,
    bead_list_summary_line,
    summarize_bead_rows,
)
from sase.bead_type_presentation import BEAD_TYPE_VALUES, bead_type_presentation


@dataclass(frozen=True)
class Row:
    issue_type: object
    status: object
    task_type: str = ""
    task_type_fields: dict[str, str] | None = None


def test_summary_counts_all_buckets_and_renders_nonzero_groups() -> None:
    summary = summarize_bead_rows(
        [
            Row(IssueType.PLAN, Status.OPEN),
            Row("phase", "open"),
            Row("task", "ready"),
            Row("plan", "in_progress"),
        ],
        matched=4,
    )

    assert summary.shown == 4
    assert summary.matched == 4
    assert summary.by_type == {"plan": 2, "phase": 1, "task": 1}
    assert summary.by_status == {
        "open": 2,
        "claimed": 0,
        "ready": 1,
        "snoozed": 0,
        "in_progress": 1,
        "closed": 0,
    }
    assert (
        bead_list_summary_line(summary, use_color=False, implicit_limit=False)
        == "4 beads · ▸ 2  ↳ 1  ◆ 1 · ○ 2  ◇ 1  ◐ 1"
    )


def test_summary_counts_due_flags_and_renders_the_urgency_clause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.__version__", "0.19.0")
    monkeypatch.setattr(
        "sase.bead_summary_presentation.core_time.local_now",
        lambda: datetime(2026, 12, 7, 12, 0, 0),
    )
    due_fields = {
        "key": "plugins_enabled",
        "remove_by_date": "2026-12-01",
        "remove_by_release": "0.19.0",
    }
    live_fields = {
        "key": "new_checkout",
        "remove_by_date": "2027-12-01",
        "remove_by_release": "9.99.0",
    }

    summary = summarize_bead_rows(
        [
            Row(IssueType.TASK, Status.OPEN, "flag", due_fields),
            Row(IssueType.TASK, Status.OPEN, "flag", live_fields),
        ],
        matched=2,
    )

    assert summary.due_flags == 1
    assert (
        bead_list_summary_line(summary, use_color=False, implicit_limit=False)
        == "2 open tasks · ⧗ 1 due flag"
    )

    colored = bead_list_summary_line(summary, use_color=True, implicit_limit=False)
    assert "\x1b[1;7m⧗\x1b[0m 1 due flag" in colored


def test_summary_counts_typed_flag_tasks_as_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.model import Issue

    monkeypatch.setattr("sase.__version__", "0.19.0")
    monkeypatch.setattr(
        "sase.bead_summary_presentation.core_time.local_now",
        lambda: datetime(2026, 12, 7, 12, 0, 0),
    )
    due = Issue(
        "sase-due",
        "Due flag",
        issue_type=IssueType.TASK,
        status=Status.OPEN,
        task_type="flag",
        task_type_fields={
            "key": "plugins_enabled",
            "kind": "beta",
            "when_enabled": "new path",
            "when_disabled": "old path",
            "remove_when": "when proven",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.19.0",
        },
    )
    live = Issue(
        "sase-live",
        "Live flag",
        issue_type=IssueType.TASK,
        status=Status.OPEN,
        task_type="flag",
        task_type_fields={
            "key": "new_checkout",
            "kind": "sunset",
            "when_enabled": "new path",
            "when_disabled": "old path",
            "remove_when": "when proven",
            "remove_by_date": "2027-12-01",
            "remove_by_release": "9.99.0",
        },
    )

    summary = summarize_bead_rows([due, live], matched=2)

    assert summary.by_type == {"plan": 0, "phase": 0, "task": 2}
    assert summary.due_flags == 1
    assert (
        bead_list_summary_line(summary, use_color=False, implicit_limit=False)
        == "2 open tasks · ⧗ 1 due flag"
    )


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([Row("plan", "open")], "1 open plan"),
        ([Row("plan", "open"), Row("plan", "closed")], "2 plans · ○ 1  ✓ 1"),
        ([Row("plan", "open"), Row("task", "open")], "2 open beads · ▸ 1  ◆ 1"),
        (
            [Row("plan", "open"), Row("phase", "in_progress")],
            "2 beads · ▸ 1  ↳ 1 · ○ 1  ◐ 1",
        ),
        ([Row("phase", "closed")], "1 closed phase"),
        ([Row("phase", "closed"), Row("phase", "closed")], "2 closed phases"),
    ],
)
def test_summary_fold_branches_and_pluralization(
    rows: list[Row], expected: str
) -> None:
    summary = summarize_bead_rows(rows, matched=len(rows))

    assert (
        bead_list_summary_line(summary, use_color=False, implicit_limit=False)
        == expected
    )


def test_summary_hidden_clause_has_explicit_and_implicit_limit_forms() -> None:
    summary = summarize_bead_rows([Row("plan", "closed")], matched=3)

    assert (
        bead_list_summary_line(summary, use_color=False, implicit_limit=False)
        == "1 closed plan · 2 hidden"
    )
    assert (
        bead_list_summary_line(summary, use_color=False, implicit_limit=True)
        == "1 closed plan · 2 hidden (--limit 0 shows all)"
    )


def test_summary_plain_mode_has_no_escape_sequences() -> None:
    summary = summarize_bead_rows(
        [Row("plan", "open"), Row("phase", "in_progress")],
        matched=5,
    )

    line = bead_list_summary_line(summary, use_color=False, implicit_limit=True)

    assert "\x1b[" not in line


def test_summary_color_mode_styles_group_glyphs_only() -> None:
    summary = summarize_bead_rows(
        [Row("plan", "open"), Row("phase", "in_progress")],
        matched=2,
    )

    line = bead_list_summary_line(summary, use_color=True, implicit_limit=False)

    assert line == (
        "2 beads · "
        f"{bead_type_presentation('plan').cli_style}▸{ANSI_RESET} 1  "
        f"{bead_type_presentation('phase').cli_style}↳{ANSI_RESET} 1 · "
        f"{bead_status_presentation('open').cli_style}○{ANSI_RESET} 1  "
        f"{bead_status_presentation('in_progress').cli_style}◐{ANSI_RESET} 1"
    )


def test_summary_color_mode_styles_folded_words_and_hidden_clause() -> None:
    summary = summarize_bead_rows([Row("plan", "closed")], matched=3)

    line = bead_list_summary_line(summary, use_color=True, implicit_limit=True)

    assert line == (
        "1 "
        f"{bead_status_presentation('closed').cli_style}closed{ANSI_RESET} "
        f"{bead_type_presentation('plan').cli_style}plan{ANSI_RESET} · "
        f"{ansi_sgr(dim=True)}2 hidden (--limit 0 shows all){ANSI_RESET}"
    )


def test_summary_wording_maps_cover_every_type_and_status() -> None:
    assert set(BEAD_TYPE_NOUNS) == set(BEAD_TYPE_VALUES)
    assert set(BEAD_STATUS_ADJECTIVES) == set(BEAD_STATUS_VALUES)
    assert set(BEAD_STATUS_ADJECTIVES) == set(bead_status_display_order())


def test_summary_unknown_type_or_status_raises() -> None:
    with pytest.raises(ValueError, match="unknown bead type"):
        summarize_bead_rows([Row("bug", "open")], matched=1)

    with pytest.raises(ValueError, match="unknown bead status"):
        summarize_bead_rows([Row("plan", "blocked")], matched=1)


def test_summary_zero_shown_renders_without_crashing() -> None:
    summary = summarize_bead_rows([], matched=0)

    assert summary.shown == 0
    assert summary.hidden == 0
    assert bead_list_summary_line(summary, use_color=False, implicit_limit=False) == (
        "0 beads"
    )

    hidden_summary = summarize_bead_rows([], matched=2)
    assert (
        bead_list_summary_line(hidden_summary, use_color=False, implicit_limit=True)
        == "0 beads · 2 hidden (--limit 0 shows all)"
    )
