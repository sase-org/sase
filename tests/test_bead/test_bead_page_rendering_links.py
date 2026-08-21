from __future__ import annotations

from types import MappingProxyType
from typing import cast

from sase.bead.model import BeadLink, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.rendering import render_bead_page
from tests.test_bead.bead_page_rendering_test_helpers import ReferenceLinks, View


def _linked_pair() -> tuple[View, Issue, Issue]:
    left = Issue(
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
    right = Issue(
        "sase-ct",
        "Right",
        issue_type=IssueType.PLAN,
        status=Status.OPEN,
    )
    return View((left, right)), left, right


def test_bead_page_renders_links_and_second_refresh_does_not_drop_them() -> None:
    view, left, _right = _linked_pair()
    first = render_bead_page(
        cast(BeadProject, view),
        left,
        BeadAssociationIndex(MappingProxyType({})),
        link_resolver=ReferenceLinks(),
    )
    second = render_bead_page(
        cast(BeadProject, view),
        left,
        BeadAssociationIndex(MappingProxyType({})),
        link_resolver=ReferenceLinks(),
    )
    assert first == second
    assert "<!-- sase:links:start -->" in first
    assert "## Links" in first
    assert "related" in first
    assert "bead:sase-ct" in first
    assert "shares the ACE-TUI flake root cause" in first
    assert "https://example.test/beads/sase-ct.md" in first
