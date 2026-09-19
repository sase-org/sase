---
keyword: Check-Full Is Explicit-Only
aliases: [agents run check not check-full, landing does not run check-full]
summary:
  just check is the only agent-initiated verification recipe; just check-full runs only
  when explicitly instructed, typically to repair a CI failure.
metadata:
  status: accepted
  decided: 2026-09-19
---

**Claim.** `just check` is the only verification recipe a SASE agent runs unless the
current prompt, the user, or the assigned bead explicitly names `just check-full`. Epic
landers follow the same rule and therefore no longer author `%q(w=2.0)`. A `just check`
pass with a `just check-full` failure is a test-infrastructure bug, out of scope for the
current agent; file it through `/sase_new_task` and do not take it as remaining product
or landing work. `just check` may still escalate internally to the full test suite; that
is rare by design and is not the agent choosing `just check-full`.

**Why.** The host-capacity measurements in [[decisions/two-speed-verification]] still
hold: the full suite can consume a quarter to a half of the machine continuously. Using
that lane as a default landing gate also converts test-infrastructure failures (flake
baseline, test-cost budgets, full-lane-only flakes, screenshot drift) into blocking epic
work. CI already runs the exhaustive non-visual suite and a check-only visual job.
Rejected alternative: keep `just check-full` as the landing / broadening / unusual-
selection gate, and keep the lander's `%q(w=2.0)` resource claim so that gate can run
without stacking onto a fully loaded host — rejected because those triggers are not
explicit instruction, and once landers stop running that command the double-weight claim
has no remaining job.

**Cost.** A scoped false negative waits for CI rather than for the next lander. Flake
baseline, test-cost, and screenshot-update gates of `just check-full` are no longer an
agent default. Screenshot goldens that a change actually dirties are still the changing
agent's job via `just fix-tui-screenshots` when TUI output or snapshot coverage changed.

**Reopens when.** Selection-health shows the heuristic is materially wrong in practice,
or check-full-only CI failures become frequent enough that the detection lag is no
longer acceptable.
