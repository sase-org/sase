---
keyword: A Gate Never Blocks An Agent
aliases: [gates never block, gate shells, blocking gate wait]
summary:
  Creating a gate from inside an agent ends that agent's turn; continuation is a gate
  shell's follow-up, never a wait.
metadata:
  status: accepted
  decided: 2026-08-27
---

**Claim.** A gate an agent creates becomes a gate shell: a named, non-LLM member of that
agent's family that publishes the decision, outlives its creator, runs the commands the
reviewer selects, and hands their typed outcome to the next family member. Creating a
shell gate hands off and kills the creating agent's turn immediately after the
descriptor prints; continuation is always the gate shell's recorded follow-up, never the
creator waiting, polling, or blocking on a response.

**Why.** Blocking held the creator's process, its workspace claim, and — for plans — its
runner slot for as long as a human took to decide, and the failure mode was not
hypothetical: the `bob-cli-15.2` bead notes record a confirmation gate that stayed
pending because `cancel_gate` blocked on `.response.lock` behind an approved
long-running command, and a second gate that timed out with no selected option, leaving
the phase unclosed and forcing a later agent to re-derive the state from scratch. The
rejected alternative — keep blocking and make the wait more robust (a bounded lock, a
smarter timeout) — only shrinks the blocking window; it does not remove the structural
cost of an agent process, claim, and runner slot sitting idle for a human-scale
decision. Killing the creator and resuming through an ordinary family follow-up removes
that cost entirely and reuses the same handoff machinery `sase monitor` and `/sase_pipe`
already rely on, rather than inventing a fourth continuation mechanism. A successful
turn still completes through [[decisions/host-owned-completion]].

**Cost.** One extra family row (the gate shell) and one extra process start per decision
— the same cost a monitor follow-up already pays today, not a new category of expense.
`%auto`-resolved gates still cost exactly one agent, because creation always makes the
gate shell but only hands off if the gate is still pending once creation returns.

**Reopens when.** A hosting platform ships a true suspend/resume primitive that
preserves workspace claims and provider budget across a pause, per
![[decisions/single-turn-agents]] — no such primitive exists today, so blocking is not a
live alternative to reopen this decision toward.
