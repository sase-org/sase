---
create_time: 2026-05-12 23:21:02
status: done
prompt: sdd/prompts/202605/tui_agent_list_stability_fix.md
---
# TUI Agent List Stability Fix

## Goal

Stabilize the Agents tab so rows do not disappear and reappear after the full-history reconcile, and so child/follow-up
rows are not rendered without their visible parent in the normal agent list.

## Diagnosis

The loader has a two-tier artifact path. Tier 1 is intentionally incomplete: it uses the artifact index or a bounded
source scan for fast startup. Tier 2 is the complete source scan. The TUI correctly schedules Tier 2 after Tier 1, but
ordinary later refreshes still default back to Tier 1 and replace `_agents_with_children` with that smaller snapshot.
That makes the displayed row universe oscillate between incomplete and complete history.

The orphan-child symptom comes from two places:

- `sort_and_reorder()` groups follow-up rows by `parent_timestamp`, but appends any follow-ups whose parent is absent.
  Those rows therefore look like normal children even though the parent row is not present.
- The fold-state filter assumes the flat list already has coherent parent/child structure, so it does not drop workflow
  children whose parent disappeared earlier in the pipeline.

The prior `s5.cld` analysis also identified a dismissed-filter path where roots can be removed independently of
children. That is a valid hardening concern, but the main disappearance/reappearance behavior is the Tier 1/Tier 2
replacement loop described by `s5.cdx.plan`.

## Implementation Plan

1. Add a small merge helper in the agent loading mixin for incomplete loads after a completed full-history load.
   - Detect when the previous `_agent_load_state` was complete and the incoming `load_state` is incomplete.
   - Treat the incoming Tier 1 list as a patch over the cached `_agents_with_children`: replace matching identities,
     prepend or otherwise insert newly loaded rows in Tier 1 order, and preserve historical rows that Tier 1 omitted.
   - Filter preserved cached rows against the current dismissed set so externally dismissed rows are not resurrected.

2. Keep the first paint behavior unchanged.
   - Before the first Tier 2 reconcile has completed, Tier 1 may still replace the list and schedule a full-history
     reconcile.
   - Search and explicit revive flows already force full-history and should continue to do so.

3. Stop rendering orphan children in the normal ordered list.
   - In `sort_and_reorder()`, remove the final append of follow-ups whose parent was absent.
   - In `filter_agents_by_fold_state()`, add a parent-present guard for workflow children so any child orphaned by
     dismiss/filter logic is dropped before rendering.

4. Add focused regression tests.
   - Cover Tier 1 -> Tier 2 -> Tier 1 apply sequence and assert the post-reconcile cache keeps historical rows while
     updating active rows and inserting new Tier 1 rows.
   - Cover orphan follow-ups in `sort_and_reorder()` and orphan workflow children in the fold filter.

5. Validate.
   - Run focused tests for the modified loader/order/fold paths.
   - Because this repo requires it after code changes, run `just install` if needed and `just check` before reporting
     completion.
