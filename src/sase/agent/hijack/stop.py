"""The ordered stop protocol for Agent Hijack (phase ``stop``).

Stopping a stalled agent without losing its work follows a fixed order:

1. **Eligibility.** Gather facts (row, meta, pid identity, claim, lifecycle
   phase, capability) and call the Rust eligibility function. A refusal
   returns exit 2 and changes nothing.
2. **Record and intent.** Exclusively create the ledger record (``requested``)
   and write the hijack-mode user-kill intent. Both exist before any signal.
3. **Pin.** Pin the workspace claim under the claim lock, recording the prior
   pin state. A mismatched or replaced claim aborts.
4. **Lost race.** If ``done.json`` already holds a real outcome, the record
   becomes ``finished_first``, the intent is removed, and the pin is restored
   only if this hijack set it.
5. **Stop.** The record moves to ``stopping`` and the verified terminator runs
   (process-identity checks, 6 s grace, then SIGKILL). No ``killpg`` shortcut.
6. **Survivors.** Any surviving process moves the record to ``stop_failed``,
   removes the intent, and restores the pin. The row stays RUNNING. Exit 1.
7. **Fallback.** When the runner died before settling, the orchestrator writes
   the same ``done.json`` the runner would have and re-asserts the pin.
8. **Evidence**, best-effort and off the TUI: per-repo diff stats, the last
   tool call and its age, the run duration, and stale ``index.lock`` files.
9. **Strict snapshot.** Every repo with changes is snapshotted. A failure is
   recorded but does not block ``held``; every later release must snapshot
   first.
10. **Publish.** The record moves to ``held`` and HIJACKED is published.

Only steps 1--7 run before the process tree is dead; evidence and snapshots
are deliberately last so they observe the final state.
"""

from __future__ import annotations

from sase.agent.hijack._stop_claim import STOP_GRACE_SECONDS
from sase.agent.hijack._stop_orchestrator import (
    HijackStopResult,
    STOP_INTENT_SOURCE,
    stop_agent_for_hijack,
)

__all__ = [
    "HijackStopResult",
    "STOP_GRACE_SECONDS",
    "STOP_INTENT_SOURCE",
    "stop_agent_for_hijack",
]
