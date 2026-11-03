---
keyword: Handoffs End Through Host Completion
aliases:
  - staged handoffs
  - host-adopted handoffs
  - no kill-path handoff
summary:
  A turn-ending handoff is staged, the turn completes through host completion, and the
  host then adopts the handoff.
metadata:
  status: accepted
  decided: 2026-11-03
---

**Claim.** A turn-ending handoff (`sase plan propose`, `sase questions`, `sase pipe`,
`sase gate create`, `sase sudo request`, `sase launch request`, `sase monitor start`,
and agent-side workflow HITL) is staged while the agent is still alive. Every root turn
then completes through `/sase_final` and host-owned finalizers. Only after those
finalizers settle does a fixed host-owned epilogue adopt the staged handoff. The agent
never waits on its own staged work. This partly supersedes the kill-era clauses of
[[decisions/gates-never-block]], [[decisions/single-turn-agents]], and
[[decisions/host-owned-completion]]: the no-blocking, single-turn, and host-ownership
principles stay.

**Why.** The kill-era path wrote a marker and terminated the runner before finalizers
ran, so any edit made before the handoff was never committed. That already lost work
(lander plan-status edits, a sase-core fix that a lander declined to propose a successor
for so its edits would commit). Rejected alternatives: keep the kill and add a pre-kill
commit (two completion paths, and a later finalizer dirtying the tree still races
adoption), and treat the handoff itself as a finalizer (`%final:none` could remove it,
retries could repeat it). Staging plus a post-finalizer epilogue reuses
[[decisions/host-owned-completion]] for repository decisions and keeps continuation
mechanical per [[decisions/single-turn-agents]] and [[decisions/gates-never-block]].

**Cost.** One extra step on every handoff turn: stage, then declare, then stop. The
agent must not wait on its own staged work, and adoption is fail-closed — a failed
finalizer holds the handoff instead of activating it. Same-workspace handoffs may carry
unfinished work; tale plans still commit or file a typed deferral.

**Reopens when.** A hosting platform ships a true suspend/resume primitive that
preserves workspace claims and provider budget across a pause, per
[[decisions/single-turn-agents]] — no such primitive exists today.
