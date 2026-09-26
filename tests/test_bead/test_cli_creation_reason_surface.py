"""``sase bead`` surfaces for the immutable bead creation reason."""

from __future__ import annotations

from rich.console import Console

from sase.ace.tui.widgets.artifacts.beads_detail import (
    bead_preview_markdown,
    bead_properties_header,
)
from sase.bead.cli_detail import render_issue_detail
from sase.bead.cli_detail_json import issue_detail_wire_dict, issue_to_wire_dict
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.model import Issue, IssueType, Status


def _issue(creation_reason: str = "") -> Issue:
    return Issue(
        id="sase-1ap.3",
        title="Give created beads a distinct Context treatment",
        issue_type=IssueType.TASK,
        status=Status.OPEN,
        owner="owner@example.com",
        created_at="2026-09-26T15:00:00Z",
        description="Scope and evidence.",
        creation_reason=creation_reason,
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


def test_human_detail_shows_creation_reason_before_description() -> None:
    out = _detail(_issue(creation_reason="A second agent reproduced dropped retries"))

    assert "CREATION REASON" in out
    assert "A second agent reproduced dropped retries" in out
    assert out.index("CREATION REASON") < out.index("DESCRIPTION")


def test_human_detail_omits_creation_reason_for_historical_beads() -> None:
    out = _detail(_issue())

    assert "CREATION REASON" not in out
    assert "DESCRIPTION" in out


def test_json_wire_carries_creation_reason_only_when_present() -> None:
    with_reason = issue_to_wire_dict(
        _issue(creation_reason="A second agent reproduced dropped retries")
    )
    assert with_reason["creation_reason"] == (
        "A second agent reproduced dropped retries"
    )

    historical = issue_to_wire_dict(_issue())
    assert "creation_reason" not in historical


def test_json_envelope_carries_creation_reason() -> None:
    detail = IssueDetail(
        issue=_issue(creation_reason="Filed from triage"),
        ancestors=(),
        phases=(),
        child_epics=(),
        depends_on=(),
        blocks=(),
        plan=None,
    )
    envelope = issue_detail_wire_dict(detail)
    issue_payload = envelope["issue"]
    assert isinstance(issue_payload, dict)
    assert issue_payload["creation_reason"] == "Filed from triage"


def _capture(renderable: object) -> str:
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_beads_detail_pane_shows_creation_reason() -> None:
    issue = _issue(creation_reason="A second agent reproduced dropped retries")

    properties = _capture(
        bead_properties_header(issue, None, project="alpha", project_name="Alpha")
    )
    assert "Creation reason" in properties
    assert "A second agent reproduced dropped retries" in properties

    preview = bead_preview_markdown(issue, None, project="alpha")
    assert "**Creation reason:** A second agent reproduced dropped retries" in preview


def test_beads_detail_pane_omits_empty_creation_reason() -> None:
    issue = _issue()

    properties = _capture(
        bead_properties_header(issue, None, project="alpha", project_name="Alpha")
    )
    assert "Creation reason" not in properties

    preview = bead_preview_markdown(issue, None, project="alpha")
    assert "Creation reason" not in preview
