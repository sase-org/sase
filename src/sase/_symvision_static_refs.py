"""Static references for source-scoped public API analysis.

Symvision intentionally scans ``src/sase`` instead of tests or external entry
points. Keep public APIs that are exercised through those boundaries visible
without changing their runtime owners.
"""

from __future__ import annotations

from sase.core.finalizer_facade import (
    finalizer_context_digest as _finalizer_context_digest,
)
from sase.core.finalizer_facade import (
    finalizer_instance_spec_digest as _finalizer_instance_spec_digest,
)
from sase.core.finalizer_facade import (
    authenticate_finalizer_plan as _authenticate_finalizer_plan,
)
from sase.core.finalizer_facade import (
    finalizer_plan_digest as _finalizer_plan_digest,
)
from sase.core.finalizer_facade import (
    validate_finalizer_plan as _validate_finalizer_plan,
)
from sase.core.finalizer_facade import (
    finalizer_provider_spec_digest as _finalizer_provider_spec_digest,
)
from sase.core.finalizer_facade import (
    finalizer_wire_schema_version as _finalizer_wire_schema_version,
)
from sase.core.finalizer_facade import (
    validate_finalizer_instance_spec as _validate_finalizer_instance_spec,
)
from sase.core.finalizer_facade import (
    validate_finalizer_provider_spec as _validate_finalizer_provider_spec,
)
from sase.core.finalizer_wire import FinalizerPlanEntryWire as _FinalizerPlanEntryWire
from sase.core.finalizer_wire import (
    FinalizerSubmissionPayloadWire as _FinalizerSubmissionPayloadWire,
)
from sase.core.finalizer_wire import (
    finalizer_attempt_from_dict as _finalizer_attempt_from_dict,
)
from sase.core.finalizer_wire import (
    finalizer_diagnostic_from_dict as _finalizer_diagnostic_from_dict,
)
from sase.core.finalizer_wire import (
    finalizer_instance_policy_from_dict as _finalizer_instance_policy_from_dict,
)
from sase.core.finalizer_wire import (
    finalizer_instance_result_from_dict as _finalizer_instance_result_from_dict,
)
from sase.core.finalizer_wire import (
    finalizer_instance_spec_from_dict as _finalizer_instance_spec_from_dict,
)
from sase.core.finalizer_wire import (
    finalizer_provider_spec_from_dict as _finalizer_provider_spec_from_dict,
)
from sase.core.commit_finalizer_prompt_artifacts import (
    commit_finalizer_pass_prompt_filename as _commit_finalizer_pass_prompt_filename,
)
from sase.ace.tui.modals.config_hub_catalog import (
    config_subtab_specs as _config_subtab_specs,
)
from sase.ace.tui.modals.models_panel import ModelsPanel as _ModelsPanel
from sase.ace.tui.util.artifact_ref_syntax import (
    ArtifactRefCandidateSpans as _ArtifactRefCandidateSpans,
)
from sase.ace.tui.util.artifact_ref_syntax import (
    ArtifactRefPartSpan as _ArtifactRefPartSpan,
)
from sase.ace.tui.util.artifact_ref_syntax import (
    ArtifactRefStyledSpan as _ArtifactRefStyledSpan,
)
from sase.feature_flags.cli_summary import FlagListSummary as _FlagListSummary
from sase.feature_flags.state import (
    SavedFeatureFlagSetOutcome as _SavedFeatureFlagSetOutcome,
)
from sase.feature_flags.state import SavedFeatureFlagState as _SavedFeatureFlagState
from sase.feature_flags.state import feature_flag_state_path as _feature_flag_state_path
from sase.core.finalizer_wire import (
    finalizer_selector_op_from_dict as _finalizer_selector_op_from_dict,
)
from sase.finalizers.artifacts import finalizer_runs_dir as _finalizer_runs_dir
from sase.finalizers.cli import FinalizerInstanceView as _FinalizerInstanceView
from sase.finalizers.cli import build_finalizer_inventory as _build_finalizer_inventory
from sase.finalizers.commit import BuiltinCommitExecution as _BuiltinCommitExecution
from sase.finalizers.commit import StitchCommandResult as _StitchCommandResult
from sase.finalizers.commit import run_stitch_create as _run_stitch_create
from sase.finalizers.config import FinalizerFieldProvenance as _FinalizerFieldProvenance
from sase.finalizers.controller import (
    FinalizerControllerError as _FinalizerControllerError,
)
from sase.finalizers.declaration import (
    FinalContextPublication as _FinalContextPublication,
)
from sase.finalizers.declaration import (
    final_submission_is_current as _final_submission_is_current,
)
from sase.finalizers.executor import FinalizerExecutionError as _FinalizerExecutionError
from sase.finalizers.executor import (
    execute_command_finalizer as _execute_command_finalizer,
)
from sase.finalizers.executor import (
    execute_plugin_finalizer as _execute_plugin_finalizer,
)
from sase.finalizers.executor import result_to_json as _result_to_json
from sase.finalizers.executor import run_provider_operation as _run_provider_operation
from sase.finalizers.reconciliation import (
    auto_commit_done_plan_status_if_possible as _auto_commit_done_plan_status_if_possible,
)
from sase.finalizers.reconciliation import (
    auto_commit_external_sdd_prompt_qa_if_possible as _auto_commit_external_sdd_prompt_qa_if_possible,
)
from sase.finalizers.reconciliation import (
    auto_commit_sdd_bead_reprojection_if_possible as _auto_commit_sdd_bead_reprojection_if_possible,
)
from sase.finalizers.reconciliation import (
    auto_commit_separate_sdd_store_if_possible as _auto_commit_separate_sdd_store_if_possible,
)
from sase.finalizers.reconciliation import clean_result_reason as _clean_result_reason
from sase.finalizers.sdk import FinalizerProvider as _FinalizerProvider
from sase.finalizers.sdk import sdk_worker_main as _sdk_worker_main
from sase.llm_provider.commit_finalizer_prompting import (
    result_changed_files as _result_changed_files,
)
from sase.main._init_skills_manifest import (
    SkillManifestOwnershipPlan as _SkillManifestOwnershipPlan,
)

_PUBLIC_API_REFS = (
    _ArtifactRefCandidateSpans,
    _ArtifactRefPartSpan,
    _ArtifactRefStyledSpan,
    _BuiltinCommitExecution,
    _FinalContextPublication,
    _FinalizerExecutionError,
    _FinalizerControllerError,
    _FinalizerFieldProvenance,
    _FinalizerInstanceView,
    _FinalizerPlanEntryWire,
    _FinalizerProvider,
    _FinalizerSubmissionPayloadWire,
    _FlagListSummary,
    _ModelsPanel,
    _SavedFeatureFlagSetOutcome,
    _SavedFeatureFlagState,
    _SkillManifestOwnershipPlan,
    _StitchCommandResult,
    _build_finalizer_inventory,
    _authenticate_finalizer_plan,
    _auto_commit_done_plan_status_if_possible,
    _auto_commit_external_sdd_prompt_qa_if_possible,
    _auto_commit_sdd_bead_reprojection_if_possible,
    _auto_commit_separate_sdd_store_if_possible,
    _clean_result_reason,
    _commit_finalizer_pass_prompt_filename,
    _config_subtab_specs,
    _execute_command_finalizer,
    _execute_plugin_finalizer,
    _feature_flag_state_path,
    _final_submission_is_current,
    _finalizer_attempt_from_dict,
    _finalizer_context_digest,
    _finalizer_diagnostic_from_dict,
    _finalizer_instance_policy_from_dict,
    _finalizer_instance_result_from_dict,
    _finalizer_instance_spec_digest,
    _finalizer_instance_spec_from_dict,
    _finalizer_plan_digest,
    _finalizer_provider_spec_digest,
    _finalizer_provider_spec_from_dict,
    _finalizer_runs_dir,
    _finalizer_selector_op_from_dict,
    _finalizer_wire_schema_version,
    _result_to_json,
    _result_changed_files,
    _run_provider_operation,
    _run_stitch_create,
    _sdk_worker_main,
    _validate_finalizer_instance_spec,
    _validate_finalizer_plan,
    _validate_finalizer_provider_spec,
)
