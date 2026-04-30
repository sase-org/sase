"""sase.core facade for the agent/artifact filesystem snapshot scan.

Phase 8D rewired :func:`scan_agent_artifacts` to call ``sase_core_rs``
directly through :func:`sase.core.rust.require_rust_binding` and deleted
the Python walker fallback (the marker-loading, JSON-coercion, and
artifact-directory walking helpers that existed only to back the legacy
``dispatch`` Python branch). The Rust extension is a hard runtime
dependency; a missing or stale wheel surfaces as :class:`ImportError` /
:class:`AttributeError` instead of silently switching paths.

What this scanner does NOT do (unchanged from the Phase 3 contract):

- It does not check process liveness. Liveness lives in
  :mod:`sase.ace.hooks.processes` and ``/proc`` guards.
- It does not parse RUNNING-field claims from project ``.gp`` files.
  Workspace-claim semantics live in :mod:`sase.running_field`.
- It does not mutate any filesystem state.

Soft errors (unreadable directories, malformed marker JSON) are absorbed
silently by the Rust scanner and counted in
:class:`AgentArtifactScanStatsWire`. Callers that care about diagnostics
can inspect ``snapshot.stats``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    RunningMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
    WorkflowStepStateWire,
    agent_scan_wire_from_dict,
)
from sase.core.rust import require_rust_binding


def _options_to_dict(options: AgentArtifactScanOptionsWire) -> dict[str, Any]:
    return {
        "include_prompt_step_markers": options.include_prompt_step_markers,
        "include_raw_prompt_snippets": options.include_raw_prompt_snippets,
        "max_prompt_snippet_bytes": options.max_prompt_snippet_bytes,
        "only_workflow_dirs": list(options.only_workflow_dirs),
    }


def scan_agent_artifacts(
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return a snapshot of all agent artifact directories under *projects_root*.

    Calls ``sase_core_rs.scan_agent_artifacts`` directly and rehydrates the
    returned dict into typed wire records via
    :func:`agent_scan_wire_from_dict`. ``projects_root`` is required and is
    normally ``Path.home() / ".sase" / "projects"`` — passing it explicitly
    keeps the contract testable and lets future shells (server, mobile)
    supply a different root without Rust reading global config.

    The Rust binding releases the GIL during the filesystem walk and
    returns the same wire shape callers already consume.
    """
    opts = options or AgentArtifactScanOptionsWire()
    rust_scan = require_rust_binding("scan_agent_artifacts")
    payload: dict[str, Any] = rust_scan(str(projects_root), _options_to_dict(opts))
    return agent_scan_wire_from_dict(payload)


# pyvision: tests/test_core_agent_scan.py
def with_options(
    base: AgentArtifactScanOptionsWire,
    **overrides: Any,
) -> AgentArtifactScanOptionsWire:
    """Return a copy of *base* with *overrides* applied.

    Convenience for callers that want to derive a tweaked options record
    without juggling :func:`dataclasses.replace` imports.
    """
    return replace(base, **overrides)


__all__ = [
    "AgentArtifactRecordWire",
    "AgentArtifactScanOptionsWire",
    "AgentArtifactScanStatsWire",
    "AgentArtifactScanWire",
    "AgentMetaWire",
    "DoneMarkerWire",
    "PlanPathMarkerWire",
    "PromptStepMarkerWire",
    "RunningMarkerWire",
    "WaitingMarkerWire",
    "WorkflowStateWire",
    "WorkflowStepStateWire",
    "scan_agent_artifacts",
    "with_options",
]
