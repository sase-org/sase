---
create_time: 2026-06-16 17:23:02
status: done
prompt: sdd/prompts/202606/agents_bulk_kill_edit.md
---
# Agents Tab Bulk Kill And Edit With Prompt Stack

## Goal

Add Agents-tab support for `,X` to kill/dismiss a marked set of agents and then open a prompt stack where each removed
agent's raw prompt is loaded into its own editable prompt pane. Pane order must follow the order in which the user
marked agent rows with `m`, not visible row order and not Python set order.

This is TUI glue and presentation behavior. It should stay in this repo and reuse the existing kill/dismiss cleanup
tasks; it should not move into `sase-core`.

## Current State

- Plain `x` already bulk kills/dismisses marked Agents-tab rows by routing through
  `AgentMarkingMixin._bulk_kill_marked_agents()` and `AgentKillFlowMixin._do_bulk_kill_agents()`.
- `,x` currently kills/dismisses only the selected agent and mounts `PromptInputBar` with that agent's raw prompt.
- Bulk kill/dismiss persistence already runs as a tracked cleanup task via `_submit_bulk_kill_persistence_task()`, which
  keeps it visible in the Task Queue and included in quit safety.
- The prompt bar already supports a stack of prompt panes, but mounting from one string can split on real `---`
  separators. For this feature, each killed agent must become exactly one prompt pane even if that agent's raw prompt
  itself contains separators or YAML frontmatter.
- Agent marks are stored in `_marked_agents`, a set. That is sufficient for membership, but it cannot satisfy the new
  mark-order requirement.

## Behavior Contract

1. `,X` is an Agents-tab leader action for "kill marked and edit".
2. If no Agents-tab marks exist, `,X` warns `No agents marked` and does not fall back to the focused row. Existing `,x`
   remains the focused-row kill-and-edit action.
3. Mark order is explicit:
   - marking a row appends its identity to the order list;
   - unmarking removes it;
   - unmarking and re-marking moves it to the end;
   - clearing/pruning/cleanup removes corresponding identities from the order list.
4. Stale marks are ignored/pruned before the action. If no live marked agents remain, warn `No marked agents remain`.
5. `,X` uses the same confirmation modal and kill/dismiss split as existing marked bulk kill. Cancel preserves marks and
   does not mount a prompt bar.
6. On confirmation, the existing bulk kill/dismiss operation runs first, preserving optimistic UI removal and tracked
   persistence behavior.
7. The prompt stack is populated from the ordered marked agents' raw prompts. Each prompt is transformed with the same
   forced-name-reuse rule used by single-agent `,x`.
8. To preserve "one killed agent, one prompt pane", the prompt bar is seeded from an explicit list of pane texts, not by
   joining prompts with `---`.
9. If any live marked agent selected for cleanup has no raw prompt, abort before confirmation and warn with a count.
   This matches the single-agent `,x` safety rule and avoids killing an agent without creating its corresponding edit
   pane.
10. Workflow child cascade behavior remains owned by the existing kill planner. Prompt panes are created for explicitly
    marked live agents only; cascade-hidden children are not added unless the user explicitly marked those rows.

## Implementation Plan

1. Track mark order alongside mark membership.
   - Add `_marked_agent_order: list[AgentIdentity]` to app state, type hints, and test fakes.
   - Update `_toggle_mark_agent()`, `_clear_agent_marks()`, `_prune_stale_marked_agents()`, save/dismiss paths, tagging
     paths that subtract marks, and bulk cleanup paths that clear marks so the order list stays consistent.
   - Add a small helper such as `_marked_agents_in_mark_order()` that maps identities to current `Agent` objects and
     appends any legacy/test-only marked identities missing from the order list in current `_agents_with_children`
     order.

2. Add an explicit prompt-stack seeding API.
   - Add a public `PromptStackState.from_panes(texts, selected_index=last)` wrapper around the existing single-pane
     construction semantics.
   - Add `PromptInputBar(initial_panes=...)` or an equivalent mount helper that uses `from_panes()` so each raw prompt
     is loaded verbatim into one pane.
   - Keep existing `initial_value` behavior unchanged for history loads and typed multi-prompts.

3. Add the bulk kill-and-edit flow.
   - Implement `_bulk_kill_marked_agents_and_edit()` near the existing kill/edit entry points.
   - Resolve live marked agents using mark order.
   - Collect raw prompts before mutating the agent list, apply `_force_name_reuse_in_prompt()`, and abort if any
     selected live marked agent lacks prompt content.
   - Reuse the existing bulk confirmation modal by allowing `_present_bulk_kill_modal()` to accept an optional
     confirmation callback, defaulting to today’s `_do_bulk_kill_agents()`.
   - On confirm, call `_do_bulk_kill_agents(killable, dismissable)` and then mount the prompt stack with the prepared
     ordered prompts using a bulk variant of `_edit_and_relaunch_agent()`.

4. Wire `,X`.
   - Add a new leader-mode keymap entry, likely `kill_marked_and_edit: "X"`, in `src/sase/default_config.yml` and
     `LeaderModeKeymaps`.
   - Dispatch it from `LeaderModeMixin._dispatch_leader_key()` only on the Agents tab.
   - Update leader footer text to show `kill marked & edit (<N>)` when marks exist.
   - Update Agents help text if leader-mode actions are documented there.

5. Tests.
   - Mark order:
     - marking A then B then C records A/B/C order;
     - unmarking then re-marking moves that identity to the end;
     - clearing/pruning/bulk cleanup keeps order state consistent.
   - Prompt seeding:
     - `PromptInputBar(initial_panes=[...])` creates one pane per text without splitting embedded `---`;
     - existing `initial_value` splitting behavior remains unchanged.
   - Bulk `,X` flow:
     - with marked running and done agents, confirmation calls the existing bulk kill path and mounts panes in mark
       order;
     - cancellation preserves marks and mounts nothing;
     - stale marks are ignored/pruned;
     - any missing raw prompt aborts before kill and shows a warning;
     - a one-mark `,X` works through the marked flow, while no marks warns.
   - Keymap/footer:
     - `,X` dispatches on Agents tab and is absent/no-op elsewhere;
     - default keymap config and typed keymap defaults stay in sync.

## Verification

Run focused tests first:

```bash
pytest tests/ace/tui/test_agent_marking.py tests/ace/tui/test_retry_edit_agent_name.py tests/ace/tui/widgets/test_prompt_stack.py
```

Then run any new focused module for bulk kill-and-edit and keymap/footer assertions.

Because this repo requires it after source changes:

```bash
just install
just check
```

## Risks And Boundaries

- The main correctness risk is losing mark order because `_marked_agents` is a set. Keeping membership and order as
  separate structures, with one helper that reconciles them, limits churn in existing marked-set actions.
- The main prompt risk is separator parsing. Explicit pane seeding avoids accidentally splitting a killed agent's raw
  prompt into multiple panes.
- Bulk prompt collection should not add a new synchronous slow path beyond the existing single-agent `,x` behavior. If
  prompt reads prove expensive for large marked sets, collect them via a short worker and apply the confirmation/mount
  step back on the UI thread.
- Kill/dismiss persistence should remain untouched except for clearing mark-order state; the existing tracked cleanup
  task path already satisfies the TUI performance rules.
