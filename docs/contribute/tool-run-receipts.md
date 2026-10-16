---
title: Tool run receipts
description: Internal receipt policy and verification details for recorded tool runs.
---

# Tool run receipts

This page records internal receipt policy and verification details for tool runs.

## Fingerprinted toolchain and external state (E4 hermetic-baseline)

`check` and `check-full` version-probe every lint toolchain they run: `python`, `just`,
`sase-core-rs`, plus `ruff`, `mypy`, `symvision`, and `prettier`. Each probe runs in at
most 1 s and all probes share a 2 s budget; an unavailable or failing probe makes the
fingerprint explicitly incomplete instead of yielding an old-looking successful
identity, and a changed lint-tool version moves the fingerprint digest so an old receipt
can never cover a new toolchain. This does not fix install provenance (`sase-vr` still
tracks that ruff/mypy resolve by install date rather than `uv.lock`): the probes capture
the drift instead of preventing it.

Bead and feature-flag state read by lint stages (`_lint-flags`, symvision
`--epic-symbol`) is external state and is deliberately not fingerprinted: digesting it
would invalidate every receipt on any unrelated bead close. Receipts built on `check`
fingerprints therefore carry a conservative time-to-live of at most 2 h, and receipt
lookup refuses expired coverage. A bead change inside that window that flips a lint
verdict is an explicit limitation of the receipt, not proof of coverage; the next
`check` re-observes and mints again.

## Receipt catalog policy and mixed-core rollout (E4 core-pin-catalog)

Only `check` declares an opt-in `receipt:` policy (`accept: [pass, no_new_failures]`,
`ttl: 2h`); `check-full`, `install-venv`, and ad-hoc runs stay receipt-less. The policy
is normalized by the Rust core but excluded from the definition digest, so editing it
never moves historical duration or corpus identity, while adding toolchain probes or
fingerprint inputs still moves the digest once, as intended. The beta `tool_receipts`
flag was removed at E4 landing: the policy is now always exposed on the loaded
definition and the flag-off branch is deleted.

Mixed installed cores fail closed with a clear diagnostic, never with a stale identity.
The pinned source revision (`sase-core-revision.txt`) is the receipt-capable core, and
dev installs build the extension from that checkout, so `just install-venv` heals a
stale wheel. A published `sase-core-rs` older than the receipt wire rejects the
`receipt:` key as an unknown catalog field (`sase tool run` exits 2 naming the entry),
and Python code calling the receipt bindings fails the "Check pinned core bindings" lint
step instead of crashing with `AttributeError` at runtime. Apollo and unconfigured-mac
machines stay on the pass-only path until their ledgers grow enough for an independent
KNOWN precision gate; no receipt is shared across machines.

## Verdict receipts: mint, query, and no-skip (E4 receipt-execution-cli)

After wrapper settlement and E3 triage settlement, both the foreground and the claimed
hand-off worker paths settle a verdict receipt through the same Rust mint API: mint only
for a named, non-bypassed run whose before/after fingerprints are complete and equal,
with `mutated_input = false`, `settled_by = wrapper`, and a verdict in that tool's
`receipt.accept` set. Ad-hoc, bypassed, mutated, incomplete, non-wrapper-settled,
control, infrastructure, environment, NEW, undetermined, and unaccepted no-new runs
leave no receipt row. A later same-identity, same-fingerprint non-success supersedes an
earlier receipt until a later eligible success. The settle adapter is fail open for tool
execution (it records a diagnostic and never changes the child's result); receipt lookup
stays fail closed.

`sase tool receipt TOOL [-a/--accept {pass,no-new}] [-j/--json]` reports the covering
receipt for one named tool at the current fingerprint: exit 0 for covered (receipt id,
source run id, verdict, age), 1 for exactly one typed refusal (`no_receipt`,
`fingerprint_changed: <path>` with bounded changed paths, `expired`,
`incomplete_fingerprint`, `verdict_insufficient`, `definition_changed`, or
`invalidated_by_later_run`), and 2 for an unknown tool or usage error. `-j` emits a
versioned (`schema_version: 1`) machine-readable envelope. The query states what the
ledger holds and never claims any completion policy is met.

Every `sase tool run` invokes its child despite an existing receipt. A covering receipt
is proof for host completion to consult; it never skips, reuses, or redirects execution.

## Receipt opportunity report (E4 opportunity-report)

`sase tool receipts [-d/--days N] [-j/--json]` lists retained receipts and reports
content-equivalent verification repeats: counts, summed duration and hours, top tools,
and the observation window, all versioned (`schema_version: 1`). The comparison is
content-addressed — path content at each HEAD plus dirty/untracked hashes, with
toolchain, environment, extra arguments, and catalog identity kept in the key, comparing
Git blobs by content rather than by HEAD alone — so a verified dirty tree later
committed and rechecked at a new HEAD counts as a repeat opportunity. Missing Git
objects and incomplete fingerprints are reported as uncomparable, never guessed. The
report informs a later reuse decision; it never changes what `run` executes and never
claims the current tree is covered.

## Measuring adoption

```bash
tools/tool_adoption_report -d 7 -j
```

The read-only report pairs each agent's normalized LLM tool-call records (per file, by
`tool_use_id`), classifies heavy (>=20 s) `just check` / `just check-full` invocations
as wrapped in `sase tool run`, raw, or bypassed (`SASE_TOOL_BYPASS=... just check`), and
reports count and wall-time shares with their denominators. It also counts refusals: an
exit-2 raw call carrying the guard marker, followed by a wrapped call. Each call is
filtered by its own timestamp rather than its file's modification time, so a window
cannot mix in older calls. Unpaired, negative, over-six-hour, truncated, undated, and
ambiguous (pipelines, multi-command) records are counted, not guessed. It does not read
the ToolRun ledger, so ledger counts and recording errors are separate coverage signals.

## Stats

`sase tool stats [-a/--all] [-d/--days N] [-j/--json] [-t/--tool TOOL]` turns the ledger
into routine readouts: per tool, stage, route, and provider p50/p90, the outcome and
censoring mix, ceiling kills and wasted hours, repeats and duplicates, a daily trend, a
chronological backtest, and host pressure. The default scope is the current catalog
project over 7 days; `-a` includes every project, `-t` filters to one tool and prints
its detail sections, and `-d` must be 1–180. Exit codes: 0 when reported (an empty
window prints `no recorded runs`), 1 on a store or binding failure, 2 on usage errors.
`-j` prints the core result plus a top-level `host`, sorted and indented with
`schema_version: 1`.

The report is read-only and machine-local: it reconciles unsettled runs first, then
opens the ledger without migrating or writing. Compare machines by running `stats` on
each host (`ssh <host> sase tool stats -j`), never by merging ledgers.

Definitions, in plain words:

- The **bare-settled cohort** is `succeeded`/`failed` runs with a known duration and no
  extra args. Percentiles use nearest rank; a missing value renders as an em dash, never
  as zero.
- **Routes** are `escalated` (a join record, or an inline-then-escalate run whose
  recorded ceiling budget is smaller than its duration), `detached` (a hand-off run with
  a starter), `handoff` (without a starter), `owned` (a foreground run inside a monitor
  or proc), and `inline` (everything else). `handoff + owned + escalated` is
  monitor-owned.
- A **ceiling kill** is an `inline`, `signaled` run by a named agent that died inside
  85%–100% (+60 s grace) of its recorded ceiling, or inside 530–550 s without recorded
  context (the legacy signature). A run with recorded context but no ceiling is never
  counted as a ceiling kill. **Waste** buckets are exclusive: killed at ceiling,
  timeout, stopped, lost, interrupted, then any other signal.
- **Repeats** are exact-state repetition: same project, tool, definition, extra args,
  and complete fingerprint, ordered by creation. A repeat after a signaled, interrupted,
  or lost run counts separately, as does a run that started before an earlier same-key
  run ended (a concurrent duplicate). The content-equivalent E4b measurement stays
  `sase tool receipts`.
- **Trend** buckets runs per local day, empty days included. The **backtest** is a
  baseline, not a forecaster: each in-window element with at least 20 earlier elements
  is checked against the p10–p90 band of the 60 most recent priors, and the report
  states coverage against the ≥80% target and median width against the ≤3× target.
  Conditioning on selection size or continuation mode belongs to the parked forecast
  work; this is the baseline such a forecast must beat.
- **Pressure** buckets host samples in 30 s windows and reports busy buckets (2+
  distinct runs), the share of buckets with memory PSI above 10, and p90 PSI and
  load-per-CPU. OOM kills are not observable from the ledger.

Stage detail reaches back over the `detail_days` retention horizon; older windows lose
stage rows while run summaries survive to `summary_days`.

Each held reconsider condition from the tool-routing research has a stats field:

| Condition  | Stats field                                                                                           |
| ---------- | ----------------------------------------------------------------------------------------------------- |
| Rest of E6 | Per-stage backtest coverage and width                                                                 |
| E7         | `pressure.busy_memory_over_threshold_share`, concurrent-duplicate hours, token-wait runs and timeouts |
| E8         | Run counts from each host (`ssh <host> sase tool stats -j`)                                           |
| E4b        | `sase tool receipts`, not this report                                                                 |

## Related

- [Named tools and ToolRuns](../reference/automation/tools.md)
