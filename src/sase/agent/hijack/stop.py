"""The ordered stop protocol for Agent Hijack (phase ``stop``).

Stopping a stalled agent without losing its work follows a fixed order:

1. **Eligibility + target dedup.** Gather facts and call the Rust v2
   decision. The target key (``sha256(project_file::session-or-agent)``)
   reserves one active operation per target; a second request returns the
   active operation (same hijack id) instead of a second stop.
2. **Record and intent.** Exclusively create the ledger record (``requested``,
   with ``target_key`` and ``scope``) and write the hijack-mode user-kill
   intent. An intent that is not persisted aborts before any signal
   (``intent_write_failed``).
3. **Pin.** Pin the workspace claim under the claim lock, recording the prior
   pin state. A mismatched claim aborts; a ``begin_stop`` failure after the
   pin restores the prior pin state.
4. **Lost race.** If ``done.json`` already holds a real outcome, the record
   becomes ``finished_first``, the intent is removed, and the pin is restored
   only if this hijack set it.
5. **Stop.** The record moves to ``stopping`` and the verified terminator runs
   (pidfd signalling on Linux, identity checks, 6 s grace, then SIGKILL),
   retried a bounded number of times.
6. **Survivors.** Surviving writers move the record to ``stop_blocked``;
   custody and the pin stay until an explicit abandon. ``,k`` retries via
   ``retry_stop``; only ``abandon_stop`` (explicit ``x`` release) unpins.
7. **Fallback.** When the runner died before settling, the orchestrator writes
   the same ``done.json`` the runner would have and re-asserts the pin. The
   stale sweep reconciles abandoned requested/stopping records the same way.
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
