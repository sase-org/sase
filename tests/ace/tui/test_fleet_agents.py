from __future__ import annotations

import copy

from sase.ace.tui.models.fleet_agents import (
    catalog_next_cursor,
    followed_batch_family_promotions,
    followed_logical_keys,
    merge_catalog_pages,
    project_fleet_agents,
)
from sase.dispatch.follow_store import FollowStoreSnapshot
from tests.ace.tui.fleet_fixture import (
    fleet_attention_response,
    fleet_follow_snapshot,
    fleet_host_response,
    fleet_installation_id,
    fleet_logical_locator,
    fleet_summary,
)


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


def test_project_fleet_agents_maps_pending_attention_onto_local_statuses() -> None:
    logical_a = {"schema_version": 1, "project": "sase", "agent_id": "agent-a"}
    logical_b = {"schema_version": 1, "project": "sase", "agent_id": "agent-b"}
    response = {
        "schema_version": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": "apollo",
                "summaries": [
                    {
                        "schema_version": 1,
                        "logical_locator": logical_a,
                        "logical_key": "logical-a",
                        "exact_key": "exact-a",
                        "status": "running",
                    },
                    {
                        "schema_version": 1,
                        "logical_locator": logical_b,
                        "logical_key": "logical-b",
                        "exact_key": "exact-b",
                        "status": "asking",
                    },
                ],
            }
        ],
    }
    attention_response = {
        "schema_version": 1,
        "hosts": [
            {
                "alias": "apollo",
                "payload": {
                    "entries": [
                        {
                            "kind": "question",
                            "state": "pending",
                            "logical_key": "logical-a",
                        },
                        {
                            "kind": "gate",
                            "state": "settled",
                            "logical_key": "logical-b",
                        },
                    ],
                },
            }
        ],
    }

    projection = project_fleet_agents(
        catalog_response=response,
        attention_response=attention_response,
    )

    by_key = {row.fleet_logical_key: row for row in projection.fleet_rows}
    assert by_key["logical-a"].status == "QUESTION"
    assert by_key["logical-a"].fleet_attention == {
        "kind": "question",
        "state": "pending",
        "logical_key": "logical-a",
    }
    # A settled attention entry never overrides status; the row's own
    # lifecycle ("asking") is the fallback signal instead.
    assert by_key["logical-b"].status == "WAITING INPUT"
    assert by_key["logical-b"].fleet_attention is not None


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


def test_offline_fleet_fixture_projects_rows_counts_and_diagnostics() -> None:
    installation_id = fleet_installation_id("c")
    logical = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="fixture-agent",
    )
    summary = fleet_summary(
        installation_id=installation_id,
        agent_id="fixture-agent",
        needs_attention=True,
        bounded_intent="reuse from visual and perf tests",
    )
    response = fleet_host_response(
        alias="apollo",
        installation_id=installation_id,
        summaries=(summary,),
        diagnostics=(
            {
                "code": "fixture_warning",
                "severity": "warning",
                "message": "offline fixture diagnostic",
            },
        ),
        partial=True,
    )
    attention = fleet_attention_response(
        (
            {
                "kind": "question",
                "state": "pending",
                "logical_key": summary["logical_key"],
            },
        ),
        alias="apollo",
    )

    projection = project_fleet_agents(
        summary_response=response,
        catalog_response=response,
        followed_response=response,
        attention_response=attention,
        follow_snapshot=fleet_follow_snapshot(logical),
        local_agent_count=2,
    )

    assert len(projection.fleet_rows) == 1
    assert len(projection.focus_rows) == 1
    assert projection.configured_host_count == 1
    assert projection.partial is True
    assert projection.counts["local"] == 2
    assert projection.counts["focus_total"] == 3
    assert projection.counts["fleet"] == 1
    assert projection.diagnostics == (
        {
            "code": "fixture_warning",
            "severity": "warning",
            "message": "offline fixture diagnostic",
        },
        {
            "code": "fixture_warning",
            "severity": "warning",
            "message": "offline fixture diagnostic",
        },
        {
            "code": "fixture_warning",
            "severity": "warning",
            "message": "offline fixture diagnostic",
        },
    )
    row = projection.focus_rows[0]
    assert row.fleet_origin_alias == "apollo"
    assert row.fleet_followed is True
    assert row.status == "QUESTION"
    assert row.fleet_bounded_intent == "reuse from visual and perf tests"


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


def _worker_summary(
    *,
    installation_id: str,
    agent_id: str,
    agent_label: str,
    status: str = "running",
    lifecycle: str = "running",
    revision: int = 3,
) -> dict[str, object]:
    logical = fleet_logical_locator(installation_id=installation_id, agent_id=agent_id)
    logical_key = f"{installation_id}:{agent_id}"
    return {
        "schema_version": 1,
        "logical_locator": logical,
        "exact_locator": {
            "schema_version": 1,
            "logical": logical,
            "shell_id": f"shell-{agent_id}",
            "run_id": f"run-{agent_id}",
            "attempt_id": "attempt-1",
        },
        "logical_key": logical_key,
        "exact_key": f"{logical_key}:run-{agent_id}",
        "row_kind": "agent_shell",
        "labels": {
            "schema_version": 1,
            "project_label": "sase",
            "agent_label": agent_label,
            "family_label": None,
            "owner_label": "bryan",
            "alias": None,
        },
        "project_name": "sase",
        "model": "grok-4",
        "provider": "xai",
        "status": status,
        "status_bucket": "running" if status == "running" else "done",
        "intent": "observe apollo",
        "observed_at_unix": 1_800_000_000.0,
        "row_revision": {
            "schema_version": 1,
            "logical_key": logical_key,
            "revision": revision,
        },
        "lifecycle": lifecycle,
        "liveness": "alive" if status == "running" else "dead",
        "connection_health": "online",
        "freshness": "fresh",
        "capabilities": {
            "schema_version": 1,
            "resource": ["content.read", "stop"],
            "host": [],
            "protocol": ["fleet.v1"],
        },
        "content": {
            "schema_version": 1,
            "handle_count": 1,
            "total_byte_len": 24,
            "kinds": ["output"],
            "supports_range": True,
            "supports_growth": True,
        },
        "current_instance": status == "running",
        "dismissable": False,
        "needs_attention": False,
        "occupied_runner_slot": False,
        "container_projected_concrete_agent": False,
    }


def _worker_catalog_response(
    *summaries: dict[str, object],
    running: int = 1,
    next_cursor: str | None = None,
    status: str = "ok",
    error: dict[str, object] | None = None,
) -> dict[str, object]:
    installation_id = fleet_installation_id("w")
    return {
        "schema_version": 1,
        "operation": "catalog",
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": "apollo",
                "provider_ref": "builtin@https",
                "installation_id": installation_id,
                "endpoint": "https://apollo.example.test",
                "status": status,
                "cached": False,
                "age_seconds": 0.2,
                "payload": None
                if error is not None
                else {
                    "schema_version": 1,
                    "counts": {
                        "schema_version": 1,
                        "running": running,
                        "waiting": 0,
                        "attention": 0,
                        "occupied_runner_slots": 0,
                        "logical_agent_total": len(summaries),
                    },
                    "freshness": {
                        "schema_version": 1,
                        "freshness": "fresh",
                        "partial": False,
                        "refreshed_at_unix": 1_800_000_000.0,
                        "error": None,
                    },
                    "page": {
                        "schema_version": 1,
                        "rows": list(summaries),
                        "limit": 100,
                        "total_matching_rows": len(summaries),
                        "next_cursor": next_cursor,
                        "has_more": next_cursor is not None,
                    },
                },
                "error": error,
            }
        ],
    }


def test_project_fleet_agents_reads_worker_catalog_page_rows() -> None:
    installation_id = fleet_installation_id("w")
    running = _worker_summary(
        installation_id=installation_id,
        agent_id="live",
        agent_label="apollo-live",
    )
    done = _worker_summary(
        installation_id=installation_id,
        agent_id="done",
        agent_label="apollo-done",
        status="done",
        lifecycle="terminal",
        revision=9,
    )
    response = _worker_catalog_response(running, done, running=1)

    projection = project_fleet_agents(catalog_response=response, local_agent_count=2)

    assert [row.agent_name for row in projection.fleet_rows] == [
        "apollo-live",
        "apollo-done",
    ]
    assert projection.fleet_rows[0].llm_provider == "xai"
    assert projection.fleet_rows[0].fleet_bounded_intent == "observe apollo"
    assert projection.fleet_rows[0].fleet_origin_installation_id == installation_id
    assert projection.fleet_rows[0].status == "RUNNING"
    assert projection.fleet_rows[1].status == "DONE"
    assert projection.counts["fleet"] == 1
    assert projection.partial is False
    assert projection.diagnostics == ()


def test_project_fleet_agents_reads_followed_batch_entry_summaries() -> None:
    installation_id = fleet_installation_id("w")
    summary = _worker_summary(
        installation_id=installation_id,
        agent_id="live",
        agent_label="apollo-live",
    )
    logical_key = str(summary["logical_key"])
    followed = {
        "schema_version": 1,
        "operation": "followed_batch",
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": "apollo",
                "installation_id": installation_id,
                "status": "ok",
                "payload": {
                    "schema_version": 1,
                    "counts": {"running": 1},
                    "entries": [
                        {
                            "schema_version": 1,
                            "requested_logical_key": logical_key,
                            "summary": summary,
                        }
                    ],
                },
            }
        ],
    }
    snapshot = FollowStoreSnapshot(
        schema_version=1,
        records=(
            {
                "schema_version": 1,
                "state": "active",
                "logical_key": logical_key,
                "logical_locator": summary["logical_locator"],
            },
        ),
        tombstones=(),
        path="/tmp/follows.json",
    )

    projection = project_fleet_agents(
        followed_response=followed,
        follow_snapshot=snapshot,
        local_agent_count=0,
    )

    assert len(projection.focus_rows) == 1
    assert projection.focus_rows[0].agent_name == "apollo-live"
    assert projection.focus_rows[0].fleet_followed is True
    assert projection.counts["focus_remote"] == 1


def test_project_fleet_agents_surfaces_host_errors_instead_of_empty_success() -> None:
    response = _worker_catalog_response(
        status="invalid",
        error={
            "code": "invalid_request",
            "message": "fleet catalog limit exceeds 100",
        },
        running=0,
    )

    projection = project_fleet_agents(catalog_response=response)

    assert projection.fleet_rows == ()
    assert projection.partial is True
    assert projection.diagnostics[0]["code"] == "invalid_request"
    assert "limit exceeds 100" in str(projection.diagnostics[0]["message"])


def test_merge_catalog_pages_keeps_authoritative_counts_and_second_page_rows() -> None:
    installation_id = fleet_installation_id("w")
    first_row = _worker_summary(
        installation_id=installation_id,
        agent_id="page-one",
        agent_label="page-one",
    )
    second_row = _worker_summary(
        installation_id=installation_id,
        agent_id="page-two",
        agent_label="page-two",
        status="done",
        lifecycle="terminal",
    )
    first = _worker_catalog_response(first_row, running=1, next_cursor="off:100")
    second = _worker_catalog_response(second_row, running=1, next_cursor=None)

    merged = merge_catalog_pages(first, second)
    projection = project_fleet_agents(catalog_response=merged)

    assert [row.agent_name for row in projection.fleet_rows] == ["page-one", "page-two"]
    assert projection.counts["fleet"] == 1
    assert catalog_next_cursor(first) == "off:100"
    assert catalog_next_cursor(second) is None
