"""Tests for Agent bundle serialization (to_bundle_dict / from_bundle_dict).

Facade preserving the original ``tests.test_agent_model_bundle`` import path.
The tests now live in the sibling ``test_agent_model_bundle_*`` modules and
are re-exported here, so existing imports keep working.
"""

from tests.test_agent_model_bundle_legacy import (
    test_bundle_loads_legacy_pre_rename_fields,
    test_bundle_preserves_plan_chain_stored_name,
    test_bundle_preserves_stored_unprefixed_name,
    test_bundle_round_trips_tale_done_status,
    test_bundle_write_emits_no_legacy_fields,
    test_old_bundle_synthesis_falls_back_to_raw_suffix_date,
    test_old_bundle_synthesis_skips_already_prefixed_name,
    test_old_bundle_synthesis_skips_workflow_children,
    test_old_bundle_synthesizes_prefixed_agent_name_from_stop_time,
)
from tests.test_agent_model_bundle_roundtrip import (
    test_bundle_dict_is_json_serializable_for_populated_agent,
    test_bundle_hydrates_projected_agent_and_skips_projection_fields,
    test_bundle_loads_legacy_tag_as_tribe,
    test_bundle_round_trip_basic,
    test_bundle_round_trip_empty_linked_repos,
    test_bundle_round_trip_linked_repos,
    test_bundle_round_trip_preserves_agent_tribe,
    test_bundle_round_trip_preserves_plan_association,
    test_bundle_serialization_keeps_agent_state_without_artifact_text,
    test_bundle_skips_retry_chain_siblings,
    test_bundle_skips_wait_display_source,
)
from tests.test_agent_model_bundle_times import (
    test_bundle_backward_compat_feedback_time_to_feedback_times,
    test_bundle_backward_compat_missing_feedback_plan_paths,
    test_bundle_backward_compat_plan_time_to_plan_times,
    test_bundle_round_trip_agent_type_serialized_as_string,
    test_bundle_round_trip_datetime_serialization,
    test_bundle_round_trip_feedback_and_questions_times,
    test_bundle_round_trip_feedback_plan_paths,
    test_bundle_round_trip_list_fields,
    test_bundle_round_trip_none_start_time,
    test_bundle_round_trip_plan_and_code_time,
    test_bundle_round_trip_workflow_child,
)

__all__ = [
    "test_bundle_backward_compat_feedback_time_to_feedback_times",
    "test_bundle_backward_compat_missing_feedback_plan_paths",
    "test_bundle_backward_compat_plan_time_to_plan_times",
    "test_bundle_dict_is_json_serializable_for_populated_agent",
    "test_bundle_hydrates_projected_agent_and_skips_projection_fields",
    "test_bundle_loads_legacy_pre_rename_fields",
    "test_bundle_loads_legacy_tag_as_tribe",
    "test_bundle_preserves_plan_chain_stored_name",
    "test_bundle_preserves_stored_unprefixed_name",
    "test_bundle_round_trip_agent_type_serialized_as_string",
    "test_bundle_round_trip_basic",
    "test_bundle_round_trip_datetime_serialization",
    "test_bundle_round_trip_empty_linked_repos",
    "test_bundle_round_trip_feedback_and_questions_times",
    "test_bundle_round_trip_feedback_plan_paths",
    "test_bundle_round_trip_linked_repos",
    "test_bundle_round_trip_list_fields",
    "test_bundle_round_trip_none_start_time",
    "test_bundle_round_trip_plan_and_code_time",
    "test_bundle_round_trip_preserves_agent_tribe",
    "test_bundle_round_trip_preserves_plan_association",
    "test_bundle_round_trip_workflow_child",
    "test_bundle_round_trips_tale_done_status",
    "test_bundle_serialization_keeps_agent_state_without_artifact_text",
    "test_bundle_skips_retry_chain_siblings",
    "test_bundle_skips_wait_display_source",
    "test_bundle_write_emits_no_legacy_fields",
    "test_old_bundle_synthesis_falls_back_to_raw_suffix_date",
    "test_old_bundle_synthesis_skips_already_prefixed_name",
    "test_old_bundle_synthesis_skips_workflow_children",
    "test_old_bundle_synthesizes_prefixed_agent_name_from_stop_time",
]
