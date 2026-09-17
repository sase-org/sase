---
keyword: Expensive Commands Are Recorded Before They Are Admitted
aliases:
  - record before admit
  - record first, admit last
  - ToolRun ledger first
summary:
  The sase tool control plane lands its ToolRun record first; prediction and admission
  only ever consume a corpus that already exists.
---

**Claim.** An expensive command becomes a named tool whose every run is durably recorded
— fingerprint, per-stage timings, host load samples — before anything predicts its
duration or prices its admission. The ToolRun ledger lands first, in a new per-machine
Rust-owned store with its own retention; prediction consumes the corpus only after weeks
of samples and stays advisory until backtested; admission consumes calibrated
prediction, never guesses. A ToolRun is a semantic record that delegates execution to an
existing executor (inline child, monitor, durable proc): recording adds no new
supervisor, and recording stays fail-open even where admission later becomes
fail-closed.

**Why.** Load samples cannot be backfilled — the tree records none today — so every
unrecorded week delays calibration by a week, while a record pays for itself even if no
consumer ever ships. This applies [[decisions/corpus-before-mechanism]] to execution
machinery. Rejected alternatives: **admission-first** (epic `sase-zm`, closed superseded
2026-09-17) priced and queued work before any evidence of what work costs — 14 phases,
zero closed, nothing landed — and the measured waste points the other way: on apollo
over 14 days, 37.2 h of repeated verification commands and 16.24 h of `check-full` runs
re-discovering one month-old known-red master (waste that records — triage, receipts —
attack and a queue does not), with zero concurrent-duplicate request fingerprints for
admission to prevent. **Recognition-by-profile** — inferring cost by matching argv
patterns instead of naming tools — leaves no stable identity for fingerprints, receipts,
or quantiles, and opt-in recognition measurably goes unused (`verify` profile on 1 of 69
monitors, prepared host completion on 0 of 69). **Reusing the proc store** fails on
retention: `procs.history_limit: 100` would destroy the corpus in days, and the
telemetry store keeps only aggregates. Evidence and epic decomposition:
`research:202609/sase_tool_epic_roadmap/sase_tool_epic_roadmap.md`.

**Cost.** A new per-machine durable store and a new disk-retention class registered with
`sase disk`; recording ships well before anything user-visible consumes it; and adoption
is instruction-led (guidance plus the wrapper — provider hooks are gone), so bypass is
measured, not enforced. The commands being recorded are the same expensive verification
runs that [[decisions/two-speed-verification]] rations.

**Reopens when.** The ledger itself measures a concurrent-duplicate or queue-starvation
rate that recording, triage, and receipts do not mitigate — evidence that admission or
single-flight joining must move earlier than calibrated prediction allows.
