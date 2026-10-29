"""Bounded execution of the configured after-rebase gate hook.

Phase ``gate-runner`` of the rebased-stitch gate epic: take a pending gate
context, load project-scoped configuration for its explicit repository,
launch the configured command with one hard monotonic deadline, and classify
the collected facts through the shared Rust policy facade
(:mod:`sase.core.rebase_gate`).

Contract (owned by Rust; this module only supplies IO facts):

- Disabled or invalid gate settings never launch a process. An empty
  ``commit_hooks.after_rebase`` command returns the facade's ``skip`` verdict.
- The command runs with repository-root cwd and two environment variables:
  ``SASE_REBASE_CONTEXT`` names a temporary JSON input file holding the
  pending context, and ``SASE_REBASE_RESULT`` names the fresh result file the
  checker writes. Changed paths are never interpolated into shell text.
- One monotonic wall-clock budget covers context preparation, command
  execution, teardown, and result reads. The group is terminated on timeout
  and killed after a short bounded grace period, then reaped; drain threads
  join with a bounded wait so a descendant holding a pipe open cannot hang
  the finalizer.
- Every gate error fails open: timeout, signal, spawn failure, unsupported
  exits, malformed/missing/stale reports, invalid config, explicit ``error``
  reports, and observability/cleanup failures produce a visible warning and
  allow the push. Only a valid matching ``findings`` report blocks it.
- Cancellation of the overall stitch stays cancellation: ``KeyboardInterrupt``
  and task cancellation terminate the subprocess group best-effort and are
  re-raised, never converted into permission to push.

Python builds a ``warn`` decision directly only for inputs the Rust wire
types cannot represent (a non-string hook command, an unusable timeout, an
unloadable config layer) or when the facade itself raises. Every verdict
that depends on execution evidence comes from the facade.

This module never wires publication or dispatch and never enables the repo
hook; it only executes one gate context on demand.
"""

from __future__ import annotations

from sase.workflows.commit._rebase_gate_common import (
    GATE_PHASE_LABEL as GATE_PHASE_LABEL,
    REBASE_GATE_CONTEXT_ENV as REBASE_GATE_CONTEXT_ENV,
    REBASE_GATE_RESULT_ENV as REBASE_GATE_RESULT_ENV,
    RebaseGateOutcome as RebaseGateOutcome,
)
from sase.workflows.commit.rebase_gate_execution import (
    GateStepState as GateStepState,
)
from sase.workflows.commit.rebase_gate_settings import (
    GateSettings as GateSettings,
    load_after_rebase_gate_settings as load_after_rebase_gate_settings,
    run_after_rebase_gate as run_after_rebase_gate,
)

__all__ = [
    "GATE_PHASE_LABEL",
    "REBASE_GATE_CONTEXT_ENV",
    "REBASE_GATE_RESULT_ENV",
    "RebaseGateOutcome",
    "run_after_rebase_gate",
]
