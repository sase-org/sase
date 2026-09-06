---
keyword: CI Is Two-Speed
aliases: [Master Gate vs Full CI, two-speed CI, release gate split]
summary:
  Master pushes run a per-SHA fast gate, while the exhaustive CI matrix runs off the
  push path on a schedule and remains a release prerequisite through ci_watch freshness
  checks.
metadata:
  status: accepted
  decided: 2026-08-28
---

**Claim.** CI is no longer the thing that runs everything on every push. A push to
`master` runs `Master Gate` (`.github/workflows/master-gate.yml`): a per-SHA,
never-cancelled fast gate with the lint gate and eight deterministic shards of the whole
non-visual fast suite. The exhaustive lane moved to `Full CI`
(`.github/workflows/full.yml`), a scheduled caller of `ci.yml` that runs every two hours
off the push path. `ci_watch` gates release on both signals: `gating_workflows` proves
this commit's fast gate is green, and `heavy_max_age_hours` requires a recent green
`Full CI` run.

**Why.** [[decisions/two-speed-verification]] established that verification is two-speed
because host capacity, not test speed alone, is the constraint. Epic sase-um applies
that same rule to CI. The measured alternatives all either failed to produce an
attributable per-SHA signal or consumed the account's capacity without reliably settling
the tip: `queue: max` on the master group, per-SHA concurrency on the full `ci.yml`,
deleting the master concurrency block, `cancel-in-progress: true`, a GitHub merge queue,
larger or self-hosted runners, verifying every Nth commit, and a diff-scoped selector in
CI. Backtesting showed measurable master commits escalating to the full suite, and
`tests/test_github_actions_ci_workflow.py` deliberately forbids CI workflows from
running the scoped local lane.

**Cost.** A regression only the heavy lane can catch may be learned up to two hours
after the responsible push, and heavy-lane failures do not page through `ci_watch` while
the tip they attach to is unsettled. The project accepts that lag to keep every master
SHA attributable and to keep the exhaustive lane from blocking the push path.

**Reopens when.** The fast gate's p50 wall time stops fitting the commit cadence, or the
heavy lane catches regressions the gate misses often enough that a two-hour detection
lag is no longer acceptable.
