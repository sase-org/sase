---
keyword: Agents Are Single-Turn
aliases: [single turn, one-turn agent]
summary:
  A SASE agent run is one provider turn; continuation is always mechanical, never a
  promise to resume.
metadata:
  status: accepted
  decided: 2026-08-15
---

**Claim.** A SASE agent run is exactly one provider turn. Work that outlives the turn is
continued by a mechanism that terminates the runner and starts a successor —
`sase monitor`, `/sase_pipe`, `/sase_plan`, `/sase_questions` — never by the agent
waiting, sleeping, or scheduling its own wake-up.

**Why.** Every hosted agent runtime ships background-execution and scheduling
primitives, and every one of them silently no-ops here: the runner captures the turn and
exits, so there is no process left to resume into. A rule stated without this mechanism
reads as arbitrary and is the first thing an agent rationalizes away when its native
tool "would obviously work." Rejected alternatives: an agent polling or sleeping in
place, native scheduler/cron features, and long-lived daemon agents — all of them assume
a process survives past the turn, which SASE's execution model does not provide.
`feat(cli)!: make run detached-only` (`b20637f4f`, 2026-07-02) and its reversal
`feat(cli)!: retire detached proc mode` (`ac5d95810`, 2026-08-15) show the model being
tested against a real alternative and settling here.

**Cost.** Every durable wait must go through mechanical infrastructure — a monitor, a
family pipe, a plan or questions handoff — instead of the agent simply continuing to
exist. That infrastructure has to exist and stay reliable for every kind of wait an
agent needs. A successful turn still ends through [[decisions/host-owned-completion]].

**Reopens when.** A hosting platform ships a true suspend/resume primitive that
preserves workspace claims and provider budget across the pause, per
[[decisions/gates-never-block]]. No such primitive exists today.
