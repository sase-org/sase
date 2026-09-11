from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests._validate_sase_core_rs_tool_helpers import load_validate_sase_core_rs


pytestmark = pytest.mark.contract


def test_validate_sase_core_rs_requires_stats_v6_commit_and_truncation_fields() -> None:
    validator = load_validate_sase_core_rs()

    def module_with_payload(payload: object) -> SimpleNamespace:
        return SimpleNamespace(
            rebuild_agent_artifact_index=lambda *_args: {},
            agent_stats_query_runs=lambda *_args: payload,
        )

    valid_payload = {
        "schema_version": 6,
        "work": {"projects": [], "changespecs": []},  # legacy wire key
        "commits": {"committing_runs": 0, "committing_agents": 0},
        "xprompts": {
            "rows": [
                {
                    "models_truncated": 0,
                    "projects_truncated": 0,
                    "partners_truncated": 0,
                }
            ]
        },
        "runners": {
            "lanes_counted": 0,
            "lanes_without_end_skipped": 0,
            "user_hidden_skipped": 0,
        },
    }

    assert not validator._validate_agent_stats_work_schema(
        module_with_payload({"schema_version": 3})
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 3,
                "work": {"projects": [], "changespecs": []},
            }  # legacy wire key
        )
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 4,
                "work": {"projects": [], "changespecs": []},
            }  # legacy wire key
        )
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 5,
                "work": {"projects": [], "changespecs": []},  # legacy wire key
                "xprompts": {"rows": []},
            }
        )
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                **valid_payload,
                "commits": {"committing_agents": 0},
            }
        )
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                **valid_payload,
                "xprompts": {"rows": [{"models_truncated": 0}]},
            }
        )
    )
    assert validator._validate_agent_stats_work_schema(
        module_with_payload(valid_payload)
    )


def _reuse_existing_claim_snapshot(**overrides: Any) -> dict[str, Any]:
    snapshot = {
        "occupied_capacity": 2.0,
        "candidate_decision": {
            "decision": "reuse_existing_claim",
            "effective_weight": 2.0,
        },
    }
    snapshot.update(overrides)
    return snapshot


def test_validate_sase_core_rs_requires_runner_capacity_candidate_decision() -> None:
    validator = load_validate_sase_core_rs()

    def module(
        *, policy_schema_version: int = 2, snapshot: Any = None
    ) -> SimpleNamespace:
        def _snapshot(_request: dict[str, Any]) -> Any:
            if isinstance(snapshot, Exception):
                raise snapshot
            return (
                snapshot if snapshot is not None else _reuse_existing_claim_snapshot()
            )

        return SimpleNamespace(
            runner_capacity_policy_schema_version=lambda: policy_schema_version,
            runner_capacity_snapshot=_snapshot,
        )

    assert validator._validate_runner_capacity_contract(module())

    # A schema-v1 wheel predates candidate_decision entirely.
    assert not validator._validate_runner_capacity_contract(
        module(policy_schema_version=1)
    )

    # A schema-v1 wire rejects the request's ``candidate`` field outright.
    assert not validator._validate_runner_capacity_contract(
        module(snapshot=ValueError("unknown field `candidate`"))
    )

    # Double-charging a parallel member and its serial successor.
    assert not validator._validate_runner_capacity_contract(
        module(snapshot=_reuse_existing_claim_snapshot(occupied_capacity=4.0))
    )

    # No usable candidate_decision in the response.
    assert not validator._validate_runner_capacity_contract(
        module(snapshot=_reuse_existing_claim_snapshot(candidate_decision=None))
    )

    # A blocked/parked decision instead of transferring the live claim.
    assert not validator._validate_runner_capacity_contract(
        module(
            snapshot=_reuse_existing_claim_snapshot(
                candidate_decision={"decision": "blocked", "effective_weight": 2.0}
            )
        )
    )

    # The wrong effective weight for the shared lineage.
    assert not validator._validate_runner_capacity_contract(
        module(
            snapshot=_reuse_existing_claim_snapshot(
                candidate_decision={
                    "decision": "reuse_existing_claim",
                    "effective_weight": 1.0,
                }
            )
        )
    )


def test_validate_sase_core_rs_requires_capacity_only_claim_owner_key() -> None:
    validator = load_validate_sase_core_rs()

    def module(*, owner_key: Any) -> SimpleNamespace:
        def _scan(_projects_root: str, _options: dict[str, Any]) -> dict[str, Any]:
            return {
                "records": [
                    {
                        "timestamp": "20260427110500",
                        "agent_meta": {"runner_claim_owner_key": owner_key},
                    }
                ]
            }

        return SimpleNamespace(scan_agent_artifacts=_scan)

    assert validator._validate_capacity_only_scan_contract(
        module(owner_key="probe:fam:parallel:20260427110500")
    )

    # A wheel built before runner_claim_owner_key existed drops it silently.
    assert not validator._validate_capacity_only_scan_contract(module(owner_key=None))


def test_validate_sase_core_rs_requires_weighted_fleet_summary_fields() -> None:
    validator = load_validate_sase_core_rs()

    def module(
        *, queue_weight: Any = 2.0, raises: Exception | None = None
    ) -> SimpleNamespace:
        def _summary(_request: dict[str, Any]) -> Any:
            if raises is not None:
                raise raises
            return {"queue_weight": queue_weight}

        return SimpleNamespace(
            fleet_logical_locator_key=lambda _locator: "logical-key",
            fleet_project_resolved_agent_summary=_summary,
        )

    assert validator._validate_weighted_fleet_summary_contract(module())

    # A wheel built before the fleet-weight fields existed silently omits it.
    assert not validator._validate_weighted_fleet_summary_contract(
        module(queue_weight=None)
    )

    assert not validator._validate_weighted_fleet_summary_contract(
        module(raises=ValueError("unknown field `queue_weight`"))
    )
