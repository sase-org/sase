from __future__ import annotations

from sase.ace.tui.models.fleet_agents import (
    followed_logical_locators,
    project_fleet_agents,
)
from sase.dispatch.follow_store import FollowStoreSnapshot


def test_project_fleet_agents_marks_followed_and_preserves_machine_sections() -> None:
    logical_a = {"schema_version": 1, "project": "sase", "agent_id": "agent-a"}
    logical_b = {"schema_version": 1, "project": "sase", "agent_id": "agent-b"}
    follow_snapshot = FollowStoreSnapshot(
        schema_version=1,
        records=(
            {
                "schema_version": 1,
                "state": "active",
                "logical_key": "logical-a",
                "logical_locator": logical_a,
            },
        ),
        tombstones=(),
        path="/tmp/follows.json",
    )
    response = {
        "schema_version": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": "apollo",
                "origin": {"installation_id": "sase_inst_v1_" + "a" * 64},
                "freshness": "fresh",
                "connection_health": "online",
                "observed_at_unix": 1_800_000_000,
                "summaries": [
                    {
                        "schema_version": 1,
                        "logical_locator": logical_a,
                        "exact_locator": {"run_id": "run-a", "logical": logical_a},
                        "logical_key": "logical-a",
                        "exact_key": "exact-a",
                        "status": "running",
                        "revision": 4,
                        "content": {
                            "agent_name": "same.name",
                            "patch_name": "fleet-ui",
                            "model": "gpt-5",
                            "bounded_intent": "hydrate",
                        },
                    },
                    {
                        "schema_version": 1,
                        "logical_locator": logical_b,
                        "exact_locator": {"run_id": "run-b", "logical": logical_b},
                        "logical_key": "logical-b",
                        "exact_key": "exact-b",
                        "status": "done",
                        "content": {
                            "agent_name": "same.name",
                            "patch_name": "fleet-ui",
                        },
                    },
                ],
            }
        ],
    }

    projection = project_fleet_agents(
        catalog_response=response,
        followed_response=response,
        follow_snapshot=follow_snapshot,
        local_agent_count=3,
    )

    assert len(projection.fleet_rows) == 2
    assert len(projection.focus_rows) == 1
    assert projection.counts["local"] == 3
    assert projection.counts["focus_total"] == 4
    assert projection.counts["fleet"] == 2
    followed = projection.focus_rows[0]
    assert followed.fleet_origin_alias == "apollo"
    assert followed.project_display_name == "apollo"
    assert followed.fleet_followed is True
    assert followed.fleet_revision == 4
    assert followed.fleet_bounded_intent == "hydrate"
    assert {row.identity for row in projection.fleet_rows} == {
        row.identity for row in projection.fleet_rows
    }
    assert projection.fleet_rows[0].identity != projection.fleet_rows[1].identity


def test_followed_logical_locators_reads_active_records_only() -> None:
    active = {"schema_version": 1, "project": "sase", "agent_id": "active"}
    pending = {"schema_version": 1, "project": "sase", "agent_id": "pending"}
    snapshot = FollowStoreSnapshot(
        schema_version=1,
        records=(
            {
                "schema_version": 1,
                "state": "active",
                "logical_key": "active",
                "logical_locator": active,
            },
            {
                "schema_version": 1,
                "state": "pending",
                "logical_key": "pending",
                "logical_locator": pending,
            },
        ),
        tombstones=(),
        path="/tmp/follows.json",
    )

    assert followed_logical_locators(snapshot) == (active,)
