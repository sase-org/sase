---
create_time: 2026-05-13 10:15:00
status: done
prompt: sdd/prompts/202605/agent_tier_merge_dedup_backstop.md
---
# Plan: Preserve canonical dedup behavior during post-history agent merges

## Context

The older plan at `~/.sase/plans/202605/dup_root_agent_rows.md` diagnosed duplicate root rows in the `sase ace` Agents
tab when an incomplete Tier 1 refresh was merged over a previously complete Tier 2 history load.

That primary symptom is already addressed in this workspace. In `src/sase/ace/tui/actions/agents/_loading_apply.py`,
`_merge_incomplete_load_after_complete_history` now skips an incoming non-child root when its `raw_suffix` already
belongs to a cached parent. The existing regression
`test_incomplete_load_after_complete_history_drops_running_duplicate_root` covers the exact `RUNNING` root shadowing a
cached `WORKFLOW` parent case.

However, part of the older recommendation is still relevant. The current suffix guard drops the incoming `RUNNING` row
before it can participate in the canonical `dedup_running_vs_workflow` metadata merge. That prevents the duplicate row,
but it can discard metadata that would normally be merged from the `RUNNING` projection onto the richer `WORKFLOW`
projection during a clean full load. The older plan's `dedup_by_pid` backstop is also still a useful cross-snapshot
safety net because the loader dedups each snapshot before the UI merge, while
`_merge_incomplete_load_after_complete_history` can combine rows from two different already-deduped snapshots.

## Goal

Keep the existing no-duplicate-row behavior while making the incomplete-load merge preserve the same canonical dedup
invariants as `load_tiered_agents`:

- A Tier 1 `RUNNING` projection for the same ace-run suffix as a cached `WORKFLOW` parent should be dropped as a row.
- Metadata from that `RUNNING` projection should still be merged into the cached `WORKFLOW` parent.
- Cross-snapshot same-PID duplicates should be removed with the same rules as the loader-level `dedup_by_pid` pass.
- Existing ordering, child attachment, dismissed filtering, and `hide_non_run_agents` behavior should remain unchanged.

## Implementation Approach

1. Add regression coverage before changing behavior.

   Extend `tests/test_agent_loader_self_heal.py` with a variant of
   `test_incomplete_load_after_complete_history_drops_running_duplicate_root` where the incoming `RUNNING` row carries
   metadata absent from the cached `WORKFLOW` row, such as `workspace_num`, `response_path`, `model`, `vcs_provider`,
   `agent_name`, or `step_output`.

   Assert the resulting visible rows are still only the cached workflow parent plus its child, and assert the workflow
   parent received the metadata that `dedup_running_vs_workflow` normally merges.

2. Add PID safety-net coverage.

   Add a focused test that seeds `_agents_with_children` from a complete-history snapshot with a cached row and applies
   an incomplete Tier 1 refresh containing a new root with the same PID where `dedup_by_pid` should prefer one row.

   Use a case covered by existing canonical rules, such as a cached VCS workflow/workspace claim versus an incoming
   non-VCS row, or a cached `RUNNING` row versus an incoming `WORKFLOW` row with the same PID. Assert the merge output
   matches `dedup_by_pid` expectations and keeps any merged metadata.

3. Rework `_merge_incomplete_load_after_complete_history` to retain shadow rows until canonical dedup can process them.

   Import `dedup_running_vs_workflow` and `dedup_by_pid` from `sase.ace.tui.models._dedup`.

   Instead of unconditionally discarding an incoming non-child root solely because its `raw_suffix` is already present
   in `cached_parent_suffixes`, allow canonical ace-run `RUNNING` shadow rows to enter the temporary `merged` list. Then
   run:
   - `dedup_running_vs_workflow(merged)`
   - `dedup_by_pid(merged)`

   before recomputing `always_visible`, `hideable`, and `prep.filtered_agents`.

   Preserve the current suffix guard for non-canonical shadow cases not handled by `dedup_running_vs_workflow`, so the
   existing duplicate suppression does not regress.

4. Keep child grouping stable after dedup.

   Ensure running the dedup passes after assembling `merged` does not orphan workflow children or reorder normal cached
   parent/child groups. If a dedup pass removes a parent in favor of another parent, verify children remain adjacent to
   the surviving parent for the cases covered by this merge path.

5. Validate locally.

   Run the focused regression file first:

   ```bash
   ./.venv/bin/python -m pytest tests/test_agent_loader_self_heal.py -q
   ```

   Then run the repository check command required by project memory:

   ```bash
   just check
   ```

## Non-Goals

- Do not remove the existing complete-history patch behavior for Tier 1 refreshes.
- Do not change the renderer or tree builder; they are downstream of the agent list and should continue to receive a
  deduplicated list.
- Do not move shared loader dedup logic into Python UI code beyond invoking the existing canonical dedup helpers.
