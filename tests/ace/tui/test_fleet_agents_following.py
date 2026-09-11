from __future__ import annotations

import copy

from sase.ace.tui.actions.agents._fleet_follow import followed_logical_keys
from sase.ace.tui.models.fleet_agents import followed_batch_family_promotions
from sase.dispatch.follow_store import FollowStoreSnapshot
from tests.ace.tui.fleet_fixture import (
    fleet_follow_snapshot,
    fleet_host_response,
    fleet_installation_id,
    fleet_logical_locator,
    fleet_summary,
)


def test_followed_logical_keys_reads_active_records_only() -> None:
    active = {"schema_version": 1, "project": "sase", "agent_id": "active"}
    pending = {"schema_version": 1, "project": "sase", "agent_id": "pending"}
    snapshot = FollowStoreSnapshot(
        schema_version=1,
        records=(
            {
                "schema_version": 1,
                "state": "active",
                "logical_key": "logical-active",
                "logical_locator": active,
            },
            {
                "schema_version": 1,
                "state": "pending",
                "logical_key": "logical-pending",
                "logical_locator": pending,
            },
        ),
        tombstones=(),
        path="/tmp/follows.json",
    )

    assert followed_logical_keys(snapshot) == ("logical-active",)
    assert followed_logical_keys(None) == ()


def test_followed_batch_family_promotions_promote_explicit_singleton() -> None:
    installation_id = fleet_installation_id("d")
    singleton = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="worker",
        family_id=None,
    )
    family = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="worker",
        family_id="family-1",
    )
    response = fleet_host_response(
        installation_id=installation_id,
        summaries=(
            fleet_summary(
                installation_id=installation_id,
                agent_id="worker",
            ),
        ),
    )

    assert followed_batch_family_promotions(
        fleet_follow_snapshot(singleton),
        response,
    ) == (
        {
            "schema_version": 1,
            "from": singleton,
            "to": family,
        },
    )


def test_followed_batch_family_promotions_skip_ambiguous_families() -> None:
    installation_id = fleet_installation_id("e")
    singleton = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="worker",
        family_id=None,
    )
    first = fleet_summary(installation_id=installation_id, agent_id="worker")
    second = copy.deepcopy(first)
    second["logical_locator"]["family_id"] = "family-2"
    response = fleet_host_response(
        installation_id=installation_id,
        summaries=(first, second),
    )

    assert (
        followed_batch_family_promotions(
            fleet_follow_snapshot(singleton),
            response,
        )
        == ()
    )


def test_followed_batch_family_promotions_skip_family_and_dispatch_records() -> None:
    installation_id = fleet_installation_id("f")
    singleton = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="worker",
        family_id=None,
    )
    family = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="worker",
        family_id="family-1",
    )
    dispatch_record = {
        **fleet_follow_snapshot(singleton).records[0],
        "created_by": "dispatch",
    }
    family_record = fleet_follow_snapshot(family).records[0]
    snapshot = FollowStoreSnapshot(
        schema_version=1,
        records=(dispatch_record, family_record),
        tombstones=(),
        path="/tmp/follows.json",
    )
    response = fleet_host_response(
        installation_id=installation_id,
        summaries=(fleet_summary(installation_id=installation_id, agent_id="worker"),),
    )

    assert followed_batch_family_promotions(snapshot, response) == ()
