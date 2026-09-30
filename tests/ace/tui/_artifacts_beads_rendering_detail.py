"""Property grid and body rendering for the Artifacts Beads pane."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

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
from sase.ace.tui.widgets.artifacts.beads_rendering import (
    build_empty_bead_detail,
    task_text,
)
from sase.bead.model import Dependency, Issue, IssueType, Status
from sase.vcs_provider import IssueWire
from tests.ace.tui._artifacts_beads_helpers import pinned_clock, snapshot

__all__ = [
    "pinned_clock",
    "test_detail_and_preview_share_the_full_creation_label",
    "test_detail_drops_empty_property_rows_for_a_sparse_task",
    "test_detail_keeps_populated_property_rows",
    "test_detail_keeps_unrecorded_resolution_on_a_closed_bead",
    "test_detail_uses_shared_metadata_and_triage_callout",
    "test_external_issue_links_render_in_rows_detail_and_preview",
    "test_first_run_empty_detail_points_to_create_and_triage",
    "test_flag_detail_omits_due_state_when_unresolved",
]


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


def test_flag_detail_omits_due_state_when_unresolved(tmp_path: Path) -> None:
    flag = Issue(
        "alpha-flag",
        "Remove plugin switch",
        issue_type=IssueType.TASK,
        task_type="flag",
        task_type_fields={
            "key": "plugins_enabled",
            "kind": "beta",
            "when_enabled": "on",
            "when_disabled": "off",
            "remove_when": "done",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.19.0",
        },
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

    for label in ("ID", "Type", "Status", "Project", "Created"):
        assert _has_property_label(properties, label)
    for label in (
        "Assignee",
        "Model",
        "Closed",
        "Dependencies",
        "External issue",
        "Readiness",
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


def test_detail_keeps_unrecorded_resolution_on_a_closed_bead(
    tmp_path: Path,
) -> None:
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


def test_first_run_empty_detail_points_to_create_and_triage(
    tmp_path: Path,
) -> None:
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
