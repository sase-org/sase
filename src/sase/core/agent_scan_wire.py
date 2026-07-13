"""Wire records for the agent/artifact filesystem scan facade.

Sidecar to :mod:`sase.core.wire` and :mod:`sase.core.query_wire`. Defines
the **stable** boundary between Python and a future Rust implementation of
the agent-artifact snapshot scan (Phase 3 of
``sdd/research/202604/rust_backend_migration.md`` and
``../sase_100/plans/202604/rust_backend_phase3_agent_scan.md``).

The wire records intentionally do not subclass or share code with the
existing Python ``Agent`` / ``WorkflowEntry`` / ``RunningAgentInfo``
dataclasses. Those models keep evolving for the TUI/CLI; this contract
changes only with a schema bump.

Scope of the contract
---------------------

A snapshot scan visits ``projects/*/artifacts/<workflow>/<timestamp>/``
trees rooted under a Python-supplied ``projects_root`` (normally
``~/.sase/projects``) and parses a small, fixed set of marker JSON files:

- ``agent_meta.json``
- ``done.json``
- ``running.json``
- ``waiting.json``
- ``pending_question.json``
- ``workflow_state.json``
- ``plan_path.json``
- ``prompt_step_*.json``

Each artifact directory becomes one :class:`AgentArtifactRecordWire`
carrying the markers actually present. Optional markers are ``None`` when
the file is missing or unreadable; the scan does **not** raise on
malformed JSON — it skips the bad file and increments a typed counter on
:class:`AgentArtifactScanStatsWire` so diagnostics are still possible.

Field selection rationale
-------------------------

Only fields currently consumed by Python call sites are exposed. Phase 3D
through 3F will plug the snapshot into:

- ``sase.agent.names._lookup`` (``find_named_agent`` / ``is_workflow_complete``)
- ``sase.agent.running`` (``list_running_agents`` / ``list_all_agents``)
- ``sase.ace.tui.models._loaders._artifact_loaders`` (``load_done_agents``,
  ``load_running_home_agents``, ``enrich_agent_from_meta``)
- ``sase.ace.tui.models._loaders._workflow_loaders`` (``load_workflow_states``)
- ``sase.ace.tui.models._loaders._workflow_step_loaders``
  (``load_workflow_agent_steps``)
- ``sase.ace.tui.models._loaders._workflow_snapshot_loaders`` (snapshot mirrors)

The wire is deliberately compact: arbitrary unknown fields from the marker
JSON files are NOT round-tripped. If a future call site needs an extra
field, add it here (and bump :data:`AGENT_SCAN_WIRE_SCHEMA_VERSION` if the
shape changes incompatibly).

JSON shape conventions
----------------------

- All keys are lowercase ``snake_case``.
- ``None`` is preserved (becomes JSON ``null``).
- Lists are preserved (never replaced with ``None`` for empty branches).
- Timestamps are passed through as the original string form (ISO 8601 for
  ``*_at`` fields; ``YYYYmmddHHMMSS`` for artifact directory names).

Module layout
-------------

This module is the stable import path for the agent-scan wire. The
definitions live in three sibling modules to keep each file under the
500-line cap, and are re-exported here:

- :mod:`sase.core.agent_scan_wire_markers` — per-file marker projections
  (``DoneMarkerWire``, ``AgentMetaWire``, ``RunningMarkerWire``, etc.).
- :mod:`sase.core.agent_scan_wire_records` — top-level scan/record wires
  and scan-option/stats/index dataclasses.
- :mod:`sase.core.agent_scan_wire_conversion` — JSON ``to_dict``/``from_dict``
  helpers used by the facade adapter and tests.
"""

from __future__ import annotations

from sase.core.agent_scan_wire_conversion import (
    agent_artifact_index_query_to_dict,
    agent_artifact_index_status_from_dict,
    agent_artifact_index_update_from_dict,
    agent_scan_wire_from_dict,
    agent_scan_wire_to_json_dict,
)
from sase.core.agent_scan_wire_markers import (
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    RunningMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
    WorkflowStepStateWire,
)
from sase.core.agent_scan_wire_records import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    DONE_WORKFLOW_DIR_NAMES,
    DONE_WORKFLOW_DIR_PREFIXES,
    WORKFLOW_STATE_DIR_NAMES,
    WORKFLOW_STATE_DIR_PREFIXES,
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexStatusWire,
    AgentArtifactIndexUpdateWire,
    AgentArtifactIndexVerifyWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)

__all__ = [
    "AGENT_ARTIFACT_INDEX_SCHEMA_VERSION",
    "AGENT_SCAN_WIRE_SCHEMA_VERSION",
    "DONE_WORKFLOW_DIR_NAMES",
    "DONE_WORKFLOW_DIR_PREFIXES",
    "WORKFLOW_STATE_DIR_NAMES",
    "WORKFLOW_STATE_DIR_PREFIXES",
    "AgentArtifactIndexQueryWire",
    "AgentArtifactIndexStatusWire",
    "AgentArtifactIndexUpdateWire",
    "AgentArtifactIndexVerifyWire",
    "AgentArtifactRecordWire",
    "AgentArtifactScanOptionsWire",
    "AgentArtifactScanStatsWire",
    "AgentArtifactScanWire",
    "AgentMetaWire",
    "DoneMarkerWire",
    "PendingQuestionMarkerWire",
    "PlanPathMarkerWire",
    "PromptStepMarkerWire",
    "RunningMarkerWire",
    "WaitingMarkerWire",
    "WorkflowStateWire",
    "WorkflowStepStateWire",
    "agent_artifact_index_query_to_dict",
    "agent_artifact_index_status_from_dict",
    "agent_artifact_index_update_from_dict",
    "agent_scan_wire_from_dict",
    "agent_scan_wire_to_json_dict",
]
