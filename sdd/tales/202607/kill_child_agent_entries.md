---
create_time: 2026-07-06 13:56:46
status: wip
prompt: sdd/prompts/202607/kill_child_agent_entries.md
---
# Plan: Kill Individual Agent Child Entries from the Agents Tab

## Problem

Pressing `x` on a running child row in the `sase ace` Agents tab currently goes through the same focused cleanup planner
path as root rows, but the cleanup planner treats child rows as cascade-only. That rule is correct when a parent
workflow/root row is selected, because killing the parent should hide its children and avoid duplicate child actions. It
is wrong when the user explicitly focuses a child row and presses `x`: the selected child should be a first-class
cleanup target.

The screenshot failure is consistent with this path:

- `AgentKillMixin.action_kill_agent()` resolves the focused row.
- `_plan_focused_agent_cleanup()` creates a `CLEANUP_SCOPE_EXPLICIT_IDENTITIES` request for that row.
- `plan_agent_cleanup()` skips child rows before normal kill/dismiss classification.
- The no-op toast reports a skipped item, and because unrelated out-of-scope rows may be listed first, the user can see
  `not_in_scope` instead of the child-specific skip reason.

Because cleanup planning is shared backend behavior, the primary behavior change belongs in `sase-core` and must be
mirrored by the Python fallback in this repo.

## Desired Behavior

- Pressing `x` on a running child agent row kills that child process only.
- Pressing `x` on a dismissable child row dismisses that child row only.
- Killing a root workflow/agent row keeps the existing cascade behavior for its child rows.
- Group, tag, panel, and all-panel cleanup should continue to avoid double-counting child rows unless a child was
  explicitly selected as an individual target.
- If both a parent and one of its children are selected in the same cleanup plan, the parent cascade should win and the
  child should not be listed as an additional kill.
- Runtime handling remains uniform across providers; no Codex/Claude/Gemini-specific branches.

## Implementation Plan

1. Update the Rust cleanup planner in `sase-core`.
   - Add a planner concept for "direct child target" rather than treating every child as cascade-only.
   - Allow direct child targeting only for explicit selection-style scopes, primarily `explicit_identities` and
     `custom_selection`.
   - Keep broad scopes (`all_panels`, `focused_panel`, `tag`) cascade-only for child rows so bulk cleanup does not start
     listing every child as a separate action.
   - If the selected parent is also in scope, preserve the existing parent-cascade behavior and skip the child as
     cascade-only.
   - For a direct child target, continue through the existing dismiss/kill partitioning so process-backed children
     produce `kill_items` and terminal/pidless children produce `dismiss_items`.
   - Ensure side-effect intents for a direct child are scoped to that child: dismissed index, notification dismissal,
     bundle/artifact cleanup, and workspace release only where it is actually safe. In particular, audit workflow-step
     children so killing one child does not prematurely release a still-active parent workflow claim.

2. Mirror the same behavior in the Python cleanup fallback.
   - Update `src/sase/core/agent_cleanup_facade.py` so fallback planning matches Rust exactly.
   - Keep the wire schema stable unless the Rust-side audit proves the planner needs an extra field to distinguish
     workflow-step children from family-member children. Prefer existing fields first (`parent_workflow`,
     `parent_timestamp`, `agent_type`) to avoid schema churn.

3. Adjust focused `x` handling only where needed.
   - Keep `AgentKillMixin.action_kill_agent()` routed through `_plan_focused_agent_cleanup()` so single-row behavior
     stays planner-backed.
   - Once the planner returns a child `kill_item` or `dismiss_item`, the existing confirm/dismiss flow should work with
     the selected child agent.
   - Improve `_notify_no_focused_cleanup_action()` to prefer the skipped item matching the focused row identity, so
     future no-op errors report the relevant reason instead of the first unrelated `not_in_scope` row.

4. Verify optimistic UI and persistence semantics.
   - `_collect_planned_kill_identities()` should hide only the selected child for a direct child kill.
   - Root workflow kills should still hide the root and its cascaded children.
   - `_do_kill_agent()` and `_do_bulk_kill_agents()` should not remove siblings when only a child is killed.
   - Persistence should save/dismiss/delete the child artifacts and notifications consistently with existing root kill
     behavior, without broad parent/sibling cleanup.

5. Add focused regression coverage.
   - In `sase-core`, add planner tests for:
     - explicit child-only running target becomes a kill item;
     - explicit child-only completed target becomes a dismiss item;
     - parent plus child still produces one parent kill and one cascaded child, not two kills;
     - broad tag/panel/all scopes still skip child direct listing;
     - direct child side-effect intents include the child and not siblings.
   - In this repo, add matching Python fallback tests under `tests/test_core_facade/test_agent_cleanup.py`.
   - Add TUI action tests for:
     - pressing `x` on a running child opens the kill confirmation and confirms into `_do_kill_agent(child, plan)`;
     - pressing `x` on a completed child dismisses that child;
     - killing a child removes that child from `_agents` and `_agents_with_children` while leaving the parent and
       siblings visible;
     - the no-action toast chooses the selected row's skipped reason.

6. Run validation.
   - In this repo: `just install` followed by focused tests while iterating, then `just check`.
   - In `sase-core`: run the cleanup planner Rust tests, then the repo's standard check/test command if available.
   - Manually sanity-check the Agents tab flow if a live child-agent fixture is easy to create; otherwise rely on
     focused TUI action tests plus planner coverage.

## Notes and Risks

- The existing child skip rule is intentional for parent-cascade cleanup, so the change should be narrowly scoped to
  explicit individual child selection.
- The main correctness risk is workspace release for workflow-step children. Family-member child rows are normal agent
  runs and should behave like top-level running agents, but workflow-step children may share a parent workflow claim.
  The implementation should confirm whether releasing that claim is correct before applying existing workflow kill side
  effects to a direct child.
- The plan does not require keymap config changes because `kill_agent: "x"` already exists and the issue is downstream
  cleanup planning.
