"""Coverage for the in-memory plans filter index built from a plans snapshot."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from sase.ace.tui.widgets.artifacts.plans_filtering import build_plan_filter_index
from sase.plan_search.filter_query import PlanFilterValues, to_query_string
from tests._plan_filter_query_helpers import matched_plan_option_ids, plans_snapshot


def test_build_index_covers_every_row_with_stable_option_ids() -> None:
    snapshot = plans_snapshot()
    index = build_plan_filter_index(snapshot)

    assert index.source_key == snapshot.source_key
    assert len(index) == 3
    assert tuple(record.kind for record in index) == (
        "proposal",
        "active",
        "archive",
    )
    assert set(index.by_option_id) == {
        "proposal:sase:proposal-1",
        "active:sase:/plans/202607/active.md",
        "archive:sase:/plans/202607/archive.md",
    }


def test_build_index_prefolds_search_fields_and_project_aliases() -> None:
    index = build_plan_filter_index(plans_snapshot())

    proposal = index.by_option_id["proposal:sase:proposal-1"]
    assert proposal.status_labels == frozenset(("proposed",))
    assert proposal.tier_labels == frozenset(("epic",))
    assert proposal.project_labels == frozenset(
        ("sase", "structured agentic software engineering")
    )
    assert "make plan filtering instant" in proposal.haystack
    assert proposal.option_id in matched_plan_option_ids(
        plans_snapshot(),
        to_query_string(
            PlanFilterValues(projects=("Structured Agentic Software Engineering",))
        ),
    )


def test_build_index_uses_plan_frontmatter_not_bead_workflow_state() -> None:
    index = build_plan_filter_index(plans_snapshot())

    active = index.by_option_id["active:sase:/plans/202607/active.md"]
    assert active.status_labels == frozenset(("wip",))
    assert active.tier_labels == frozenset(("epic",))
    assert active.kind_labels == frozenset(("active", "plans"))
    assert "in_progress" not in active.status_labels


def test_build_index_normalizes_timestamps_and_excludes_invalid_values() -> None:
    index = build_plan_filter_index(plans_snapshot())

    proposal = index.by_option_id["proposal:sase:proposal-1"]
    active = index.by_option_id["active:sase:/plans/202607/active.md"]
    assert proposal.timestamp == int(
        datetime.fromisoformat("2026-07-01T12:00:00+00:00").timestamp()
    )
    assert active.timestamp == int(
        datetime.fromisoformat("2026-07-02T09:00:00+00:00").timestamp()
    )


def test_archive_index_includes_status_tier_and_full_body() -> None:
    archive = build_plan_filter_index(plans_snapshot()).by_option_id[
        "archive:sase:/plans/202607/archive.md"
    ]

    assert archive.status_labels == frozenset(("done", "approved"))
    assert archive.tier_labels == frozenset(("tale", "epic"))
    assert "# rollout\n\nthe filter bar is live." in archive.haystack
    assert archive.option_id in matched_plan_option_ids(
        plans_snapshot(),
        to_query_string(
            PlanFilterValues(
                kinds=("archive",),
                statuses=("APPROVED",),
                tiers=("TALE",),
                text=("filter bar",),
            )
        ),
    )


def test_single_project_option_ids_match_the_existing_row_contract() -> None:
    snapshot = replace(plans_snapshot(), project="sase")
    index = build_plan_filter_index(snapshot)

    assert "active:/plans/202607/active.md" in index.by_option_id
    assert "active:sase:/plans/202607/active.md" not in index.by_option_id
