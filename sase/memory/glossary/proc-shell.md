---
keyword: Proc Shell
---

A proc shell is a named supervised proc (`shell_kind: "proc"`) with durable output and
lifecycle state. It is either **session-attached**, meaning a sase monitor that belongs
to the agent session that started it and may carry timeout, workspace-claim, and
follow-up policy, or **stand-alone**, meaning a beta `%proc` launch unit dispatched with
origin `xprompt-proc`. A stand-alone proc shell belongs to no agent or session,
allocates no agent runner, and appears in the Agents tab as its own row kind, counted
separately from agents. A gate shell's execution-phase proc does not make it a proc
shell: it stays `shell_kind: "gate"` throughout, pending or executing.
