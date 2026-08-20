from __future__ import annotations

import json

from sase.bead.cli_detail import render_issue_detail
from sase.bead.cli_detail_json import issue_to_wire_dict, render_issue_detail_json
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_detail_style import DetailStyle
from sase.bead.model import BeadLink, Issue, IssueType, Status


def _detail(issue: Issue) -> IssueDetail:
    return IssueDetail(
        issue=issue,
        ancestors=(),
        phases=(),
        child_epics=(),
        depends_on=(),
        blocks=(),
        plan=None,
    )


def _issue() -> Issue:
    return Issue(
        "sase-js",
        "Left",
        issue_type=IssueType.PLAN,
        status=Status.OPEN,
        links=[
            BeadLink(
                target_ref="bead:sase-ct",
                relation="related",
                description="shares the ACE-TUI flake root cause",
                origin="manual",
            )
        ],
    )


def test_bead_show_json_includes_stable_links_array() -> None:
    issue = _issue()
    payload = issue_to_wire_dict(issue)
    assert payload["links"] == [
        {
            "target_ref": "bead:sase-ct",
            "relation": "related",
            "description": "shares the ACE-TUI flake root cause",
            "origin": "manual",
        }
    ]
    envelope = json.loads(render_issue_detail_json(_detail(issue)))
    assert envelope["issue"]["links"][0]["target_ref"] == "bead:sase-ct"


def test_bead_show_text_includes_links_section() -> None:
    rendered = render_issue_detail(
        _detail(_issue()),
        relativize_design=False,
        style=DetailStyle.PLAIN,
    )
    assert "LINKS" in rendered
    assert "related" in rendered
    assert "bead:sase-ct" in rendered
