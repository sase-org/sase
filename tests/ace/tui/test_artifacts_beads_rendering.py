"""Rows and detail rendering for the Artifacts Beads pane."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
from rich.console import Console

from sase.ace.tui.widgets.artifacts.beads_data import BeadsSnapshot
from sase.ace.tui.widgets.artifacts.beads_data_models import (
    ExternalIssueLink,
    ProjectBead,
)
from sase.ace.tui.widgets.artifacts.beads_detail import (
    bead_body_markdown,
    bead_preview_markdown,
    bead_properties_header,
)
from sase.ace.tui.widgets.artifacts.beads_list import build_bead_options
from sase.ace.tui.widgets.artifacts.beads_rendering import (
    build_beads_status,
    build_empty_bead_detail,
    flag_text,
    task_text,
)
from sase.bead.model import (
    CloseRecord,
    Dependency,
    FlagRecord,
    Issue,
    IssueType,
    ReopenCause,
    Resolution,
    Status,
    TaskPlusOneEvidence,
)
from sase.bead_flag_presentation import flag_due_presentation
from sase.vcs_provider import IssueWire
from tests.ace.tui._artifacts_beads_helpers import snapshot

_PINNED_NOW = datetime(2026, 7, 8, 12, 0, 0)


def _has_property_label(rendered: str, label: str) -> bool:
    """True when *label* is the first column of a property-grid row."""
    return re.search(rf"(?m)^\s*{re.escape(label)}\s", rendered) is not None


def _capture_properties(
    issue: Issue,
    value: BeadsSnapshot,
    *,
    project: str = "alpha",
    project_name: str = "Alpha",
) -> str:
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                issue,
                value,
                project=project,
                project_name=project_name,
            )
        )
    return capture.get()


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


def test_flag_group_rows_status_and_detail_render_due_metadata(tmp_path: Path) -> None:
    flag = Issue(
        "alpha-flag",
        "Remove plugin switch",
        issue_type=IssueType.FLAG,
        flag=FlagRecord(
            key="plugins_enabled",
            remove_by_date="2026-12-01",
            remove_by_release="0.19.0",
        ),
    )
    assert flag.flag is not None
    due = flag_due_presentation(
        flag.flag,
        today=date(2026, 12, 7),
        release="0.19.0",
    )
    value = replace(
        snapshot(tmp_path),
        flags=(ProjectBead("alpha", flag),),
        flag_due={("alpha", flag.id): due},
    )

    options, rows = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics=set(),
    )
    prompts = {option.id: option.prompt.plain for option in options if option.id}
    option_ids = [option.id for option in options]
    status = build_beads_status(value, loading=False, load_error=None).plain
    row = flag_text(flag, due=due).plain
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                flag,
                value,
                project="alpha",
                project_name="Alpha",
            )
        )
    properties = capture.get()
    body = bead_body_markdown(flag)
    preview = bead_preview_markdown(flag, value, project="alpha")

    assert option_ids.index("header:tasks") < option_ids.index("header:flags")
    assert option_ids.index("header:flags") < option_ids.index("header:epics")
    assert prompts["header:flags"].startswith("── Flags (1)")
    assert rows["flag:alpha-flag"].kind == "flag"
    assert "⚑ alpha-flag Remove plugin switch" in row
    assert "⚑ plugins_enabled" in row
    assert "DUE ⧗ +6d" in row
    assert "2 tasks  ·  1 flag (1 due)  ·  1 epic  ·  2 phases" in status
    assert "Flag" in properties
    assert "plugins_enabled" in properties
    assert "Due state" in properties
    assert "DUE ⧗ +6d" in properties
    assert "## Flag" in body
    assert "- Key: `plugins_enabled`" in body
    assert "**Due state:** due (DUE ⧗ +6d)" in preview


def test_flag_detail_omits_due_state_when_unresolved(tmp_path: Path) -> None:
    flag = Issue(
        "alpha-flag",
        "Remove plugin switch",
        issue_type=IssueType.FLAG,
        flag=FlagRecord(
            key="plugins_enabled",
            remove_by_date="2026-12-01",
            remove_by_release="0.19.0",
        ),
    )
    value = replace(
        snapshot(tmp_path),
        flags=(ProjectBead("alpha", flag),),
    )

    properties = _capture_properties(flag, value)

    assert _has_property_label(properties, "Flag")
    assert "plugins_enabled" in properties
    assert _has_property_label(properties, "Removal")
    assert not _has_property_label(properties, "Due state")


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


def test_detail_drops_empty_property_rows_for_a_sparse_task(tmp_path: Path) -> None:
    value = snapshot(tmp_path)
    issue = next(task.issue for task in value.tasks if task.issue.id == "alpha-open")

    properties = _capture_properties(issue, value)

    for label in ("ID", "Type", "Status", "Readiness", "Project", "Created"):
        assert _has_property_label(properties, label)
    for label in (
        "Assignee",
        "Model",
        "Closed",
        "Dependencies",
        "External issue",
        "References",
        "Patch",
        "External bug",
        "Plan reference",
    ):
        assert not _has_property_label(properties, label)
    assert "—" not in properties


def test_detail_keeps_populated_property_rows(tmp_path: Path) -> None:
    value = snapshot(tmp_path)
    issue = replace(
        value.epics[0].issue,
        dependencies=[
            Dependency(
                issue_id="alpha-1",
                depends_on_id="alpha-1.1",
                created_at="2026-07-02T10:00:00Z",
            )
        ],
    )

    properties = _capture_properties(issue, value)

    assert _has_property_label(properties, "Assignee")
    assert "alpha.agent" in properties
    assert _has_property_label(properties, "Owner")
    assert "owner@example.com" in properties
    assert _has_property_label(properties, "Plan reference")
    assert "plan:202608/beads.md" in properties
    assert _has_property_label(properties, "Dependencies")
    assert "alpha-1.1" in properties


def test_detail_keeps_unrecorded_resolution_on_a_closed_bead(tmp_path: Path) -> None:
    value = snapshot(tmp_path)
    issue = replace(
        next(task.issue for task in value.tasks if task.issue.id == "alpha-open"),
        status=Status.CLOSED,
        closed_at="2026-07-08T16:00:00Z",
        resolution=None,
    )

    properties = _capture_properties(issue, value)

    assert _has_property_label(properties, "Resolution")
    assert "(unrecorded)" in properties


def test_external_issue_links_render_in_rows_detail_and_preview(
    tmp_path: Path,
) -> None:
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    link = ExternalIssueLink(
        external_ref="bug:alpha#42",
        project="alpha",
        display_project="Alpha",
        issue_id="42",
        relation="mirrored",
        issue=IssueWire(
            number=42,
            title="Ready for triage",
            state="open",
            body="Remote checklist body.",
            labels=("priority:high",),
            assignees=("octocat",),
            author="reporter",
            updated_at="2026-07-15T10:00:00Z",
            url="https://example.test/issues/42",
            comment_count=3,
        ),
        drift=True,
    )

    row = task_text(
        issue,
        triage=False,
        plan_link=False,
        external_links=(link,),
    ).plain
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                issue,
                value,
                project="alpha",
                project_name="Alpha",
                external_links=(link,),
            )
        )
    body = bead_body_markdown(issue, external_links=(link,))
    preview = bead_preview_markdown(
        issue,
        value,
        project="alpha",
        external_links=(link,),
    )

    assert "○#42" in row
    assert "External issue" in capture.get()
    assert "drift" in capture.get()
    assert "## External Issues" in body
    assert "- Labels: priority:high" in body
    assert "Remote checklist body." in body
    assert "**External issue:** Alpha #42 · open (drift)" in preview


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


def test_task_rows_and_detail_render_post_close_plus_one_badges(
    tmp_path: Path,
) -> None:
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    issue.status = Status.CLOSED
    issue.closed_at = "2026-08-01T14:00:00Z"
    issue.resolution = Resolution.DONE
    issue.plus_one_evidence.append(
        TaskPlusOneEvidence(
            timestamp="2026-08-01T15:00:00Z",
            reporter="agent.beta",
            note="Saw this before the close landed.",
            observed_since="2026-01-01T00:00:00Z",
        )
    )

    row = task_text(issue, triage=False, plan_link=False).plain
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

    assert "[+1 after close]" in row
    assert "[+1 after close]" in capture.get()
    assert "Post-close +1" in capture.get()
    assert "post-close evidence" in body
    assert "**Observed since:** 2026-01-01T00:00:00Z" in body


def test_task_rows_and_detail_render_reopen_badges_and_close_history(
    tmp_path: Path,
) -> None:
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    issue.close_history.append(
        CloseRecord(
            closed_at="2026-07-30T09:12:04Z",
            reopened_at="2026-08-05T17:04:11Z",
            reopened_via=ReopenCause.PLUS_ONE,
            close_reason="Not reproducible on main; the retry shim already covers this.",
            resolution=Resolution.CANCELED,
            reopened_by="claude.probe",
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
    properties = capture.get()
    body = bead_body_markdown(issue)

    assert "[↺1]" in task_row
    assert "Previously closed" in properties
    assert "↺1" in properties
    assert "## Previously Closed" in body
    assert body.index("## Previously Closed") < body.index("## Description")
    assert "↺ Closed 2026-07-30T09:12:04Z · canceled" in body
    assert "Reopened 2026-08-05T17:04:11Z by a +1 from @claude.probe" in body
