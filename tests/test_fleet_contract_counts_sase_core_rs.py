"""Fleet-contract ``sase_core_rs`` tests: counts, follow records, and host rollups."""

from __future__ import annotations

import copy

import pytest

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
