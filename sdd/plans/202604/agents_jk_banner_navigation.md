---
create_time: 2026-04-25 17:46:41
status: done
prompt: sdd/prompts/202604/agents_jk_banner_navigation.md
---
# Plan: Fix `j`/`k` Navigation Across Banner Rows on the Agents Tab

## Problem

When the Agents tab group fold is collapsed (group fold level `< 3`, i.e. only banner rows are rendered — tag, project,
and/or name-root headers per `plans/202604/agents_tab_nested_groups.md`), pressing `j`/`k` does not move the visible
highlight between banners. The selection appears stuck on the first banner even though the user can clearly see multiple
selectable banner rows.

Reproducible from a `sase ace` snapshot in which the user has collapsed the Agents panel to L2 and sees, for example:

```
══ (untagged) 15 agents · 2 running · 1 awaiting
── sase / sase 15 agents · 2 running · 1 awaiting
· d ·1 agent · 1 awaiting
· sase-r ·5 agents · 1 running
· j ·1 agent
· sase-q ·6 agents
```

`j`/`k` should cycle through these banner rows; today they do not.

## Root cause

- `j`/`k` are bound to the app-level `next_changespec`/`prev_changespec` actions (`src/sase/ace/tui/bindings.py:8-9`).
- On the Agents tab those actions delegate to `_navigate_agents_panel(direction)` in
  `src/sase/ace/tui/actions/navigation/_basic.py:15-31`. The helper only walks the flat list of agent global indices
  returned by `_active_panel_indices()` (see `src/sase/ace/tui/actions/agents/_core.py:178-188`); it never considers
  banner rows or the group fold level.
- When `_group_fold_state.level < 3`, `AgentList.update_list()` (`src/sase/ace/tui/widgets/agent_list.py:215-251`)
  renders only banner rows from `build_agent_tree(... fold_level<3)`
  (`src/sase/ace/tui/models/agent_groups.py:212-273`). In that mode the highlighted row is chosen by matching
  `current_group_key`, not by `current_idx`.
- `_navigate_agents_panel` mutates only `self.current_idx` and never touches `self._current_group_key`. The visible
  highlight therefore stays pinned to the banner whose `group_key` was last written by `event_handlers.py:298` (mouse
  click) or `_snap_focus_after_group_fold_change()` (`src/sase/ace/tui/actions/agents/_folding.py:59-83`).
- Mouse navigation works because `AgentList.on_option_list_option_highlighted` posts a `SelectionChanged` event carrying
  `group_key`, which the app handler writes back to `_current_group_key`. The keyboard path bypasses that handler.

This is also called out as expected behavior in Phase 4 of `plans/202604/agents_tab_nested_groups.md` (lines 156-160),
which says `j`/`k` should "traverse banners and agent rows uniformly". That contract was never wired up on the keyboard
side.

## Goal

Make `j`/`k` step through the same row sequence the renderer is showing:

- At fold level `< 3`: cycle through the banner rows, in tree order.
- At fold level `3`: cycle through the agents on the active panel, exactly as today — preserving the existing UX and the
  existing fold/regression tests.

The pinned panel stays flat (Phase 3 explicitly defers grouping there; `agent_list.py:160` and `update_list` already
force `effective_level = 3` for the pinned panel), so `j`/`k` keeps its current flat behavior whenever
`_pinned_panel_focused == "pinned"`.

## Approach

### Phase 1 — Make `_navigate_agents_panel` row-aware

1. **Refactor `_navigate_agents_panel`** in `src/sase/ace/tui/actions/navigation/_basic.py` so it walks the same logical
   row sequence the widget renders.
   - When the pinned panel is focused, keep today's flat-list behavior verbatim (no tree, no banner mode). The pinned
     panel does not group.
   - When the main panel is focused, branch on `_group_fold_state.level`:
     - `level < 3`: build `tree = build_agent_tree(self._agents, group_fold_level=level)` and filter to
       `kind == "group"` entries. The rendered sequence in this mode is banner-only, so navigation cycles banners.
       - Position lookup: find the banner whose `group_key` equals `_current_group_key`. If none matches (e.g. just
         after a level switch), start at the first banner — mirrors the existing "snap to first" branch on
         `_basic.py:27-29`.
       - On step: update `_current_group_key` to the new banner's `group_key` and snap `current_idx` to
         `banner.agent_indices[0]` so the detail panel and `_get_selected_agent()` consumers (e.g. detail rendering,
         `_kill_pin.py:146-152`) still have a real agent to read.
     - `level == 3`: build the same tree, filter to `kind == "agent"` entries, and intersect with
       `_active_panel_indices()` to preserve the existing panel-restricted behavior. Banners are non-selectable at L3,
       so they are skipped. Clear `_current_group_key = None` since at L3 the highlight is agent-driven.
   - Cycle direction unchanged: `(pos + direction) % len(rows)`.

2. **Type hints**: add `_group_fold_state` and `_current_group_key` to the navigation mixin's type-checking block
   (`navigation/_types.py` if needed) so the new accesses pass `mypy`. These attributes are already declared on
   `AgentsMixinCore` (`_core.py:79-80`) and on AceApp at runtime.

3. **Tests** in a new `tests/ace/tui/test_agent_jk_navigation.py`:
   - L0 fold, three tags: `j` cycles `_current_group_key` through the three tag banners; `k` reverses; `current_idx`
     lands on each banner's first agent_indices entry.
   - L1 fold: cycles project banners (one row per `(tag, project)` pair) in tree order.
   - L2 fold: cycles all banner rows (tag + project + name-root), matching the six-row layout in the user's snapshot.
   - L3 fold: matches today's behavior — `_current_group_key` stays `None` and `current_idx` cycles agents within the
     active panel. Acts as a regression guard.
   - Boundary: when `_current_group_key` does not match any visible banner (e.g. after a level transition that drops the
     previously-focused banner), pressing `j` lands on the first banner.
   - Pinned panel focused: navigation stays flat, no banner cycling, even when `_group_fold_state.level < 3`.

### Out of scope

- `gg` / `G` jump-to-top/bottom over banner rows (today they only scroll, not navigate).
- Banner-aware `J` / `K` reordering keymaps (`move_agent_up` / `move_agent_down` are a separate path with their own
  ordering invariants).
- Pinned panel grouping (deferred by the Phase 3 design).
- `?` help modal copy — no new keymaps are introduced, so no documentation change is required.

## Risks

- **Tree rebuild on every key press.** `build_agent_tree` is in-memory and O(N); cheap for the rosters seen today. The
  Phase 4 design already calls out memoization keyed on `(agent identities tuple, tag-store version, fold-level)` as a
  follow-up if rosters approach 500+ agents (`agents_tab_nested_groups.md:198`). Not necessary for this fix.
- **Third writer of `_current_group_key`.** Today only `_snap_focus_after_group_fold_change()` and the mouse handler in
  `event_handlers.py:298` mutate the field. Adding a keyboard writer is safe — the value is consumed read-only by
  `_display.py:134` (passed to `AgentList.update_list`) and by `_kill_pin.py:146-152`; no observers care about
  provenance.
- **Pinned panel layered on top of group fold.** It is possible to be on the pinned panel while the main panel's
  `_group_fold_state.level < 3`. The fix must short-circuit on `_pinned_panel_focused == "pinned"` regardless of level,
  otherwise `j`/`k` on the pinned panel would start cycling banners that are not even visible there.

## Definition of done

- `just check` passes (lint, type-check, fast test suite).
- New `tests/ace/tui/test_agent_jk_navigation.py` covers the five scenarios above (L0, L1, L2, L3 regression, boundary,
  pinned-panel).
- Manual smoke in `sase ace`:
  1. From a default expanded view, press `h` two or three times to collapse to L2 / L1 / L0.
  2. Press `j` and `k` and confirm the highlighted banner cycles through the visible rows in both directions.
  3. Confirm the side-panel agent details follow the banner's first agent (i.e. the AGENT DETAILS pane is no longer
     stuck on a hidden agent).
  4. Press `l` back to L3, press `j`/`k`, and confirm agent navigation matches today's behavior with no banner highlight
     visible.
