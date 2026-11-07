---
keyword: Agent Hijack
aliases:
  - hijack
  - hijacked agent
summary: Stop a stalled agent turn while keeping its workspace held for recovery.
---

An Agent Hijack stops a running agent turn while retaining its workspace claim, agent
node, and recovery evidence. The turn settles as `hijacked` and appears as **⏏
HIJACKED** in the Stopped bucket; waiters stay parked while the workspace is held. The
user resolves the hijack exactly once by continuing in the same workspace (possibly with
a different model), starting over after a recovery snapshot, or dismissing after a
recovery snapshot. It never resumes the killed process. A hijack is distinct from a
kill, auto-restart, `sase agent hold`, `sase pipe`, and the `STALLED` wait label.
