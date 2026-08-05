"""Rows and detail rendering for the Artifacts Beads pane."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from rich.console import Console

from sase.ace.tui.widgets.artifacts.beads_detail import (
    bead_body_markdown,
    bead_preview_markdown,
    bead_properties_header,
)
from sase.ace.tui.widgets.artifacts.beads_list import build_bead_options
from sase.ace.tui.widgets.artifacts.beads_rendering import (
    build_empty_bead_detail,
    task_text,
)
from sase.bead.model import Issue, IssueType, TaskPlusOneEvidence
from tests.ace.tui._artifacts_beads_helpers import snapshot

_PINNED_NOW = datetime(2026, 7, 8, 12, 0, 0)


@pytest.fixture
def pinned_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze "now" so the shared bead age labels are deterministic."""
    monkeypatch.setattr("sase.core.time.local_now", lambda: _PINNED_NOW)


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


def test_detail_uses_shared_metadata_and_triage_callout(tmp_path: Path) -> None:
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    gate = value.triage_gates[("alpha", issue.id)]
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                issue,
                value,
                project="alpha",
                project_name="Alpha",
            )
        )
    properties = capture.get()
    body = bead_body_markdown(issue, gate)

    assert "ID" in properties
    assert issue.id in properties
    assert "Type" in properties
    assert "Status" in properties
    assert body.startswith(f"> [!IMPORTANT] {issue.id} is awaiting task triage.")
    assert body.index("## Description") < len(body)


def test_detail_and_preview_share_the_full_creation_label(
    tmp_path: Path,
    pinned_clock: None,
) -> None:
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                issue,
                value,
                project="alpha",
                project_name="Alpha",
            )
        )
    properties = capture.get()
    markdown = bead_preview_markdown(issue, value, project="alpha")

    assert "2026-07-03 05:00:00 EDT · 5d ago" in properties
    assert "- Created: 2026-07-03 05:00:00 EDT · 5d ago" in markdown


def test_first_run_empty_detail_points_to_create_and_triage(tmp_path: Path) -> None:
    value = replace(snapshot(tmp_path), tasks=(), epics=(), phases_by_epic={})

    detail = build_empty_bead_detail(
        value,
        project_scope="alpha",
        loading=False,
        load_error=None,
    )

    assert detail.startswith("# No beads yet")
    assert "/sase_new_task" in detail
    assert "sized draft task" in detail
    assert "TaskTriage" in detail


def test_task_rows_and_detail_render_plus_one_badges_and_evidence(
    tmp_path: Path,
) -> None:
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    issue.plus_one_evidence.append(
        TaskPlusOneEvidence(
            timestamp="2026-08-01T15:00:00Z",
            reporter="agent.beta",
            note="Reproduced after clearing the cache.",
            refs=("research:202608/cache.md",),
        )
    )

    options, _rows = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics=set(),
    )
    task_row = next(
        option.prompt.plain for option in options if option.id == "task:alpha-ready"
    )
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                issue,
                value,
                project="alpha",
                project_name="Alpha",
            )
        )
    body = bead_body_markdown(issue)

    assert "[+1]" in task_row
    assert "[+1]" in capture.get()
    assert "+1 reports" in capture.get()
    assert "## +1 Evidence" in body
    assert "+1 agent.beta · 2026-08-01T15:00:00Z" in body
    assert "research:202608/cache.md" in body
