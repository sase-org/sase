"""Shared public helpers for the after-rebase gate runner split.

This is an already-private (``_``-prefixed) module, so the public names it
defines are implementation details of the runner package, not new public API.
Both the settings and execution legs import these without touching any
``_``-prefixed name across modules.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from sase.core.rebase_gate import (
    REBASE_GATE_WIRE_SCHEMA_VERSION,
    DecisionWire,
)
from sase.output import print_status
from sase.workflows.commit.hook_utils import write_json_atomic

REBASE_GATE_CONTEXT_ENV = "SASE_REBASE_CONTEXT"
REBASE_GATE_RESULT_ENV = "SASE_REBASE_RESULT"

GATE_PHASE_LABEL = "after_rebase"


@dataclass(frozen=True)
class RebaseGateOutcome:
    """One executed gate attempt: the facade verdict plus evidence."""

    decision: DecisionWire
    duration_seconds: float
    metadata_path: Path | None
    stdout_tail: str
    stderr_tail: str


def warn_decision(reason: str, diagnostics: str | None) -> DecisionWire:
    """Build a fail-open warning for inputs the wire cannot represent."""
    return {
        "schema_version": REBASE_GATE_WIRE_SCHEMA_VERSION,
        "verdict": "warn",
        "reason": reason,
        "findings": [],
        "diagnostics": diagnostics,
    }


def warn_without_evidence(
    started: float,
    reason: str,
    diagnostics: str | None,
) -> RebaseGateOutcome:
    """Fail open before any evidence directory exists."""
    decision = warn_decision(reason, diagnostics)
    print_status(f"Rebase gate: {reason}.", "warning")
    if diagnostics:
        print_status(f"Rebase gate detail: {diagnostics}", "warning")
    return RebaseGateOutcome(
        decision=decision,
        duration_seconds=time.monotonic() - started,
        metadata_path=None,
        stdout_tail="",
        stderr_tail="",
    )


def write_json_best_effort(path: Path, payload: dict[str, object]) -> None:
    """Write evidence JSON; observability failures never raise."""
    try:
        write_json_atomic(path, payload)
    except OSError:
        pass
