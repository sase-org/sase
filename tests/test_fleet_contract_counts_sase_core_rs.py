"""Fleet-contract ``sase_core_rs`` tests: counts, follow records, and host rollups."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from sase.ace.tui.models.fleet_agents import project_fleet_agents
from tests._fleet_contract_sase_core_rs_helpers import (
    _binding,
    _follow_record,
    _known_installation_id,
    _logical_locator,
    _operation_key,
    _origin,
    _summary_for_agent,
    _tombstone,
)


def test_count_contract_deduplicates_current_instances_and_buckets() -> None:
    installation_id = _known_installation_id("a")
    running_old = _summary_for_agent(
        installation_id, agent_id="agent-run", run_id="run-1", revision=1
    )
    running_new = _summary_for_agent(
        installation_id, agent_id="agent-run", run_id="run-2", revision=2
    )
    waiting = _summary_for_agent(
        installation_id, agent_id="agent-wait", run_id="run-1", revision=3
    )
    waiting["lifecycle"] = "waiting"
    waiting["status_bucket"] = "waiting"
    waiting["occupied_runner_slot"] = False
    attention = _summary_for_agent(
        installation_id, agent_id="agent-attn", run_id="run-1", revision=4
    )
    attention["needs_attention"] = True
    monitor = _summary_for_agent(
        installation_id, agent_id="agent-monitor", run_id="run-1", revision=5
    )
    monitor["row_kind"] = "monitor"

    counts = _binding("fleet_count_logical_agents")(
        {
            "schema_version": 1,
            "summaries": [monitor, attention, waiting, running_old, running_new],
        }
    )
    assert counts["basis"]["input_rows"] == 5
    assert counts["basis"]["selected_rows"] == 3
    assert counts["logical_agent_total"] == 3
    assert counts["running"] == 2
    assert counts["waiting"] == 1
    assert counts["attention"] == 1
    assert counts["occupied_runner_slots"] == 2

    ambiguous = copy.deepcopy(running_new)
    ambiguous["exact_locator"]["run_id"] = "run-ambiguous"
    ambiguous["exact_key"] = _binding("fleet_instance_locator_key")(
        ambiguous["exact_locator"]
    )
    with pytest.raises(ValueError, match="ambiguous current instances"):
        _binding("fleet_count_logical_agents")(
            {
                "schema_version": 1,
                "summaries": [running_new, ambiguous],
            }
        )


def test_follow_reconciliation_promotes_and_honors_tombstones() -> None:
    installation_id = _known_installation_id("a")
    singleton = _logical_locator(installation_id, family_id=None)
    family = _logical_locator(installation_id, family_id="family-1")
    reconcile = _binding("fleet_reconcile_follow_records")

    promoted = reconcile(
        {
            "schema_version": 1,
            "records": [
                _follow_record(
                    singleton,
                    created_by="explicit",
                    state="active",
                    timestamp=10.0,
                )
            ],
            "tombstones": [],
            "promotions": [{"schema_version": 1, "from": singleton, "to": family}],
            "activations": [],
            "now_unix": 12.0,
        }
    )
    assert promoted["changed"] is True
    assert len(promoted["records"]) == 1
    assert promoted["records"][0]["logical_locator"] == family
    assert promoted["records"][0]["updated_at_unix"] == 12.0
    assert _binding("fleet_follow_record_key")(promoted["records"][0])

    dispatch_pending = _follow_record(
        family, created_by="dispatch", state="pending", timestamp=20.0
    )
    suppressed = reconcile(
        {
            "schema_version": 1,
            "records": [dispatch_pending],
            "tombstones": [_tombstone(family, 21.0)],
            "promotions": [],
            "activations": [
                {
                    "schema_version": 1,
                    "logical_locator": family,
                    "operation_key": _operation_key(),
                    "activated_at_unix": 22.0,
                }
            ],
            "now_unix": 22.0,
        }
    )
    assert suppressed["records"] == []
    assert suppressed["tombstones"][0]["logical_locator"] == family
    assert any(
        diagnostic["code"]
        in {"follow_activation_tombstoned", "follow_tombstone_blocked"}
        for diagnostic in suppressed["diagnostics"]
    )


def test_focus_fleet_counts_propagate_partial_hosts_without_summing_views() -> None:
    local = _summary_for_agent(
        _known_installation_id("a"), agent_id="local", run_id="run-1", revision=1
    )
    followed_remote = _summary_for_agent(
        _known_installation_id("b"), agent_id="remote-a", run_id="run-1", revision=2
    )
    fleet_only = _summary_for_agent(
        _known_installation_id("c"), agent_id="remote-b", run_id="run-1", revision=3
    )

    counts = _binding("fleet_count_focus_and_fleet")(
        {
            "schema_version": 1,
            "local_summaries": [local],
            "followed_remote_hosts": [
                {
                    "schema_version": 1,
                    "origin": _origin(_known_installation_id("b")),
                    "summaries": [followed_remote],
                    "observed_at_unix": 2000.0,
                    "freshness": "fresh",
                }
            ],
            "fleet_hosts": [
                {
                    "schema_version": 1,
                    "origin": _origin(_known_installation_id("b")),
                    "summaries": [followed_remote],
                    "observed_at_unix": 2000.0,
                    "freshness": "fresh",
                },
                {
                    "schema_version": 1,
                    "origin": _origin(_known_installation_id("c")),
                    "summaries": [fleet_only],
                    "observed_at_unix": 1500.0,
                    "freshness": "aging",
                },
                {
                    "schema_version": 1,
                    "origin": _origin(_known_installation_id("d")),
                    "summaries": [],
                    "observed_at_unix": None,
                    "freshness": "unknown",
                },
            ],
        }
    )

    assert counts["focus"]["counts"]["running"] == 2
    assert counts["fleet"]["counts"]["running"] == 2
    assert counts["focus"]["partial"] is False
    assert counts["fleet"]["partial"] is True
    assert counts["fleet"]["unknown_origins"] == [_known_installation_id("d")]
    assert counts["fleet"]["observed_at_unix_max"] == 2000.0


def test_normalize_federation_response_preserves_catalog_counts_and_freshness() -> None:
    installation_id = _known_installation_id("b")
    done = _done_summary(
        _summary_for_agent(installation_id, agent_id="done", run_id="run-1", revision=7)
    )
    response = _catalog_response(
        installation_id=installation_id,
        rows=[done],
        running=9,
        partial=True,
        next_cursor="off:50",
        observed_at=1_800_000_000.0,
    )

    normalized = _binding("fleet_normalize_federation_response")(
        {"schema_version": 1, "response": response}
    )
    projection = project_fleet_agents(catalog_response=response)

    assert normalized["partial"] is True
    assert normalized["next_cursor"] == "off:50"
    assert normalized["hosts"][0]["authoritative_counts"]["running"] == 9
    assert normalized["hosts"][0]["observed_at_unix"] == 1_800_000_000.0
    assert normalized["count_hosts"][0]["partial"] is True
    assert projection.partial is True
    assert projection.fleet_rows[0].fleet_observed_at_unix == 1_800_000_000.0
    assert projection.counts["fleet"] == 9


def test_project_fleet_agents_counts_followed_entries_not_batch_host_totals() -> None:
    installation_id = _known_installation_id("c")
    followed_done = _done_summary(
        _summary_for_agent(
            installation_id,
            agent_id="followed-done",
            run_id="run-1",
            revision=8,
        )
    )
    followed = _followed_response(
        installation_id=installation_id,
        entries=[
            {
                "schema_version": 1,
                "requested_logical_key": followed_done["logical_key"],
                "summary": followed_done,
            },
            {
                "schema_version": 1,
                "requested_logical_key": "missing-logical-key",
                "summary": None,
            },
        ],
        running=9,
    )
    catalog = _catalog_response(
        installation_id=installation_id,
        rows=[followed_done],
        running=9,
        partial=False,
    )

    projection = project_fleet_agents(
        catalog_response=catalog,
        followed_response=followed,
        local_agent_count=2,
    )

    assert projection.counts["fleet"] == 9
    assert projection.counts["focus_remote"] == 0
    assert projection.counts["focus_total"] == 2
    assert (
        projection.counts["wire"]["focus"]["host_counts"][0]["counts"]["running"] == 0
    )


def _done_summary(summary: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(summary)
    result["status"] = "DONE"
    result["status_bucket"] = "done"
    result["lifecycle"] = "terminal"
    result["liveness"] = "dead"
    result["occupied_runner_slot"] = False
    result["current_instance"] = True
    return result


def _host_counts(
    *,
    running: int,
    total: int,
    observed_at: float | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "basis": {
            "schema_version": 1,
            "input_rows": total,
            "selected_rows": total,
            "max_revision": total,
            "observed_at_unix_max": observed_at,
        },
        "logical_agent_total": total,
        "running": running,
        "waiting": 0,
        "attention": 0,
        "occupied_runner_slots": running,
    }


def _freshness(*, partial: bool, observed_at: float) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "freshness": "fresh",
        "partial": partial,
        "refreshed_at_unix": observed_at,
        "error": "catalog_partial" if partial else None,
    }


def _catalog_response(
    *,
    installation_id: str,
    rows: list[dict[str, Any]],
    running: int,
    partial: bool,
    next_cursor: str | None = None,
    observed_at: float = 2_000.0,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "catalog",
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": "apollo",
                "installation_id": installation_id,
                "status": "ok",
                "cached": False,
                "payload": {
                    "schema_version": 1,
                    "counts": _host_counts(
                        running=running,
                        total=max(running, len(rows)),
                        observed_at=observed_at,
                    ),
                    "count_revision": 99,
                    "freshness": _freshness(
                        partial=partial,
                        observed_at=observed_at,
                    ),
                    "page": {
                        "schema_version": 1,
                        "rows": rows,
                        "limit": 50,
                        "total_matching_rows": max(running, len(rows)),
                        "next_cursor": next_cursor,
                        "has_more": next_cursor is not None,
                    },
                },
                "error": None,
            }
        ],
    }


def _followed_response(
    *,
    installation_id: str,
    entries: list[dict[str, Any]],
    running: int,
    observed_at: float = 2_000.0,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "followed_batch",
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": "apollo",
                "installation_id": installation_id,
                "status": "ok",
                "cached": False,
                "payload": {
                    "schema_version": 1,
                    "counts": _host_counts(
                        running=running,
                        total=running,
                        observed_at=observed_at,
                    ),
                    "freshness": _freshness(
                        partial=False,
                        observed_at=observed_at,
                    ),
                    "entries": entries,
                },
                "error": None,
            }
        ],
    }
