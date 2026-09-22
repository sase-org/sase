"""The models package keeps the legacy single-module public surface."""

from __future__ import annotations

import sase.procs.models as models


def test_models_all_matches_legacy_surface() -> None:
    assert models.__all__ == [
        "ACTIVE_PROC_STATUSES",
        "COMMAND_PROC_KIND",
        "DETACHED_PROC_KIND",
        "PROC_KINDS",
        "PROC_LIFECYCLE_LEGACY",
        "PROC_LIFECYCLE_PROC_SHELL",
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
