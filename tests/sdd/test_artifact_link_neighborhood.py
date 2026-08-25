"""Tests for the shared one-hop artifact-link neighborhood helpers."""

from __future__ import annotations

from sase.sdd.artifact_link_neighborhood import (
    launch_one_hop_neighborhood,
    neighborhood_footer,
    superseded_by_refs,
)


_CANONICAL = "plan:202608/x.md"


def test_neighborhood_footer_prefers_semantic_over_observational() -> None:
    rows = (
        {
            "source_ref": "agent:sase-tj.land",
            "relation": "read",
            "target_ref": _CANONICAL,
        },
        {
            "source_ref": _CANONICAL,
            "relation": "implements",
            "target_ref": "bead:sase-r8",
        },
    )

    footer = neighborhood_footer(_CANONICAL, rows)

    assert footer == "Links: implements bead:sase-r8 · read-by agent:sase-tj.land"


def test_neighborhood_footer_none_when_no_rows() -> None:
    assert neighborhood_footer(_CANONICAL, ()) is None


def test_neighborhood_footer_caps_and_reports_overflow() -> None:
    rows = tuple(
        {
            "source_ref": _CANONICAL,
            "relation": "implements",
            "target_ref": f"bead:sase-r{index}",
        }
        for index in range(7)
    )

    footer = neighborhood_footer(_CANONICAL, rows)

    assert footer is not None
    assert footer.endswith("(+2 more)")
    assert footer.count("implements") == 5


def test_superseded_by_refs_only_matches_target_position() -> None:
    rows = (
        {
            "source_ref": "plan:202608/v2.md",
            "relation": "supersedes",
            "target_ref": _CANONICAL,
        },
        {
            "source_ref": _CANONICAL,
            "relation": "supersedes",
            "target_ref": "plan:202608/v0.md",
        },
    )

    assert superseded_by_refs(_CANONICAL, rows) == ("plan:202608/v2.md",)


def test_launch_neighborhood_filters_observational_and_related() -> None:
    rows = (
        {
            "source_ref": _CANONICAL,
            "relation": "implements",
            "target_ref": "bead:sase-r8",
        },
        {
            "source_ref": "agent:sase-tj.land",
            "relation": "read",
            "target_ref": _CANONICAL,
        },
        {
            "source_ref": _CANONICAL,
            "relation": "related",
            "target_ref": "plan:202608/y.md",
        },
    )

    items = launch_one_hop_neighborhood(_CANONICAL, rows)

    assert items == ("implements bead:sase-r8",)


def test_launch_neighborhood_empty_when_no_semantic_rows() -> None:
    rows = (
        {
            "source_ref": "agent:sase-tj.land",
            "relation": "cites",
            "target_ref": _CANONICAL,
        },
    )

    assert launch_one_hop_neighborhood(_CANONICAL, rows) == ()
