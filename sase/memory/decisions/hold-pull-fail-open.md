---
keyword: Hold Admission Uses Pull Evaluation With Fail-Open TTL
aliases: [pull hold evaluation, fail-open hold store, hold TTL default]
summary:
  Holds are one durable record per armer evaluated by each candidate at admission
  (pull), with optional TTL (default 2h, cap 12h), fail-open store reads, and release
  scoped to the armer session or shell end.
metadata:
  status: accepted
  decided: 2026-09-26
---

**Claim.** An agent hold is one durable record per armer, evaluated by each candidate at
the admission boundaries it already passes through (pull), never by writing a blocking
dependency into another launch's marker. `ttl=` is optional with a bounded default
(`agent_hold_default_ttl`, `2h`) and a hard cap (`agent_hold_max_ttl`, `12h`). A broken
or unreadable hold store fails open: admission ignores it rather than stranding a
waiter. A hold releases on explicit release, when the armer's session settles (agent
armer) or shell exits, or at TTL expiry — and a settled armer's `future` rule expires
with its record, never blocking later arrivals vacuously. Running work is immune by
construction, since both enforcement points (runner-slot admission for agents,
eligibility transition for undispatched procs) are pre-run. Directive summary in
[[xprompts.md]]; full contract in `docs/xprompt.md` and `plan:202609/hold_directive.md`.

**Why.** Prompt text is replayed (`#fork`, history, pipes), so a barrier written into
another launch's `waiting.json`/`ready.json` would outlive its armer and misfire on
replay; one record per armer evaluated at admission keeps "running work is never
affected" true by construction. A hold is a scheduling courtesy, not a correctness
invariant, so the wrong failure mode is a frozen host, never an early release. Rejected
alternatives: **push model** (writing blockers into other launches' markers) couples
every launch's liveness to the armer's with no durable recovery path; **fail-closed
store** (refusing admission when the store is unreadable) turns a scheduling aid into a
host-wide freeze on exactly the corrupted-state days it must survive; **TTL-mandatory
authoring** (rejecting a hold without an explicit `ttl=`) adds friction the bounded
default already covers, since no hold can outlive the cap either way.

**Cost.** A hold whose store entry is lost releases early instead of holding; callers
that need a guarantee must re-arm and re-check rather than rely on the barrier. Liveness
pruning means a dead armer's hold disappears even if its work logically continues
elsewhere.

**Reopens when.** Holds are used as a correctness invariant rather than a scheduling
courtesy — for example, mutual-exclusion around a non-idempotent migration — with
evidence that early release caused real harm; that case needs a fenced primitive with
durable fencing, not a longer TTL on this one.
