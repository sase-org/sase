"""Typed Python records for the Rust proc wire."""

from sase.procs.service_meta import ProcServiceBlock

from .common import (
    ACTIVE_PROC_STATUSES,
    ARTIFACTS_LOG_OWNER,
    COMMAND_PROC_KIND,
    DETACHED_PROC_KIND,
    PROC_KINDS,
    PROC_LIFECYCLE_LEGACY,
    PROC_LIFECYCLE_PROC_SHELL,
    PROC_WIRE_SCHEMA_VERSION,
    STORE_LOG_OWNER,
    SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS,
    TERMINAL_PROC_STATUSES,
    TUI_PROC_KIND,
    XPROMPT_PROC_ORIGIN,
)
from .operations import (
    UNSET,
    ProcFinish,
    ProcReserve,
    ProcReserveOutcome,
    ProcSettlement,
    ProcStopRequest,
    ProcSupervisorClaim,
    ProcUpdate,
    ProcUpdateOutcome,
)
from .proc import Proc
from .retention import (
    ProcLogRetentionEntry,
    ProcLogRetentionResult,
    ProcPruneOutcome,
    ProcPrunedStateRetention,
)
from .snapshots import ProcAppendOutcome, ProcStoreSnapshot, ProcStoreStats

__all__ = [
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
