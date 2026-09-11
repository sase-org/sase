"""Acceptance coverage for two-machine artifact-link event convergence."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_event_publisher import (
    publish_artifact_link_events,
    rows_from_events,
)
from tests.sdd._artifact_link_acceptance_helpers import (
    _alias_event,
    _cluster,
    _description,
    _edge_put,
    _edge_remove,
    _git_status,
    _hot_read_events,
    _link_index_paths,
    _link_only_commit_count,
    _read_event,
    _remote_event_operation_ids,
    _row_count,
    _store,
    _touches_research,
    _unmerged_files,
    _uses,
)
from tests.sdd_store._helpers import clone


def test_two_machine_event_publication_has_no_link_index_conflicts_or_bad_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two stale machine clones converge through immutable event files."""

    cluster = _cluster(tmp_path, monkeypatch)
    machine_a = cluster.machine_a
    machine_b = cluster.machine_b
    tracked_bead = cluster.bead_project.create("Tracked rollout", IssueType.PLAN)
    base_race = _edge_put(
        "11111111111111111111111111111111",
        source="plan:202609/race.md",
        relation="related",
        target="plan:202609/target.md",
        description="base race description",
    )
    machine_a_events = (
        *_hot_read_events("a", range(4)),
        _read_event(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaa0000",
            source="agent:repeat.athena.worker",
            target="plan:202609/hot.md",
        ),
        _edge_put(
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbb0000",
            source="plan:202609/described.md",
            relation="related",
            target="research:202609/source.md",
            description="machine A description",
        ),
        _edge_put(
            "cccccccccccccccccccccccccccc0000",
            source="plan:202609/report-new.md",
            relation="related",
            target="research:202609/source.md",
            description="machine A saw the brand-new report",
        ),
        base_race,
        _alias_event(
            "dddddddddddddddddddddddddddd0000",
            old_ref="plan:202609/renamed_old.md",
            new_ref="plan:202609/renamed_new.md",
        ),
        _edge_put(
            "eeeeeeeeeeeeeeeeeeeeeeeeeeee0000",
            source="plan:202609/mixed.md",
            relation="implements",
            target=f"bead:{tracked_bead.id}",
            description="document event projects to the bead store",
            origin="derived",
        ),
    )
    report_a = publish_artifact_link_events(
        machine_a.store,
        machine_a_events,
        push_after_commit=True,
        mutation_origin="machine",
    )

    assert report_a.publication_error is None
    assert report_a.published == len(machine_a_events)
    assert _git_status(machine_a.plans) == ""
    assert _git_status(machine_a.research) == ""
    assert _unmerged_files(machine_a.plans) == ()
    assert _unmerged_files(machine_a.research) == ()

    machine_b_events = (
        *_hot_read_events("b", range(4, 9)),
        machine_a_events[4],
        _read_event(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaa0001",
            source="agent:repeat.athena.worker",
            target="plan:202609/hot.md",
        ),
        _edge_put(
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbb0001",
            source="plan:202609/described.md",
            relation="related",
            target="research:202609/source.md",
            description="machine B description",
        ),
        _edge_put(
            "cccccccccccccccccccccccccccc0001",
            source="plan:202609/report-new.md",
            relation="related",
            target="research:202609/source.md",
            description="machine B saw the brand-new report",
        ),
        _edge_remove(
            "22222222222222222222222222222222",
            source="plan:202609/race.md",
            relation="related",
            target="plan:202609/target.md",
            observed=("11111111111111111111111111111111",),
        ),
        _edge_put(
            "33333333333333333333333333333333",
            source="plan:202609/race.md",
            relation="related",
            target="plan:202609/target.md",
            description="late add survived a stale remover",
        ),
        _edge_put(
            "44444444444444444444444444444444",
            source="plan:202609/race.md",
            relation="related",
            target="plan:202609/target.md",
            description="concurrent update survived a stale remover",
            observed=("11111111111111111111111111111111",),
        ),
        _read_event(
            "dddddddddddddddddddddddddddd0001",
            source="agent:late.athena.worker",
            target="plan:202609/renamed_old.md",
        ),
    )
    report_b = publish_artifact_link_events(
        machine_b.store,
        machine_b_events,
        push_after_commit=True,
        mutation_origin="machine",
    )

    assert report_b.publication_error is None
    assert report_b.published == len(machine_b_events)
    assert _git_status(machine_b.plans) == ""
    assert _git_status(machine_b.research) == ""
    assert _unmerged_files(machine_b.plans) == ()
    assert _unmerged_files(machine_b.research) == ()
    assert _link_index_paths(machine_a.plans) == ()
    assert _link_index_paths(machine_a.research) == ()
    assert _link_index_paths(machine_b.plans) == ()
    assert _link_index_paths(machine_b.research) == ()

    observed_events = {
        str(event["operation_id"]) for event in (*machine_a_events, *machine_b_events)
    }
    assert _remote_event_operation_ids(cluster.plans_remote) == observed_events
    assert _remote_event_operation_ids(cluster.research_remote) == {
        str(event["operation_id"])
        for event in (*machine_a_events, *machine_b_events)
        if _touches_research(event)
    }

    fresh_plans = tmp_path / "fresh" / "plans"
    fresh_research = tmp_path / "fresh" / "research"
    clone(cluster.plans_remote, fresh_plans)
    clone(cluster.research_remote, fresh_research)
    fresh_store = _store(
        plans=fresh_plans,
        research=fresh_research,
        plans_remote=cluster.plans_remote,
        research_remote=cluster.research_remote,
        beads_dir=cluster.bead_project.beads_dir,
    )
    rows = fresh_store.load_durable_rows()

    assert _uses(rows, "agent:reader-a-0.athena.worker", "read", "plan:202609/hot.md")
    assert _uses(rows, "agent:reader-b-8.athena.worker", "read", "plan:202609/hot.md")
    assert _uses(rows, "agent:repeat.athena.worker", "read", "plan:202609/hot.md") == 2
    assert _row_count(rows, "plan:202609/described.md", "related") == 1
    assert _row_count(rows, "plan:202609/report-new.md", "related") == 1
    assert _description(rows, "plan:202609/race.md", "related") == (
        "concurrent update survived a stale remover"
    )
    assert (
        _uses(
            rows,
            "agent:late.athena.worker",
            "read",
            "plan:202609/renamed_new.md",
        )
        == 1
    )
    assert not any(
        row.get("target_ref") == "plan:202609/renamed_old.md" for row in rows
    )
    assert _row_count(rows, "plan:202609/mixed.md", "implements") == 1
    assert cluster.bead_project.show(tracked_bead.id).links

    all_events = (*machine_a_events, *machine_b_events)
    assert rows_from_events(all_events) == rows_from_events(reversed(all_events))
    assert rows_from_events((*all_events, *all_events)) == rows_from_events(all_events)
    for root in (fresh_plans, fresh_research):
        for path in root.glob("link-events/v1/**/*.json"):
            relative = path.relative_to(root).as_posix()
            validated = require_rust_binding("artifact_link_event_validate_bytes")(
                path.read_bytes(),
                relative,
            )
            assert validated["path"] == relative

    assert _link_only_commit_count(fresh_plans) == 2
    assert _link_only_commit_count(fresh_research) == 2
