---
keyword: Explicit Handoff Fails Closed
aliases: [fail-closed explicit handoff, tool run -H fail closed]
summary:
  Explicit sase tool run -H fails closed when its ToolRun reservation cannot commit;
  foreground and monitor-start recording stay fail-open.
metadata:
  status: accepted
  decided: 2026-09-26
---

**Claim.** Explicit `sase tool run -H` is fail-closed: if the ToolRun reservation cannot
be committed, nothing starts and the command exits 1 naming the foreground form.
Foreground `sase tool run` stays fail-open, and a monitor start's reservation is
fail-open (the monitor id is already the durable handle, so it falls back to wrapped
execution with one reason line). Once a hand-off is accepted, later recording failures
(observe, sample, finish) stay fail-open and are reported as incomplete evidence, never
as a reason to replay. This narrows one clause of [[decisions/record-before-admit]]
("recording stays fail-open") for explicit hand-offs only, alongside
[[decisions/guarded-recipes]].

**Why.** The printed run id is the only handle a `-H` caller gets, so it must be durable
from the reservation on: starting work without a committed reservation would hand the
caller an id that names nothing discoverable, waitable, or stoppable. Rejected
alternative: **fail-open `-H`** (start anyway and report the reservation failure as a
warning) leaves the caller holding a receipt for a run the ledger cannot settle, which
is exactly the lost-acknowledgement state the durable hand-off was built to eliminate.
Decision 3 of `plan:202609/tool_e2_durable_handoff.md`; the rule is documented in
`docs/tool.md`.

**Cost.** A caller whose reservation cannot commit retries or falls back to the
foreground form; transient store outages refuse hand-offs instead of degrading to
untracked runs.

**Reopens when.** A separate durable handle exists for the hand-off (for example, an
owner id committed before the ToolRun reservation), so refusing to start no longer
protects the caller from an undurable receipt — with evidence, not speculation.
