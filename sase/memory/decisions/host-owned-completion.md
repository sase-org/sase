---
keyword: Completion Is Host-Owned
aliases: [finalizer declaration, agents never commit]
summary:
  An agent never creates commits, branches, or PRs; it submits a declaration and
  host-owned finalizers act.
metadata:
  status: accepted
  decided: 2026-08-21
---

**Claim.** A turn completes when the host's selected finalizers are satisfied, not when
an agent says it is done. The agent submits one atomic, turn-bound declaration; bounded
providers execute and independently verify postconditions; refusal requires a reason and
normally fails the run. An agent never creates commits, branches, or PRs directly.

**Why.** Trusting an agent's word that work is done is neither verifiable nor
attributable — the whole point of the design is that host-owned selection pairs with
agent-supplied judgment only, never the reverse. Rejected alternatives:
provider-specific stop hooks, a hard-coded commit finalizer, arbitrary prompt-selected
executors, and trusting an executor's self-reported success — all of them let prompt
text or runtime quirks supply the executor, environment, or repository path, which is
exactly the trust boundary this decision closes.
`feat(finalizers)!: make pluggable finalizers the only completion path` (`2f9c4ae29`,
2026-08-21) made this the sole completion path; installing a finalizer-providing plugin
does not activate it.

**Cost.** Protocol and evidence complexity: the host must resolve a finalizer plan
before the turn, publish immutable context, and verify postconditions independently,
which is more machinery than "the agent ran `git commit`." The mechanical exemptions
(`/sase_plan`, `/sase_monitor`, `/sase_pipe`, `/sase_questions`) exist because they
terminate the runner before the success path — they are not violations of the rule, per
[[decisions/single-turn-agents]] and [[decisions/gates-never-block]].

**Reopens when.** After operational soak across enough real runs to know whether the
protocol's complexity is paying for itself; this decision is recent and explicitly
flagged for revisit rather than settled indefinitely.
