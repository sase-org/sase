"""Row ordering, chips, and age labels for the Artifacts Beads pane."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.artifacts.beads_list import build_bead_options
from sase.ace.tui.widgets.artifacts.beads_rendering import task_text
from sase.bead.model import Issue, IssueType
from tests.ace.tui._artifacts_beads_helpers import pinned_clock, snapshot

__all__ = [
    "pinned_clock",
    "test_rows_label_created_and_updated_ages_separately",
    "test_rows_show_triage_plan_status_and_project_chips",
    "test_rows_suppress_the_updated_cell_for_a_never_updated_bead",
    "test_tasks_precede_epics_and_every_bead_has_one_row",
]


def test_tasks_precede_epics_and_every_bead_has_one_row(tmp_path: Path) -> None:
    value = snapshot(tmp_path)
    collapsed, collapsed_rows = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics=set(),
    )
    option_ids = [option.id for option in collapsed]

    assert option_ids.index("header:tasks") < option_ids.index("header:epics")
    tasks_header = next(option for option in collapsed if option.id == "header:tasks")
    assert tasks_header.prompt.plain == "── Tasks (2) · ✦ 1 awaiting triage ────────"
    assert tuple(collapsed_rows) == (
        "task:alpha-ready",
        "task:alpha-open",
        "epic:alpha-1",
    )

    _expanded, expanded_rows = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics={("alpha", "alpha-1")},
    )
    identities = [row.issue.id for row in expanded_rows.values()]
    assert identities == [
        "alpha-ready",
        "alpha-open",
        "alpha-1",
        "alpha-1.1",
        "alpha-1.2",
    ]
    assert len(identities) == len(set(identities))


def test_rows_show_triage_plan_status_and_project_chips(tmp_path: Path) -> None:
    value = snapshot(tmp_path, project=None)
    options, _rows = build_bead_options(
        value,
        project_scope=None,
        loading=False,
        expanded_epics={("alpha", "alpha-1")},
    )
    prompts = {option.id: option.prompt.plain for option in options if option.id}

    assert "✦" in prompts["task:alpha:alpha-ready"]
    assert "ready" in prompts["task:alpha:alpha-ready"]
    assert "▤" in prompts["epic:alpha:alpha-1"]
    assert "[Alpha]" in prompts["epic:alpha:alpha-1"]
    assert prompts["phase:alpha:alpha-1.1"].startswith("  ↳")


def test_rows_label_created_and_updated_ages_separately(
    tmp_path: Path,
    pinned_clock: None,
) -> None:
    value = snapshot(tmp_path)
    options, _rows = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics={("alpha", "alpha-1")},
    )
    prompts = {option.id: option.prompt.plain for option in options if option.id}

    # created 2026-07-03, last updated 2026-07-06, "now" 2026-07-08.
    assert "⧖ 5d" in prompts["task:alpha-ready"]
    assert "✎ 2d" in prompts["task:alpha-ready"]
    assert "⧖ 7d" in prompts["epic:alpha-1"]
    assert "✎ 2d" in prompts["epic:alpha-1"]


def test_rows_suppress_the_updated_cell_for_a_never_updated_bead(
    pinned_clock: None,
) -> None:
    for updated_at in ("2026-07-08T16:00:00Z", ""):
        issue = Issue(
            id="alpha-fresh",
            title="Filed moments ago",
            issue_type=IssueType.TASK,
            created_at="2026-07-08T16:00:00Z",
            updated_at=updated_at,
        )

        row = task_text(issue, triage=False, plan_link=False).plain

        assert "⧖ now" in row
        assert "✎" not in row
