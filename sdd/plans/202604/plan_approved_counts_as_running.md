---
create_time: 2026-04-27 09:27:25
status: done
prompt: sdd/prompts/202604/plan_approved_counts_as_running.md
---
# Plan: count `PLAN APPROVED` agents as running in banner summary

## Problem

In the `sase ace` Agents tab, the group banner summary shows e.g.:

```
▶ Running ━━━━━━━━━  4 agents · 3 running · 1 awaiting
│  sase (RUNNING) ×4 @ar
│  sase (RUNNING) ×4 @aq
│  sase (RUNNING) ×4 @h
│  sase (PLAN APPROVED) ×6 @m.claude.plan
```

All four agents are listed under the **Running** group banner, but the chip-counts say `3 running · 1 awaiting`. The
`PLAN APPROVED` agent is being miscounted as _awaiting_ even though the bucketing logic and the docstring explicitly
classify it as a running/active state.

## Root cause

Two classifications coexist in `src/sase/ace/tui/models/agent_groups.py`, and they disagree about `PLAN APPROVED`:

1. **Bucketing** (source of truth — drives which group banner an agent appears under). `_status_bucket_for()` at line
   142 has an explicit branch:

   ```python
   if status == "PLAN APPROVED":
       return "Running"
   ```

   The accompanying comment (lines 103–107) states:

   > `PLAN APPROVED` is an actively executing state and reads as **Running**.

2. **Chip summary** (the `N agents · X running · Y failed · Z awaiting` line). `compute_banner_summary()` at line 582
   uses an independent set:
   ```python
   _AWAITING_STATUSES = frozenset({"QUESTION", "PLAN APPROVED"})
   ```
   It only increments `running` when `status == "RUNNING"` (literal match), so `PLAN APPROVED` never counts as running
   and instead falls through to the awaiting branch.

The two should not have diverged — the chip line is meant to summarize the same agents the banner groups together.

## Fix

Make the chip summary derive its counts from the same bucketing function the rest of the file uses, so the chip line can
never disagree with the banner it sits on.

Concretely, in `src/sase/ace/tui/models/agent_groups.py`:

- Drop the standalone `_AWAITING_STATUSES` constant.
- Rewrite `compute_banner_summary()` to call `_status_bucket_for(agent)` per agent and tally:
  - `running` ← bucket == `"Running"` (now naturally includes `PLAN APPROVED`)
  - `failed` ← bucket == `"Failed"` (existing `startswith("FAILED")` + retry handling already lives in
    `_status_bucket_for`, so this also fixes the subtle case where an unretried `FAILED` agent — currently bucketed
    `Needs Attention` — is _also_ counted in the `failed` chip; bucket-driven counts make the chip match the banner)
  - `awaiting` ← bucket == `"Needs Attention"` (covers `QUESTION` and `PLANNING`; the latter was previously not counted
    at all, which is itself a small bug — this fix also closes that gap)
  - everything else (`Done`, `Waiting`) → uncounted, same as today

`Workflow children are still skipped` (existing `agent.is_workflow_child` short-circuit stays).

## Tests

Update `tests/ace/tui/models/test_agent_groups_folds.py`:

- Add a regression test: a group containing one `RUNNING` and one `PLAN APPROVED` agent yields `running == 2`,
  `awaiting == 0`.
- Existing `test_compute_banner_summary_counts_running_failed_awaiting` (RUNNING + FAILED + QUESTION + DONE) keeps the
  same expected counts under the new implementation, since:
  - `RUNNING` → Running bucket
  - `FAILED` (no retry) → Needs Attention bucket per `_status_bucket_for`. **This changes the existing test's
    expectation** — under the new bucket-driven counts this `FAILED` agent counts as `awaiting`, not `failed`. Update
    the test to use `FAILED (RETRIED)` (with `retried_as_timestamp` set) when it wants the `failed` chip, matching how
    the banner labels work in practice.
- `test_banner_summary_text_handles_failed_retried_status` keeps working but should be tightened: only the
  `FAILED (RETRIED)` agent counts toward `failed`; the bare `FAILED` (no retry lineage) counts toward `awaiting`. This
  test currently asserts `summary.failed == 2` for two FAILED variants — that assertion needs to be split.

## Out of scope

- The `_NEEDS_INPUT_STATUSES` set used by query filters (separate concern, different semantics — it intentionally
  considers `PLAN APPROVED` a "needs input" state for the `:waiting` filter).
- Docstring on lines 103–107 already states the desired behavior; no doc edits required.
- Bucket ordering, banner labels, fold registry — all unchanged.

## Files touched

- `src/sase/ace/tui/models/agent_groups.py` (compute_banner_summary + remove `_AWAITING_STATUSES`)
- `tests/ace/tui/models/test_agent_groups_folds.py` (one new test, two existing tests adjusted)

## Validation

- `just check` (lint + mypy + tests).
- Manual: run `sase ace`, confirm a group containing a `PLAN APPROVED` agent shows `N running` only, no `awaiting` chip
  (assuming no `QUESTION`/`PLANNING` agents in the group).
