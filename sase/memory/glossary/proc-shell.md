---
keyword: Proc Shell
---

A proc shell is a named supervised proc belonging to a sase agent, with durable output
and lifecycle state. A family-attached proc shell (`shell_kind: "proc"`) is a sase
monitor and may carry timeout, workspace-claim, and follow-up policy. A gate shell's
execution-phase proc does not make it a proc shell: it stays `shell_kind: "gate"`
throughout, pending or executing.
