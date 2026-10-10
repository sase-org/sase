"""The models package keeps the legacy single-module public surface."""

from __future__ import annotations

import sase.procs.models as models


def test_models_all_matches_legacy_surface() -> None:
    assert models.__all__ == [
        "ACTIVE_PROC_STATUSES",
        "COMMAND_PROC_KIND",
        "DETACHED_PROC_KIND",
        "LEGACY_PROC_LIFECYCLE_PROC_SHELL",
        "PROC_KINDS",
        "PROC_LIFECYCLE_LEGACY",
        "PROC_LIFECYCLE_NAMED_PROC",
        "PROC_WIRE_SCHEMA_VERSION",
        "STORE_LOG_OWNER",
        "SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS",
        "TERMINAL_PROC_STATUSES",
        "TUI_PROC_KIND",
        "UNSET",
        "Proc",
        "ProcAppendOutcome",
        "ProcFinish",
        "ProcLogRetentionEntry",
        "ProcLogRetentionResult",
        "ProcObservedSettlementOutcome",
        "ProcPruneOutcome",
        "ProcPrunedStateRetention",
        "ProcReserve",
        "ProcReserveOutcome",
        "ProcServiceBlock",
        "ProcSettlement",
        "ProcStopRequest",
        "ProcStoreSnapshot",
        "ProcStoreStats",
        "ProcSupervisorClaim",
        "ProcUpdate",
        "ProcUpdateOutcome",
    ]


def test_models_names_resolve_to_single_definitions() -> None:
    from sase.procs.models.operations import UNSET as operations_unset
    from sase.procs.models.proc import Proc as proc_module_proc

    assert models.Proc is proc_module_proc
    assert models.UNSET is operations_unset
    for name in models.__all__:
        assert getattr(models, name) is not None


def test_observed_settlement_outcome_round_trip_and_known_result() -> None:
    from sase.procs.models import ProcObservedSettlementOutcome, ProcSettlement

    success = ProcObservedSettlementOutcome.from_dict(
        {
            "status": "success",
            "termination_reason": "success",
            "command_ended_at": "2026-10-10T12:12:19Z",
            "exit_code": 0,
            "message": "completed successfully",
        }
    )
    assert success is not None
    assert success.is_known_command_result()
    assert success.to_dict()["command_ended_at"] == "2026-10-10T12:12:19Z"

    loss = ProcObservedSettlementOutcome.from_dict(
        {
            "status": "error",
            "termination_reason": "supervisor-loss",
            "command_ended_at": "2026-10-10T12:12:30Z",
            "exit_code": 0,
        }
    )
    assert loss is not None
    assert not loss.is_known_command_result()
    reboot = ProcObservedSettlementOutcome.from_dict(
        {
            "status": "error",
            "termination_reason": "reboot",
            "command_ended_at": "2026-10-10T12:12:30Z",
        }
    )
    assert reboot is not None
    assert not reboot.is_known_command_result()
    assert ProcObservedSettlementOutcome.from_dict({"status": "success"}) is None

    settlement = ProcSettlement.from_dict(
        {
            "proc_id": "abc",
            "supervisor_id": "sup",
            "settling_at": "2026-10-10T12:12:19Z",
            "exit_code": 0,
            "message": "done",
            "outcome": success.to_dict(),
        }
    )
    assert settlement.outcome is not None
    assert settlement.outcome.termination_reason == "success"
    legacy = ProcSettlement.from_dict(
        {
            "proc_id": "abc",
            "supervisor_id": "sup",
            "settling_at": "2026-10-10T12:12:19Z",
        }
    )
    assert legacy.outcome is None
    assert legacy.sidecar is None
