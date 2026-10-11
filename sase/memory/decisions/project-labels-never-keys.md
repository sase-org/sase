---
keyword: Projects Are Shown By Name, Never By Directory Key
aliases: [project display names, project key leak, project labels never keys]
summary:
  Project surfaces show PROJECT_NAME through the display snapshot; the directory key and
  spec filename are identity only, and long-lived processes revalidate at refresh
  boundaries.
metadata:
  status: accepted
  decided: 2026-10-11
---

**Claim.** A project's human-facing label is `PROJECT_NAME` through the display
snapshot. The directory key and the `*.sase` filename are storage identity only,
appearing at most as labeled identity fields in project-admin output and in
machine-readable (JSON) output. Long-lived processes revalidate at worker or tick
boundaries through a ProjectSpec stat token, and lookups stay memory-only. Labels never
come from paths.

**Why.** The `gh_bbugyi200__job` incident: the Agents tab showed the directory key for a
project whose spec declares `PROJECT_NAME: job`, because sase-89's in-process-only
invalidation missed cross-process creation and naming. Rejected alternatives: in-process
invalidation only (the status quo); per-lookup stat freshness (render-path I/O,
[[tui_perf.md]]); a cross-process generation pulse bumped by mutation funnels (misses
hand edits, other sase versions, and Rust-side writers); deriving a label from the
provider key format (`gh_owner__repo` → `repo`), which can disagree with the allocated
`PROJECT_NAME` such as `job_1` and would belong in sase-core under
[[rust-core-required]]; a stale-while-revalidate daemon thread in every process.

**Cost.** A stat sweep per tick in long-lived processes, plus a reload of about 1 ms
whenever any ProjectSpec changes, including RUNNING churn. Every long-lived consumer
must call the refresh. The static-guard allowlists need maintenance.

**Reopens when.** A non-Python frontend needs labels (then move the label and freshness
rules into sase-core), the sweep becomes measurable on the tick at high project counts,
or spec churn makes reloads costly enough to justify a content-scoped token.
