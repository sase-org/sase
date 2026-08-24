---
keyword: Verification Is Two-Speed
aliases: [check vs check-full, scoped tests]
summary:
  just check is the agent default and just check-full gates landing, because host
  capacity is the constraint, not test speed.
metadata:
  status: accepted
  decided: 2026-08-05
---

**Claim.** `just check` — every whole-repo lint gate plus a diff-scoped test lane
selected from a static import-graph closure — is the agent default. `just check-full` —
every gate plus the full suite — is reserved for landing, broadening changes, and CI,
and runs through a monitor rather than inline.

**Why.** The rule alone reads as a shortcut for impatient agents; the measurement is
what makes it non-negotiable. The host admits roughly 200–400 full-suite runs per day
against about 46,000 worker-minutes of gated capacity, at roughly 61 worker-minutes per
run — so the full suite alone can consume a quarter to a half of the machine's entire
capacity, continuously. Every downstream symptom (long gate waits, contention flakes)
follows from that one number. An agent that "just runs the full suite to be safe" is not
being careful; it is taking capacity from every sibling workspace. Rejected
alternatives: splitting the repository to shrink one suite, or adopting a build system
like Pants/Bazel immediately — both solve a different problem (build speed) than the one
actually measured (shared host capacity).

**Cost.** Scoped selection is a heuristic, not a proof: it can, in principle, miss a
test that a change actually affects. `tools/select_tests` and `tools/selection_health`
exist specifically to backstop and measure that risk.

**Reopens when.** Selection-health data shows the heuristic materially wrong in
practice, or the host's capacity constraints change enough that the tradeoff no longer
holds.
