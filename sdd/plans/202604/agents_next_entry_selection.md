---
create_time: 2026-04-27 14:00:34
status: done
prompt: sdd/prompts/202604/agents_next_entry_selection.md
---
# Fix Agents Tab Next-Entry Selection

## Problem

The Agents tab has two competing ideas of "next entry":

- j/k navigation walks rendered selectable rows using `_panel_navigation_stops()`, which respects grouping, collapsed
  banners, focused tag panels, and rendered order.
- Agent actions still use older agent-index assumptions in some paths. In particular, `m` advances with
  `(current_idx + 1) % len(_agents)`, and `x` removal focus restoration is based on an agent-only visible position.

This causes the cursor to land on the wrong row when `_agents` order differs from rendered order, when groups are
collapsed, or when `x` acts on a focused group banner rather than a concrete agent row.

## Goals

- Make post-action focus follow the same visible order users see on the Agents tab.
- Keep single-agent kill/dismiss behavior that already works in rendered order.
- Fix marking auto-advance so it advances through visible markable agent rows, not raw `_agents` order.
- Fix group/banner `x` restoration so removing a focused collapsed group lands on the next surviving selectable row.
- Add focused regression tests for scrambled grouping order and collapsed-banner/group removal.

## Approach

1. Treat `_panel_navigation_stops()` as the source of truth for selectable Agents-tab row order.
2. Extend focus capture/restore around removals so it can anchor either:
   - a focused agent row via `current_idx`, or
   - a focused collapsed group/banner via `_current_group_key`.
3. After removal, restore focus to the stop at the same rendered position, clamped to the last surviving stop.
   - If the target stop is an agent, clear `_current_group_key` and set `current_idx`.
   - If the target stop is a banner, set `_current_group_key` and leave `current_idx` as the nearest valid backing
     index.
   - If no stops remain, clear `_current_group_key` and clamp `current_idx` safely.
4. Change mark auto-advance to use rendered visible agent order from `_agents_visible_order()`.
   - This intentionally skips collapsed banner rows because `m` marks agents, not groups.
   - If the current agent is not visible or no helper is available, keep a conservative raw-list fallback.
5. Preserve fast patching behavior for `m`:
   - Patch the toggled row.
   - Refresh highlights when selection moves.
   - Patch the newly selected row when possible, falling back to a full refresh if patching cannot land.

## Tests

- Add marking regression tests where raw `_agents` order differs from rendered order; `m` should advance to the visually
  next agent.
- Add wraparound coverage for rendered-order marking.
- Add removal focus tests using the production Agents-tab helper methods for a focused collapsed banner; after removing
  that group, focus should land on the next surviving rendered stop.
- Run focused tests first:
  - `pytest tests/ace/tui/test_agent_marking.py tests/ace/tui/test_agent_kill_focus_visible_order.py`
  - Relevant j/k tests if helper behavior changes.
- Run repo check after edits per repo instructions:
  - `just check`
