---
keyword: Triage Annotates; It Never Changes an Exit Code
aliases: [triage annotates, triage exit code]
summary:
  KNOWN needs an independent witness; triage classifies failure evidence without
  changing command outcomes.
metadata:
  status: accepted
  decided: 2026-09-25
---

**Claim.** Failure triage annotates each failed [[glossary:tool-run]] with durable NEW,
KNOWN, FLAKY, or UNKNOWN items and a verdict, but never changes its exit code. KNOWN
requires an independent witness; insufficient evidence is UNKNOWN. Agent runs may
continue past stages containing only KNOWN or FLAKY items, but `run_silent --finish`
still returns the first continued failure's code.

**Why.** We rejected bead-mapping as KNOWN because ownership is only a suggestion, a
strict merge-base reference because ordinary master-red evidence would become too thin,
`rerun` chains because one-shot ToolRuns must remain independent records, and
always-continue because NEW and UNKNOWN failures must stop promptly. This preserves the
fail-fast exit contract while letting agents reach later scoped tests behind witnessed
master-red failures.

**Cost.** Continued runs can take longer, and thin ledgers are intentionally
UNKNOWN-heavy until independent witnesses accumulate. Extractors and their bounded
evidence must remain readable after raw-log retention expires.

**Reopens when.** Reconsider `rerun` if FLAKY-labeled items require more than about two
hours of manual re-runs per week, reconsider the CI evidence policy if UNKNOWN remains
above about 40% of items on a machine, or revisit the classification rule when a KNOWN
label is shown to lack an independent witness.
