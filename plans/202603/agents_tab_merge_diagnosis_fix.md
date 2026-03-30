---
create_time: 2026-03-30 16:55:08
status: done
---

# Plan: Diagnose and Fix Agent Entry Merging in `sase ace` Agents Tab

## Problem Statement

The Agents tab can incorrectly collapse two distinct agent runs into a single visible entry. The reported case involves:

- a manually launched agent run, and
- a chop-triggered `#sase/fix_just` run.

These should appear as separate rows but can be merged by deduplication logic.

## Root-Cause Hypothesis

The dedup pipeline currently uses timestamp-only matching in key places:

- `dedup_workflow_entries()` dedups `WORKFLOW` agents by `raw_suffix` (timestamp) only.
- `dedup_running_vs_workflow()` matches RUNNING `ace(run)` entries to WORKFLOW entries by `raw_suffix` only.

Timestamp strings are second-granularity (`YYmmdd_HHMMSS` / `YYYYmmddHHMMSS`), so independent launches in the same
second can collide. When collisions happen, timestamp-only matching can merge unrelated entries.

## Implementation Strategy

1. Tighten dedup identity for workflow entries.
   - Update `dedup_workflow_entries()` so it only dedups entries when identity is strong enough (not timestamp-only),
     with PID-aware matching to avoid collapsing separate runs that merely share a timestamp.
   - Keep current metadata merge behavior for true duplicates.

2. Make RUNNING↔WORKFLOW dedup collision-safe.
   - Update `dedup_running_vs_workflow()` to resolve candidate WORKFLOW entries by timestamp with disambiguation (prefer
     exact PID match; avoid dedup when ambiguous).
   - Preserve existing metadata propagation semantics when a safe match is found.

3. Add regression tests.
   - Add tests that simulate same-timestamp, different-PID runs and assert they remain separate.
   - Add tests ensuring legitimate dedup behavior still works when timestamps and PID represent the same run.

4. Validate end-to-end behavior.
   - Run targeted tests for dedup behavior.
   - Run `just check` (per repo instructions) after code changes.

## Success Criteria

- Distinct agents launched in the same second no longer collapse into one Agents-tab entry.
- Existing dedup functionality for true duplicate loader records remains intact.
- Test coverage includes the reported collision scenario.
