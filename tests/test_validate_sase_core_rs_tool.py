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
        "artifact_row_resolution_wire_schema_version",
        "artifact_link_publication_state_wire_schema_version",
        "artifact_link_publication_record_key",
        "artifact_link_publication_register_pending",
        "artifact_link_publication_due",
        "artifact_link_publication_mark_attempt",
        "artifact_link_event_schema_version",
        "artifact_link_event_canonicalize",
        "artifact_link_event_canonical_json",
        "artifact_link_event_digest",
        "artifact_link_event_path_for_digest",
        "artifact_link_event_validate_path",
        "artifact_link_event_validate_bytes",
        "artifact_link_event_resolve_aliases",
        "artifact_link_events_reduce",
        "artifact_link_ref_parts",
        "artifact_row_index_keys",
        "artifact_row_ref_lookup_keys",
        "artifact_row_resolve",
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
        SimpleNamespace(
            artifact_link_row_schema_version=lambda: 2,
            artifact_link_event_schema_version=lambda: 1,
            artifact_row_resolution_wire_schema_version=lambda: 1,
            artifact_link_publication_state_wire_schema_version=lambda: 1,
        )
    )
    assert not validator._validate_artifact_link_schema(
        SimpleNamespace(
            artifact_link_row_schema_version=lambda: 1,
            artifact_link_event_schema_version=lambda: 1,
            artifact_row_resolution_wire_schema_version=lambda: 1,
            artifact_link_publication_state_wire_schema_version=lambda: 1,
        )
    )
    assert not validator._validate_artifact_link_schema(
        SimpleNamespace(
            artifact_link_row_schema_version=lambda: 2,
            artifact_link_event_schema_version=lambda: 2,
            artifact_row_resolution_wire_schema_version=lambda: 1,
            artifact_link_publication_state_wire_schema_version=lambda: 1,
        )
    )
    assert not validator._validate_artifact_link_schema(
        SimpleNamespace(
            artifact_link_row_schema_version=lambda: 2,
            artifact_link_event_schema_version=lambda: 1,
            artifact_row_resolution_wire_schema_version=lambda: 2,
            artifact_link_publication_state_wire_schema_version=lambda: 1,
        )
    )
    assert not validator._validate_artifact_link_schema(
        SimpleNamespace(
            artifact_link_row_schema_version=lambda: 2,
            artifact_link_event_schema_version=lambda: 1,
            artifact_row_resolution_wire_schema_version=lambda: 1,
            artifact_link_publication_state_wire_schema_version=lambda: 2,
        )
    )


def test_validate_sase_core_rs_probes_artifact_link_event_contract() -> None:
    validator = load_validate_sase_core_rs()
    digest = "a" * 64
    path = f"link-events/v1/{digest[:2]}/{digest}.json"
    good = SimpleNamespace(
        artifact_link_event_canonicalize=lambda event: event,
        artifact_link_event_canonical_json=lambda event: "{}\n",
        artifact_link_event_digest=lambda event: digest,
        artifact_link_event_path_for_digest=lambda value: path,
        artifact_link_event_validate_path=lambda value, expected: value,
        artifact_link_event_validate_bytes=lambda payload, value: {
            "digest": digest,
            "path": value,
        },
        artifact_link_event_resolve_aliases=lambda aliases, refs: {
            "resolved_refs": {
                "plan:202609/old.md": "plan:202609/new.md",
            }
        },
        artifact_link_events_reduce=lambda events, aliases: {
            "rows": [
                {
                    "target_ref": "plan:202609/new.md",
                    "description": "updated description",
                    "uses": 2,
                }
            ]
        },
    )
    assert validator._validate_artifact_link_event_contract(good)

    stale = SimpleNamespace(
        **{
            **good.__dict__,
            "artifact_link_events_reduce": lambda events, aliases: {
                "rows": [
                    {
                        "target_ref": "plan:202609/old.md",
                        "description": "stale",
                        "uses": 4,
                    }
                ]
            },
        }
    )
    assert not validator._validate_artifact_link_event_contract(stale)


def test_validate_sase_core_rs_requires_machine_setup_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "machine_setup_wire_schema_version",
        "classify_tailnet_health",
        "classify_tailnet_discovery",
        "reconcile_machine_enrollments",
        "fleet_followed_batch_family_promotions",
    }

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_bindings(module_with_required_bindings(validator))
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_pending_commit_checkpoint_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "pending_commit_checkpoint_wire_schema_version",
        "decide_pending_commit_checkpoint_recovery",
    }

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_bindings(module_with_required_bindings(validator))
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_artifact_context_query_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "artifact_context_query",
        "artifact_context_query_wire_schema_version",
    }

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_bindings(module_with_required_bindings(validator))
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
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


def test_validate_sase_core_rs_requires_fleet_contract_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "fleet_contract_schema_version",
        "fleet_installation_identity_load",
        "fleet_installation_identity_ensure",
        "fleet_installation_identity_rotate",
        "fleet_installation_identity_migrate",
        "fleet_logical_locator_key",
        "fleet_instance_locator_key",
        "fleet_associate_owner_display_name",
        "fleet_project_resolved_agent_summary",
        "fleet_project_resolved_agent_detail",
        "fleet_validate_resolved_agent_summary",
        "fleet_count_logical_agents",
        "fleet_follow_record_key",
        "fleet_reconcile_follow_records",
        "fleet_followed_batch_family_promotions",
        "fleet_count_focus_and_fleet",
        "fleet_classify_cursor_replay",
        "fleet_operation_payload_fingerprint",
        "fleet_decide_operation_replay",
        "fleet_mutation_payload_fingerprint",
        "fleet_validate_mutation_request",
        "fleet_evaluate_mutation_precondition",
        "fleet_partition_bulk_targets",
        "fleet_validate_connection_plan",
        "machine_setup_wire_schema_version",
        "classify_tailnet_health",
        "classify_tailnet_discovery",
        "reconcile_machine_enrollments",
        "federation_worker_main",
        "fleet_classify_runtime_duration",
        "fleet_classify_cache_freshness",
    }

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


def test_validate_sase_core_rs_requires_fenced_code_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "fenced_block_ranges",
        "fenced_block_details",
        "scan_directive_owned_fences",
        "code_value_wire_schema_version",
    }

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_prompt_archive_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "prompt_archive_inventory",
        "prompt_archive_inventory_wire_schema_version",
    }

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
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
