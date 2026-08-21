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
    finalizer_plan_digest as _finalizer_plan_digest,
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
from sase.finalizers.sdk import FinalizerProvider as _FinalizerProvider
from sase.finalizers.sdk import sdk_worker_main as _sdk_worker_main

_PUBLIC_API_REFS = (
    _BuiltinCommitExecution,
    _FinalContextPublication,
    _FinalizerExecutionError,
    _FinalizerFieldProvenance,
    _FinalizerInstanceView,
    _FinalizerPlanEntryWire,
    _FinalizerProvider,
    _FinalizerSubmissionPayloadWire,
    _StitchCommandResult,
    _build_finalizer_inventory,
    _execute_command_finalizer,
    _execute_plugin_finalizer,
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
    _run_provider_operation,
    _run_stitch_create,
    _sdk_worker_main,
    _validate_finalizer_instance_spec,
    _validate_finalizer_provider_spec,
)
