"""Agents-tab reproduction bundle helpers."""

from .invariants import (
    ReproInvariantFailure,
    ReproInvariantReport,
    check_bundle_invariants,
)
from .capture import (
    AgentsTabReproCaptureRing,
    capture_agents_tab_repro_bundle,
    disable_agents_tab_repro_capture,
    enable_agents_tab_repro_capture,
    get_agents_tab_repro_capture,
    record_agents_tab_app_projection,
    record_agents_tab_loader_result,
)
from .redact import RedactionContext, redact_bundle
from .replay import (
    ReproReplayResult,
    ReproReplayStepSnapshot,
    replay_agents_tab_bundle,
)
from .schema import (
    AgentIdentity,
    ReproAgentRow,
    ReproAppState,
    ReproAssertions,
    ReproBundle,
    ReproLoadState,
    ReproLoadStep,
    ReproManifest,
    ReproScreen,
    ReproSelectionFallback,
    load_bundle,
)
from .serialize import serialize_agent_row, serialize_agent_rows

__all__ = [
    "AgentIdentity",
    "AgentsTabReproCaptureRing",
    "ReproAgentRow",
    "ReproAppState",
    "ReproAssertions",
    "ReproBundle",
    "ReproInvariantFailure",
    "ReproInvariantReport",
    "ReproLoadState",
    "ReproLoadStep",
    "ReproManifest",
    "ReproReplayResult",
    "ReproReplayStepSnapshot",
    "ReproScreen",
    "ReproSelectionFallback",
    "RedactionContext",
    "capture_agents_tab_repro_bundle",
    "check_bundle_invariants",
    "disable_agents_tab_repro_capture",
    "enable_agents_tab_repro_capture",
    "get_agents_tab_repro_capture",
    "load_bundle",
    "record_agents_tab_app_projection",
    "record_agents_tab_loader_result",
    "redact_bundle",
    "replay_agents_tab_bundle",
    "serialize_agent_row",
    "serialize_agent_rows",
]
