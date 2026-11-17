---
keyword: Agent Hijack
aliases:
  - hijack
  - hijacked agent
summary: Stop a session's occupying turn while keeping its workspace held for recovery.
---

An Agent Hijack stops a session's occupying turn while retaining its numbered workspace
claim, agent node, and recovery evidence. `,k` on a member row, a session container, or
`sase agent hijack NAME` resolves to the occupant — the claim holder, else the newest
in-flight turn, else the earliest waiter — and names that member in the result. The turn
settles as `hijacked` and appears as **⏏ HIJACKED** in the Stopped bucket; waiters stay
parked while the workspace is held.

Immediate hijacks stop `RUNNING`/`STARTING`/`RETRYING` agent turns, running monitors
(through the monitor adapter), and `WAITING`/`QUEUED`/booting turns that hold a numbered
workspace. Finalizing turns, staged-but-unadopted handoffs, executing gates, and settled
monitors with a pending follow-up latch instead: the row shows **⏏ HIJACK PENDING ·
after \<boundary\>**, the owner keeps running, and the latch applies at the next safe
hand-off. `,k` on a pending row offers Cancel hijack, plus Hijack now once the force
bound passes; a latch mooted by clean completion holds nothing. Claimless waiters, gates
awaiting a decision, clan containers, remote rows, and already-hijacked rows redirect
(gate review, member select, remote command copy, recovery panel) or refuse with a code
and next action — never a generic toast.

The user resolves the hijack exactly once by continuing in the same workspace (possibly
with a different model), starting over after a recovery snapshot, or dismissing after a
recovery snapshot. It never resumes the killed process. A hijack is distinct from a
kill, auto-restart, `sase agent hold`, `sase pipe`, and the `STALLED` wait label.
