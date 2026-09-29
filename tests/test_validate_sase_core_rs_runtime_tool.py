from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._validate_sase_core_rs_tool_helpers import (
    load_validate_sase_core_rs,
    module_with_required_bindings,
)


pytestmark = pytest.mark.contract


def test_validate_sase_core_rs_requires_telemetry_bindings() -> None:
    validator = load_validate_sase_core_rs()
    telemetry_bindings = {
        "telemetry_record_batch",
        "telemetry_query_instant",
        "telemetry_query_range",
        "telemetry_prune",
        "telemetry_store_stats",
    }

    assert telemetry_bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in telemetry_bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_disk_inventory_bindings() -> None:
    validator = load_validate_sase_core_rs()
    disk_inventory_bindings = {
        "disk_inventory_wire_schema_version",
        "classify_disk_inventory",
    }

    assert disk_inventory_bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in disk_inventory_bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_disk_inventory_wire_schema() -> None:
    validator = load_validate_sase_core_rs()

    assert validator._validate_disk_inventory_wire_schema(
        SimpleNamespace(disk_inventory_wire_schema_version=lambda: 1)
    )
    assert not validator._validate_disk_inventory_wire_schema(
        SimpleNamespace(disk_inventory_wire_schema_version=lambda: 2)
    )


def test_validate_sase_core_rs_requires_gate_decision_lifecycle_contract() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "claim_gate_decision_execution",
        "decide_gate_decision_acceptance",
        "decide_gate_lifecycle",
    }
    seen: dict[str, object] = {}

    def decide_gate_lifecycle(request: object) -> dict[str, object]:
        seen["request"] = request
        return {
            "disposition": "answered",
            "failure": {
                "stage": "side_effects",
            },
        }

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )
    assert validator._validate_gate_decision_lifecycle_contract(
        SimpleNamespace(decide_gate_lifecycle=decide_gate_lifecycle)
    )
    request = seen["request"]
    assert isinstance(request, dict)
    execution_facts = request["execution_facts"]
    assert isinstance(execution_facts, dict)
    post_response_failure = execution_facts["post_response_failure"]
    assert isinstance(post_response_failure, dict)
    assert post_response_failure["stage"] == "side_effects"
    assert not validator._validate_gate_decision_lifecycle_contract(
        SimpleNamespace(
            decide_gate_lifecycle=lambda _request: {"disposition": "answered"}
        )
    )


def test_validate_sase_core_rs_requires_proc_store_bindings() -> None:
    validator = load_validate_sase_core_rs()
    proc_bindings = {
        "read_procs_snapshot",
        "append_proc",
        "update_proc",
        "prune_procs",
    }

    assert proc_bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in proc_bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_proc_lifecycle_bindings() -> None:
    validator = load_validate_sase_core_rs()
    proc_lifecycle_bindings = {
        "reserve_proc",
        "claim_proc_supervisor",
        "request_proc_stop",
        "begin_proc_settlement",
        "finish_proc",
    }

    assert proc_lifecycle_bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in proc_lifecycle_bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_output_variable_history_bindings() -> None:
    validator = load_validate_sase_core_rs()
    history_bindings = {
        "query_agent_output_variable_history",
        "agent_output_variable_history_wire_schema_version",
        "parse_output_variable_selector",
        "query_agent_output_variable_selectors",
        "agent_output_variable_selector_wire_schema_version",
    }

    assert history_bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in history_bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_agent_stats_work_bindings() -> None:
    validator = load_validate_sase_core_rs()
    stats_bindings = {
        "rebuild_agent_artifact_index",
        "agent_stats_query_runs",
        "agent_stats_query_activity",
    }

    assert stats_bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in stats_bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_cleanup_wire_version_binding() -> None:
    validator = load_validate_sase_core_rs()

    assert "agent_cleanup_wire_schema_version" in validator.REQUIRED_BINDINGS
    assert not validator._validate_bindings(
        module_with_required_bindings(
            validator,
            missing={"agent_cleanup_wire_schema_version"},
        )
    )


def test_validate_sase_core_rs_requires_vcs_log_bindings() -> None:
    validator = load_validate_sase_core_rs()
    vcs_log_bindings = {
        "vcs_log_wire_schema_version",
        "parse_merge_summary",
        "classify_commit_types",
    }

    assert vcs_log_bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in vcs_log_bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_snippet_session_binding() -> None:
    validator = load_validate_sase_core_rs()

    assert "apply_snippet_session_event" in validator.REQUIRED_BINDINGS
    assert not validator._validate_bindings(
        module_with_required_bindings(
            validator,
            missing={"apply_snippet_session_event"},
        )
    )


def test_validate_sase_core_rs_requires_finalizer_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "finalizer_wire_schema_version",
        "validate_finalizer_provider_spec",
        "finalizer_provider_spec_digest",
        "validate_finalizer_instance_spec",
        "finalizer_instance_spec_digest",
        "resolve_finalizer_plan",
        "finalizer_plan_digest",
        "finalizer_context_digest",
        "validate_finalizer_context",
        "validate_finalizer_submission",
        "finalizer_json_digest",
        "aggregate_finalizer_outcomes",
    }

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_tool_run_handoff_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {"tool_run_claim", "tool_run_request_stop"}

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_bindings(module_with_required_bindings(validator))
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_probes_tool_run_handoff_contract() -> None:
    validator = load_validate_sase_core_rs()
    good = SimpleNamespace(
        tool_run_normalize_definition=lambda definition: {
            "digest": "digest-1",
            "definition": definition,
        },
        tool_run_begin=lambda store, request, timeout: {
            "run": {"run_id": "run-1", "state": "created"}
        },
        tool_run_claim=lambda store, request, timeout: {
            "outcome": "refused",
            "refusal": "owner_mismatch",
            "run": {"run_id": "run-1"},
        },
        tool_run_show=lambda store, request, timeout: {
            "run": {"run_id": "run-1", "state": "created"}
        },
    )
    assert validator._validate_tool_run_handoff_contract(good)
    stale = SimpleNamespace(
        tool_run_normalize_definition=lambda definition: {
            "digest": "digest-1",
            "definition": definition,
        },
        tool_run_begin=lambda store, request, timeout: {
            "run": {"run_id": "run-1", "state": "created"}
        },
        tool_run_claim=lambda store, request, timeout: {
            "outcome": "claimed",
            "run": {"run_id": "run-1"},
        },
        tool_run_show=lambda store, request, timeout: {
            "run": {"run_id": "run-1", "state": "created"}
        },
    )
    assert not validator._validate_tool_run_handoff_contract(stale)
