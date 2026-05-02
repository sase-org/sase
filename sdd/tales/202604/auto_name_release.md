---
create_time: 2026-04-27 13:23:47
status: done
prompt: sdd/prompts/202604/auto_name_release.md
---
# Fix Auto-Assignable Agent Name Release

## Problem

`sase ace` can show multiple non-dismissed agents that share the same auto-assignable root name, such as `@a`,
`@a.plan`, and `@a.codex.plan`. The allocator currently treats a completed agent with `done.json` as no longer reserving
its auto name. That is wrong for the Agents tab: completed agents remain visible until the user kills or dismisses them,
so reusing their root name creates ambiguous groups and confusing `@name` references.

The intended rule is:

- A name is reserved while any non-dismissed agent that appears in the Agents tab still claims it.
- A name is released when the agent is dismissed, its artifacts are deleted, or a non-done agent is dead/stale.
- Done agents do not require a live PID to reserve the name, because their visible lifecycle is now controlled by
  dismissal rather than process liveness.

## Current Behavior

`src/sase/agent/names.py` implements auto-name allocation through `get_next_auto_name()` and
`_get_active_agent_names()`. That scan:

- ignores suffixes recorded in `dismissed_agents.json`,
- extracts an alphabetic prefix from dotted names and workflow names,
- skips any artifact directory that has `done.json`,
- checks process liveness only for non-done artifacts.

The `done.json` skip is the bug. The tests in `tests/test_agent_names.py` currently lock in that behavior with cases
like `test_done_agent_releases_name`, `test_dotted_done_agent_releases_prefix`, and
`test_done_multi_model_releases_base_name`.

## Implementation Plan

1. Update `_get_active_agent_names()` so non-dismissed done artifacts reserve their relevant name slots.
   - Keep the existing dismissed suffix exclusion first, so dismissed done agents are released.
   - Keep stale/dead non-done artifact handling unchanged: no `done.json` still requires a live process.
   - For root/non-child artifacts, add the effective `workflow_name` or `name` and any extracted auto prefix.
   - For `parent_timestamp` children, continue reserving only the extracted auto prefix so follow-up phases do not
     independently reserve full workflow names.

2. Keep `find_named_agent()` behavior separate from allocation.
   - It can still prefer running agents over done agents for `@name` resolution.
   - This fix should not strip names from completed artifacts or alter historical lookup behavior.

3. Preserve explicit repeat-name collision behavior.
   - `_get_active_child_names()` already treats done child names as claimed unless dismissed, which matches the desired
     rule.
   - No repeat-launcher change should be necessary unless tests expose inconsistency.

4. Update tests to express the new lifecycle rule.
   - Replace “done releases name” expectations with “done but not dismissed reserves name”.
   - Keep `test_reuses_dismissed_agent_name` proving dismissal releases the slot.
   - Keep dead/no-PID non-done tests proving killed or stale agents release the slot.
   - Add or adjust coverage for done dotted/workflow names reserving the alphabetic root prefix, including `.plan` /
     `.codex.plan` style names that caused the snapshot.

5. Verify.
   - Run focused tests: `just test tests/test_agent_names.py`.
   - Because this repo memory requires it after file changes, run `just install` if needed and then `just check`.

## Risks and Non-Goals

- This may delay reuse of short names (`a`, `b`, etc.) until users dismiss visible completed agents. That is intentional
  and matches the UI rule.
- This does not change how `@name` chooses among old done artifacts with the same explicit name. The allocator should
  prevent new non-dismissed auto-name duplicates going forward.
- This does not backfill or rename already-duplicated visible agents from previous runs.
