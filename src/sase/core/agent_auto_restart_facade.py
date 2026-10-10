"""Rust-backed update-skew auto-restart facade.

The Rust core classifies observed failure facts, context, and witnesses
into a stable recovery verdict, advances the durable at-most-once
ledger, and derives the update-episode identity. Python owns witness
collection, quiescence, the fresh-interpreter probe, evidence, and the
relaunch itself (later phases).
"""

from __future__ import annotations

from typing import Any

from sase.core.agent_auto_restart_wire import (
    AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION,
    AgentFailureFactsWire,
    AutoRestartContextWire,
    AutoRestartEpisodeWire,
    AutoRestartLedgerRecordWire,
    AutoRestartWitnessesWire,
    RecoveryVerdictWire,
    agent_failure_facts_to_dict,
    auto_restart_context_to_dict,
    auto_restart_witnesses_to_dict,
    episode_from_dict,
    ledger_record_from_dict,
    ledger_record_to_dict,
    recovery_verdict_from_dict,
)
from sase.core.rust import require_rust_binding


def auto_restart_wire_schema_version() -> int:
    """Return the auto-restart wire schema version from ``sase_core_rs``."""
    binding = require_rust_binding("agent_auto_restart_wire_schema_version")
    return int(binding())


def classify_agent_failure(
    context: AutoRestartContextWire,
    witnesses: AutoRestartWitnessesWire,
    facts: AgentFailureFactsWire | None = None,
) -> RecoveryVerdictWire:
    """Classify one failed agent through ``sase_core_rs``."""
    binding = require_rust_binding("classify_agent_failure")
    raw: dict[str, object] = binding(
        None if facts is None else agent_failure_facts_to_dict(facts),
        auto_restart_context_to_dict(context),
        auto_restart_witnesses_to_dict(witnesses),
    )
    return recovery_verdict_from_dict(raw)


def claim_auto_restart_ledger(
    key: str, lineage_root: str, *, at: str | None = None
) -> AutoRestartLedgerRecordWire:
    """Create a freshly claimed ledger record through ``sase_core_rs``."""
    binding = require_rust_binding("claim_auto_restart_ledger")
    raw: dict[str, object] = binding(key, lineage_root, at=at)
    return ledger_record_from_dict(raw)


def advance_auto_restart_ledger(
    record: AutoRestartLedgerRecordWire, event: str, *, at: str | None = None
) -> AutoRestartLedgerRecordWire:
    """Advance one ledger record; illegal transitions raise ``ValueError``."""
    binding = require_rust_binding("advance_auto_restart_ledger")
    try:
        raw: dict[str, object] = binding(ledger_record_to_dict(record), event, at=at)
    except ValueError as exc:
        raise ValueError(
            f"illegal auto-restart ledger transition: {record.state} + {event}"
        ) from exc
    return ledger_record_from_dict(raw)


def auto_restart_lineage_root(
    *,
    auto_restart_lineage_root: str | None = None,
    retry_chain_root_timestamp: str | None = None,
    artifacts_timestamp: str,
) -> str:
    """Derive the lineage root through ``sase_core_rs``."""
    binding = require_rust_binding("auto_restart_lineage_root")
    return str(
        binding(
            artifacts_timestamp,
            auto_restart_lineage_root,
            retry_chain_root_timestamp,
        )
    )


def derive_auto_restart_episode(
    witnesses: AutoRestartWitnessesWire,
) -> AutoRestartEpisodeWire:
    """Derive the episode identity through ``sase_core_rs``."""
    binding = require_rust_binding("derive_auto_restart_episode")
    raw: dict[str, object] = binding(auto_restart_witnesses_to_dict(witnesses))
    return episode_from_dict(raw)


def auto_restart_recovery_is_in_flight(state: str | None) -> bool:
    """Return whether a done-marker recovery state renders as restarting."""
    binding = require_rust_binding("auto_restart_recovery_is_in_flight")
    return bool(binding(state))


__all__ = [
    "advance_auto_restart_ledger",
    "auto_restart_lineage_root",
    "auto_restart_recovery_is_in_flight",
    "auto_restart_wire_schema_version",
    "claim_auto_restart_ledger",
    "classify_agent_failure",
    "derive_auto_restart_episode",
]
