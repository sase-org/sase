---
create_time: 2026-04-24 18:07:41
status: done
prompt: sdd/prompts/202604/agents_new_entries_top.md
---
# Plan: Keep New Agents at the Top After Manual Reordering

## Problem

The Agents tab defaults to newest-first ordering, but after the user presses `J` / `K`, `sase ace` persists a custom
top-level agent order in `~/.sase/agent_order.json`. The current custom-order helper treats every identity that is not
in the persisted order as lower priority than every known identity, so newly launched agents appear at the bottom of the
list once any manual ordering exists.

Desired behavior: newly discovered top-level agent/workflow entries should always appear above the manually ordered
older entries, while the older entries still retain the user's custom relative ordering.

## Current Data Flow

- `load_all_agents()` returns agents in default newest-first order and inserts workflow children/follow-up entries after
  their parents.
- `AgentLoadingMixin._finalize_agent_list()` applies fold filtering and then calls `apply_custom_order()` when
  `_agent_custom_order` is non-empty.
- `apply_custom_order()` separates top-level entries from workflow children, sorts top-level entries according to the
  persisted order, and reattaches workflow children after their parent.
- `AgentOrderingMixin._move_agent()` updates `_agent_custom_order` when `J`/`K` is pressed, persists it, reapplies
  `apply_custom_order()`, and follows the selected item.

The bug lives in `apply_custom_order()` and is reinforced by `_move_agent()`: unknown identities sort after persisted
identities, and when a move involves an unknown identity the code appends missing identities to the persisted order
instead of rebuilding the order from the current visible list before swapping.

## Implementation

1. Change `apply_custom_order()` so top-level identities missing from the persisted custom order remain before ordered
   identities.
   - Missing identities should preserve their incoming relative order, which is already the loader's default
     newest-first ordering.
   - Known identities should keep their persisted relative order.
   - Workflow children must remain grouped after their parent, and orphaned children should still be appended as today.

2. Update `_move_agent()` so moves involving a previously unknown identity still behave according to the visible list.
   - When either selected or target identity is missing from `_agent_custom_order`, rebuild `_agent_custom_order` from
     the current displayed top-level order before applying the swap.
   - Then swap the selected and target identities in that rebuilt list and persist the result.
   - This makes pressing `J` on a fresh top entry produce the visible one-step-down result, while future new agents can
     still appear above the now-explicit custom order.

3. Add focused unit coverage.
   - Cover `apply_custom_order()` with a persisted order plus a newer unknown top-level agent and assert the unknown
     stays first.
   - Cover multiple unknowns preserving their default relative order.
   - Cover workflow child grouping after a known or unknown parent.
   - Cover `_move_agent()` when the selected fresh entry is missing from the persisted order and moves down one visible
     slot.

4. Verify with targeted tests first, then run the repository check command.
   - Run the focused agent ordering tests.
   - Because this repo's instructions require it after changes, run `just check` before final response. If this
     workspace lacks installed dependencies, run `just install` first as noted in `memory/short/workspaces.md`.

## Risks and Non-Goals

- Do not change keymap defaults; `J` and `K` already exist in `src/sase/default_config.yml`.
- Do not change loader default sorting; the loader already returns newest-first.
- Do not attempt to prune stale identities from `~/.sase/agent_order.json` in this change. The fix should be scoped to
  how missing identities are ordered and how moves involving them are persisted.
