"""Offline fleet response fixtures for TUI tests and benches."""

from __future__ import annotations

from tests.ace.tui._fleet_facade_fixture import (
    OfflineFleetFacade,
    ScriptedFleetFacade,
    fleet_config,
    fleet_config_for_hosts,
    fleet_follow_snapshot,
)
from tests.ace.tui._fleet_locator_fixture import (
    fleet_exact_key,
    fleet_exact_locator,
    fleet_installation_id,
    fleet_logical_key,
    fleet_logical_locator,
)
from tests.ace.tui._fleet_response_fixture import (
    fleet_attention_response,
    fleet_counts,
    fleet_fault_diagnostic,
    fleet_host_payload,
    fleet_host_response,
    fleet_multi_host_response,
)
from tests.ace.tui._fleet_summary_fixture import fleet_summary

__all__ = [
    "OfflineFleetFacade",
    "ScriptedFleetFacade",
    "fleet_attention_response",
    "fleet_config",
    "fleet_config_for_hosts",
    "fleet_counts",
    "fleet_exact_key",
    "fleet_exact_locator",
    "fleet_fault_diagnostic",
    "fleet_follow_snapshot",
    "fleet_host_payload",
    "fleet_host_response",
    "fleet_installation_id",
    "fleet_logical_key",
    "fleet_logical_locator",
    "fleet_multi_host_response",
    "fleet_summary",
]
