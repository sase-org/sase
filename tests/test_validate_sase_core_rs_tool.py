from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._validate_sase_core_rs_tool_helpers import (
    load_validate_sase_core_rs,
    module_with_required_bindings,
)


pytestmark = pytest.mark.contract


def test_validate_sase_core_rs_requires_plan_validation_bindings() -> None:
    validator = load_validate_sase_core_rs()
    plan_bindings = {
        "plan_validate",
        "plan_frontmatter_schema",
        "plan_reference_parse",
        "plan_reference_render",
        "plan_reference_canonicalize",
        "plan_reference_resolve",
        "plan_reference_resolution_wire_schema_version",
        "sdd_artifact_link_parse",
        "sdd_artifact_link_render",
        "sdd_artifact_link_upsert",
    }

    assert plan_bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_bindings(module_with_required_bindings(validator))
    for binding in plan_bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_artifact_link_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "artifact_link_row_schema_version",
        "artifact_link_canonicalize",
        "artifact_link_validate_row",
        "artifact_link_upsert_row",
        "artifact_relations_builtins",
        "artifact_relation_lookup",
        "artifact_relation_label",
        "links_block_parse",
        "links_block_render",
        "links_block_upsert",
        "links_block_remove",
        "links_block_strip",
        "artifact_md_path",
        "companion_md_path",
        "artifact_link_frontmatter_inlet",
    }

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )
    assert validator._validate_artifact_link_schema(
        SimpleNamespace(artifact_link_row_schema_version=lambda: 2)
    )
    assert not validator._validate_artifact_link_schema(
        SimpleNamespace(artifact_link_row_schema_version=lambda: 1)
    )


def test_validate_sase_core_rs_requires_bead_link_mutation_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {"bead_add_link", "bead_remove_link"}

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_feature_flag_state_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {"feature_flag_state_get", "feature_flag_state_set"}

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_inline_code_binding() -> None:
    validator = load_validate_sase_core_rs()

    assert "inline_code_ranges" in validator.REQUIRED_BINDINGS
    assert not validator._validate_bindings(
        module_with_required_bindings(
            validator,
            missing={"inline_code_ranges"},
        )
    )


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
    vcs_log_bindings = {"vcs_log_wire_schema_version", "parse_merge_summary"}

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
