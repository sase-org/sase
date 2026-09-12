"""Wire records for the agent-launch migration boundary.

These dataclasses pin the Python-side JSON contract that later Rust-backed
launch phases will implement. Phase 1 only defines and tests the shapes; no
production launch path consumes these records yet.

Module layout
-------------

This module is the stable import path for the agent-launch wire. The
definitions live in sibling modules to keep each file under the 500-line
cap, and are re-exported here:

- :mod:`sase.core.agent_launch_wire_records` — launch, workspace-claim,
  fan-out, and typed-plan dataclasses.
- :mod:`sase.core.agent_launch_wire_conversion` — JSON ``to_dict``
  projection used by the facade adapter and tests.
- :mod:`sase.core.agent_launch_wire_from_dict` — JSON ``from_dict``
  hydrators for the same records.
"""

from __future__ import annotations

from sase.core.agent_launch_wire_conversion import agent_launch_wire_to_json_dict
from sase.core.agent_launch_wire_from_dict import (
    agent_launch_prepared_from_dict,
    batch_predecessor_context_from_dict,
    batch_predecessor_wait_binding_from_dict,
    launch_admission_summary_from_dict,
    launch_fanout_plan_from_dict,
    launch_plan_from_dict,
    launch_unit_result_from_dict,
)
from sase.core.agent_launch_wire_records import (
    AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
    AgentLaunchPreparedWire,
    AgentLaunchRequestWire,
    AgentUnitWire,
    BATCH_PREDECESSOR_CONTEXT_SCHEMA_VERSION,
    BatchPredecessorContextWire,
    BatchPredecessorWaitBindingWire,
    LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
    LaunchAdmissionSummaryWire,
    LaunchConditionWire,
    LaunchFanoutPlanWire,
    LaunchFanoutSlotWire,
    LaunchPlanDiagnosticWire,
    LaunchPlanWire,
    LaunchUnitResultWire,
    LaunchUnitWire,
    LAUNCH_PLAN_WIRE_SCHEMA_VERSION,
    ProcUnitWire,
    WaitTargetWire,
    WorkspaceClaimRequestWire,
)

__all__ = [
    "AGENT_LAUNCH_WIRE_SCHEMA_VERSION",
    "AgentLaunchPreparedWire",
    "AgentLaunchRequestWire",
    "AgentUnitWire",
    "BATCH_PREDECESSOR_CONTEXT_SCHEMA_VERSION",
    "BatchPredecessorContextWire",
    "BatchPredecessorWaitBindingWire",
    "LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION",
    "LaunchAdmissionSummaryWire",
    "LaunchConditionWire",
    "LaunchFanoutPlanWire",
    "LaunchFanoutSlotWire",
    "LaunchPlanDiagnosticWire",
    "LaunchPlanWire",
    "LaunchUnitResultWire",
    "LaunchUnitWire",
    "LAUNCH_PLAN_WIRE_SCHEMA_VERSION",
    "ProcUnitWire",
    "WaitTargetWire",
    "WorkspaceClaimRequestWire",
    "agent_launch_prepared_from_dict",
    "agent_launch_wire_to_json_dict",
    "batch_predecessor_context_from_dict",
    "batch_predecessor_wait_binding_from_dict",
    "launch_admission_summary_from_dict",
    "launch_fanout_plan_from_dict",
    "launch_plan_from_dict",
    "launch_unit_result_from_dict",
]
