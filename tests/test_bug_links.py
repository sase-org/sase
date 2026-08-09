"""Tests for external bug cross-links to epics and Patches."""

from sase.ace.patch.models import Patch
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bug_links import _normalize_bug_id, find_bug_links


def _patch(name: str, bug: str | None) -> Patch:
    return Patch(
        name=name,
        description="",
        parent=None,
        status="WIP",
        bug=bug,
    )


def _plan(
    issue_id: str,
    bug_id: str,
    *,
    tier: BeadTier = BeadTier.EPIC,
) -> Issue:
    return Issue(
        id=issue_id,
        title=issue_id,
        issue_type=IssueType.PLAN,
        tier=tier,
        changespec_name=f"change_{issue_id}",
        changespec_bug_id=bug_id,
    )


def test_normalize_bug_id_accepts_tags_urls_and_shorthand() -> None:
    values = (
        42,
        "42",
        "#42",
        "owner/repo#42",
        "BUG: 42",
        "https://github.com/acme/widgets/issues/42?view=1",
        "http://b/42",
    )

    assert {_normalize_bug_id(value) for value in values} == {"42"}
    assert _normalize_bug_id(" PROJ-ABC ") == "proj-abc"
    assert _normalize_bug_id(None) == ""


def test_find_bug_links_filters_to_epics_and_matching_patches() -> None:
    matching_epic = _plan("sase-1", "42")
    other_epic = _plan("sase-2", "99")
    non_epic_plan = _plan("sase-3", "42", tier=BeadTier.PLAN)
    phase = Issue(
        id="sase-1.1",
        title="phase",
        issue_type=IssueType.PHASE,
        parent_id="sase-1",
    )
    matching_pr = _patch("sase_feature", "https://github.test/issues/42")
    other_pr = _patch("sase_other", "99")

    links = find_bug_links(
        42,
        [matching_epic, other_epic, non_epic_plan, phase],
        [matching_pr, other_pr],
    )

    assert links.bug_id == "42"
    assert links.epics == (matching_epic,)
    assert links.epic_beads == links.epics
    assert links.patches == (matching_pr,)
    assert links.prs == links.patches


def test_find_bug_links_empty_id_never_matches_blank_fields() -> None:
    links = find_bug_links("  ", [_plan("sase-1", "")], [_patch("x", None)])

    assert links.bug_id == ""
    assert links.epics == ()
    assert links.patches == ()
