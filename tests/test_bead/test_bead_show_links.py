from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.cli_detail import render_issue_detail
from sase.bead.cli_detail_json import issue_to_wire_dict, render_issue_detail_json
from sase.bead.cli_detail_links import assemble_bead_link_neighborhood
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_detail_style import DetailStyle
from sase.bead.cli_show_batch import enrich_with_artifact_link_neighborhood
from sase.bead.model import BeadLink, Issue, IssueType, Status


def _detail(issue: Issue, *, include_links: bool = True) -> IssueDetail:
    views = (
        assemble_bead_link_neighborhood(
            bead_id=issue.id,
            fallback_issue=issue,
        )
        if include_links
        else ()
    )
    return IssueDetail(
        issue=issue,
        ancestors=(),
        phases=(),
        child_epics=(),
        depends_on=(),
        blocks=(),
        plan=None,
        artifact_links=views,
        include_links=include_links,
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
    assert "LINKS (1)" in rendered
    assert "↔ related · bead:sase-ct" in rendered
    assert "shares the ACE-TUI flake root cause" in rendered
    assert "manual · added" in rendered


def test_bead_show_json_includes_artifact_links_projection() -> None:
    envelope = json.loads(render_issue_detail_json(_detail(_issue())))
    assert envelope["issue"]["links"][0]["target_ref"] == "bead:sase-ct"
    assert envelope["artifact_links"][0]["direction"] == "symmetric"
    assert envelope["artifact_links"][0]["displayed_relation"] == "related"
    assert envelope["artifact_links"][0]["counterpart_ref"] == "bead:sase-ct"


def test_bead_show_json_omits_link_fields_when_disabled() -> None:
    envelope = json.loads(
        render_issue_detail_json(
            _detail(_issue(), include_links=False),
            include_links=False,
        )
    )
    assert "artifact_links" not in envelope
    assert "links" not in envelope["issue"]


def test_non_exiting_enricher_attaches_the_same_neighborhood() -> None:
    issue = _issue()
    bare = IssueDetail(
        issue=issue,
        ancestors=(),
        phases=(),
        child_epics=(),
        depends_on=(),
        blocks=(),
        plan=None,
        include_links=True,
    )

    assert bare.artifact_links == ()
    assert (
        enrich_with_artifact_link_neighborhood(bare).artifact_links
        == _detail(issue).artifact_links
    )


def test_non_exiting_enricher_degrades_instead_of_exiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pager keypress handler cannot afford `_with_artifact_link_neighborhood`."""

    def boom(**_kwargs: object) -> tuple[()]:
        raise RuntimeError("artifact link store is unreadable")

    monkeypatch.setattr(
        "sase.bead.cli_show_batch_enrich.assemble_bead_link_neighborhood", boom
    )
    detail = _detail(_issue(), include_links=False)

    assert enrich_with_artifact_link_neighborhood(detail) is detail


def test_bead_show_tolerates_unrelated_malformed_projected_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`bead show` links still render with a malformed projected row nearby."""

    from sase.bead import cli_detail_links
    from tests.sdd._artifact_link_store_helpers import _store

    store = _store(tmp_path, monkeypatch)
    malformed = {
        "schema_version": 2,
        "source_ref": "stitch:sase@fedcba9876543210fedcba9876543210fedcba98",
        "relation": "implements",
        "target_ref": "bead:[sase-zz.1]",
        "description": "commit trailer names bead [sase-zz.1]",
        "origin": "projected",
        "created_by": "projection:stitch-bead",
        "created_at": "2026-08-20T00:00:00Z",
        "uses": 1,
    }
    store._write_aggregate({"rows": [malformed]})  # noqa: SLF001
    monkeypatch.setattr(
        cli_detail_links,
        "resolve_artifact_link_store",
        lambda *args, **kwargs: store,
    )

    views = assemble_bead_link_neighborhood(
        bead_id="sase-js",
        fallback_issue=_issue(),
    )

    assert any(view.counterpart_ref == "bead:sase-ct" for view in views)
