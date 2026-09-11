from __future__ import annotations

from sase.ace.tui.models.fleet_agents import (
    catalog_next_cursor,
    catalog_next_cursors_by_host,
    merge_catalog_pages,
    project_fleet_agents,
)
from sase.dispatch.follow_store import FollowStoreSnapshot
from tests.ace.tui.fleet_fixture import (
    fleet_counts,
    fleet_host_response,
    fleet_installation_id,
    fleet_summary,
)


def _worker_summary(
    *,
    installation_id: str,
    agent_id: str,
    agent_label: str,
    status: str = "running",
    lifecycle: str = "running",
    revision: int = 3,
) -> dict[str, object]:
    del lifecycle
    return fleet_summary(
        installation_id=installation_id,
        project_id="sase",
        project_name="sase",
        agent_id=agent_id,
        run_id=f"run-{agent_id}",
        agent_name=agent_label,
        status=status,
        revision=revision,
        model="grok-4",
        provider="xai",
        bounded_intent="observe apollo",
        occupied_runner_slot=False,
    )


def _worker_catalog_response(
    *summaries: dict[str, object],
    running: int = 1,
    next_cursor: str | None = None,
    status: str = "ok",
    error: dict[str, object] | None = None,
) -> dict[str, object]:
    installation_id = fleet_installation_id("a")
    counts = fleet_counts(summaries, running=running, observed_at_unix=1_800_000_000.0)
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
                    "counts": counts,
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
    installation_id = fleet_installation_id("a")
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
    installation_id = fleet_installation_id("a")
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
                    "counts": fleet_counts((summary,), running=1),
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
    installation_id = fleet_installation_id("a")
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


def test_catalog_next_cursors_by_host_keeps_continuations_separate() -> None:
    first_installation = fleet_installation_id("a")
    second_installation = fleet_installation_id("b")
    third_installation = fleet_installation_id("c")
    first = fleet_host_response(alias="apollo", installation_id=first_installation)
    first["hosts"][0]["payload"]["page"]["total_matching_rows"] = 250
    first["hosts"][0]["payload"]["page"]["next_cursor"] = "off:100"
    first["hosts"][0]["payload"]["page"]["has_more"] = True
    second = fleet_host_response(alias="zeus", installation_id=second_installation)
    third = fleet_host_response(alias="hera", installation_id=third_installation)
    third["hosts"][0]["payload"]["page"]["total_matching_rows"] = 400
    third["hosts"][0]["payload"]["page"]["next_cursor"] = "off:300"
    third["hosts"][0]["payload"]["page"]["has_more"] = True
    response = {
        "schema_version": 1,
        "operation": "catalog",
        "configured_hosts": 3,
        "hosts": [
            first["hosts"][0],
            second["hosts"][0],
            third["hosts"][0],
        ],
    }

    assert catalog_next_cursors_by_host(response) == {
        first_installation: "off:100",
        third_installation: "off:300",
    }


def _normalized_host(
    *,
    alias: str,
    generation: str,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "alias": alias,
        "status": "ok",
        "cached": False,
        "age_seconds": None,
        "summaries": rows,
        "catalog": {
            "schema_version": 1,
            "snapshot_cursor": {
                "schema_version": 1,
                "store_generation": generation,
                "sequence": 1,
            },
            "limit": 100,
            "total_matching_rows": len(rows),
            "next_cursor": None,
            "has_more": False,
            "state": "finished",
        },
    }


def _normalized_response(*hosts: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": "catalog",
        "configured_host_count": len(hosts),
        "hosts": list(hosts),
        "count_hosts": [],
    }


def test_merge_catalog_pages_drops_rows_absent_from_a_newer_snapshot_generation() -> (
    None
):
    """A page from an older owner snapshot build never resurrects vanished rows."""
    vanished: dict[str, object] = {"logical_key": "vanished", "exact_key": "vanished-1"}
    kept: dict[str, object] = {"logical_key": "kept", "exact_key": "kept-1"}
    older = _normalized_response(
        _normalized_host(alias="apollo", generation="gen-1", rows=[vanished, kept])
    )
    newer = _normalized_response(
        _normalized_host(alias="apollo", generation="gen-2", rows=[kept])
    )

    merged = merge_catalog_pages(older, newer)

    assert merged is not None
    assert [row["logical_key"] for row in merged["summaries"]] == ["kept"]


def test_merge_catalog_pages_unions_pages_within_the_same_snapshot_generation() -> None:
    """Two continuation pages of the same snapshot build still union."""
    page_one: dict[str, object] = {"logical_key": "page-one", "exact_key": "page-one-1"}
    page_two: dict[str, object] = {"logical_key": "page-two", "exact_key": "page-two-1"}
    first = _normalized_response(
        _normalized_host(alias="apollo", generation="gen-1", rows=[page_one])
    )
    second = _normalized_response(
        _normalized_host(alias="apollo", generation="gen-1", rows=[page_two])
    )

    merged = merge_catalog_pages(first, second)

    assert merged is not None
    assert {row["logical_key"] for row in merged["summaries"]} == {
        "page-one",
        "page-two",
    }
