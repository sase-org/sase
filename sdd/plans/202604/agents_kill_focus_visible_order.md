---
create_time: 2026-04-25 19:34:01
status: done
prompt: sdd/prompts/202604/agents_kill_focus_visible_order.md
---
# `sase ace` Agents tab: `x` (kill / dismiss) jumps focus to a "random" agent instead of the row below the killed one

## Problem

On the Agents tab, with the deterministic group-tree ordering now in place, pressing `x` to kill or dismiss the focused
agent moves the highlight to an apparently random agent rather than to the agent that was visually below the killed one.

Reproduction:

- Open `sase ace`, switch to Agents, leave fold at level 3.
- Have agents whose grouping keys (tag, project, name-root) interleave with their `_agents`-order — e.g. `_agents`
  ordered by start_time `[A(tag=zeta), B(tag=alpha), C(tag=beta)]`. Visible order (per `_walk_order`):
  `[B(alpha), C(beta), A(zeta)]`.
- Highlight `B` (visually first) and press `x`. Expected: highlight moves to `C` (the agent visually below `B`). Actual:
  highlight ends up on whichever agent happens to live at the post-deletion `_agents`-index that the clamp produced —
  visually unrelated to where the user was looking.

The same symptom appears for both completed agents (the dismiss branch) and running agents (the confirm-then-kill
branch). Bulk kill (marks) and group-banner kill (`_current_group_key`) share the same focus-restoration code path and
suffer the same bug.

## Root cause

This is the kill/dismiss-side analog of `plans/202604/agents_jk_random_jumps_at_fold_3.md`. The grouping-tree walk
reorders the rendered rows by `(tag, project, name_root)`, so the visual order on the main panel is **not** the same as
`_agents` order. The focus-after-mutation logic still reasons in `_agents` order:

- `src/sase/ace/tui/actions/agents/_killing.py:96-118` — `_apply_killed_agents_in_memory` removes the killed identities
  from `_agents`, rebuilds panel indices, then calls `_clamp_agent_selection_to_active_panel`.
- `src/sase/ace/tui/actions/agents/_killing.py:120-147` — `_clamp_agent_selection_to_active_panel` does only
  `current_idx = min(current_idx, len(_agents) - 1)` and a panel-membership fallback to `active[0]`. Both are
  `_agents`-index operations; neither knows the visible order.
- `src/sase/ace/tui/actions/agents/_display.py:120` — the display refresh maps `current_idx` through
  `_main_panel_idx_map` and hands the local index to `AgentList.update_list`, whose row search finds whichever row was
  emitted for that `_agents` slice index in the **grouping-walk** order. So the highlight lands on the agent that
  happens to be at position `min(N, len-1)` in `_agents`, not the agent visually below the killed one.

The dismiss path (`_apply_dismissal_in_memory` → `_refilter_agents` → `_finalize_agent_list`,
`src/sase/ace/tui/actions/agents/_loading.py:399-528`) has the same root cause: it tries to restore focus by identity,
falls back to `min(saved_idx, len-1)`, then snaps to `active[0]` if off-panel — again all `_agents`-index reasoning.

The j/k navigation case for the same root cause was already fixed by introducing `_main_panel_visible_order()`
(`src/sase/ace/tui/actions/agents/_core.py:157-173`); kill/dismiss never adopted it.

## Fix

Make the focus-after-deletion logic walk the same visible order the renderer paints. The unifying rule:

> After a deletion, set `current_idx` to whichever agent occupies the **same visible row** that the killed agent was on
> (or the previous visible row when the killed agent was the last one in its panel).

Concretely, this means: when there is exactly one focused row being killed, capture the visible-row position of that row
before the mutation; after the mutation, set `current_idx` to the agent at the same visible position in the new visible
order, falling back to the last visible row when that position is past the end.

When the deletion removes multiple agents (bulk kill / marks / banner-group kill / workflow parent + cascaded children),
the rule generalizes: capture the visible-row position of the **focused** agent before the kill; after the kill, set
`current_idx` to the first surviving agent at-or-below that visible position, falling back to the last surviving agent
in the panel.

### 1. Capture the focused visible-row position before mutation

Introduce a small helper on the panels mixin (alongside `_main_panel_visible_order`) that returns the active panel's
visible order. The visible order on the pinned panel is just `_pinned_panel_indices` (the renderer skips
`build_agent_tree` for the pinned panel — see `widgets/agent_list.py:218-220`); on the main panel it is
`_main_panel_visible_order()`.

```python
def _active_panel_visible_order(self) -> list[int]:
    if self._pinned_panel_focused == "pinned":
        return list(self._pinned_panel_indices)
    return self._main_panel_visible_order()
```

This already exists piece-meal — formalizing it as one helper means the killing/dismissing/bulk paths can all share it.

### 2. New focus-restoration helper

Add a helper that takes the captured pre-mutation visible-row position and re-anchors `current_idx`:

```python
def _restore_focus_after_removal(self, prior_visible_pos: int | None) -> None:
    """Move current_idx onto the visible row that should now be focused.

    `prior_visible_pos` is the visible-row position (within the active panel)
    of the agent that previously held focus, captured *before* removal.
    After removal the same position points at the next surviving agent;
    if that position is past the end of the new visible list we fall back
    to the last visible row. When the panel is empty we delegate to the
    cross-panel fallback already encoded in
    `_clamp_agent_selection_to_active_panel`.
    """
```

Behavior:

1. Recompute the active panel's visible order.
2. If empty, run the existing panel-fallback logic (switch panel focus when one panel emptied; clamp to 0 when
   everything is gone).
3. Otherwise pick `target = visible[min(prior_visible_pos, len(visible) - 1)]`.
4. Set `self.current_idx = target`.

When `prior_visible_pos is None` (we couldn't capture a position — e.g. the focused agent was the active-panel banner in
fold-level < 3 or selection wasn't on the active panel), fall back to the existing clamp + first-of-active behavior
unchanged. This is the conservative "can't be smarter" path and matches today's behavior.

### 3. Wire the kill paths through the helper

`src/sase/ace/tui/actions/agents/_killing.py`:

- In `_apply_killed_agents_in_memory`, capture the visible position **before** mutating `_agents`:
  ```python
  prior_pos = self._capture_focused_visible_pos()  # active panel + index of self.current_idx
  self._agents = [a for a in self._agents if a.identity not in identities]
  self._agents_with_children = [...]
  self._build_panel_indices()
  self._restore_focus_after_removal(prior_pos)
  ```
- Replace the body of `_clamp_agent_selection_to_active_panel` with the new restore helper, or keep the function as a
  thin wrapper that calls `_restore_focus_after_removal(None)` so other call sites that don't have a prior position
  (e.g. revive, hide-toggle) keep working with today's clamp behavior. Either way the active-panel fallback /
  panel-empty fallback live in one place.

`_capture_focused_visible_pos()` rules:

- If `current_idx` is in `_active_panel_indices()`, return its position in the active panel's visible order.
- Otherwise return `None` (selection is on the other panel — nothing to anchor against).

### 4. Wire the dismiss / refilter paths through the same helper

`src/sase/ace/tui/actions/agents/_loading.py:_finalize_agent_list` already attempts identity-restore first
(`src/sase/ace/tui/actions/agents/_loading.py:495-501`). Keep that as the fast path: if the previously selected identity
still exists, leave it focused. Only when the selected agent has been removed (the kill / dismiss case) does the focus
need to fall through to the visible-position rule.

Capture `prior_pos` at the top of `_apply_dismissal_in_memory` (`src/sase/ace/tui/actions/agents/_dismissing.py:51-102`)
before clearing entries from `_agents_with_children`, then hand it to `_finalize_agent_list` as a new optional argument.
In `_finalize_agent_list`, after the existing identity-restore loop, if `selected_identity` no longer maps to any agent
and `prior_pos is not None`, route through `_restore_focus_after_removal(prior_pos)` instead of the bare
`min(saved_idx, len-1)` clamp.

The bulk dismiss path (`_do_dismiss_all` → `_apply_dismissal_in_memory`) and the per-agent dismiss path
(`_dismiss_done_agent` → `_apply_dismissal_in_memory`) both go through `_apply_dismissal_in_memory`, so a single change
covers both. The "kill all" path (`_kill_and_dismiss_all_agents` → loops `_do_kill_agent` then `_do_dismiss_all`) ends
up applying the rule at the end of the dismiss branch — fine, since at that point most agents have been removed and
landing on the last-visible row is the intended behavior.

### 5. Bulk / group / mark cases

`_do_bulk_kill_agents` (`_killing.py:183-263`) calls `_apply_killed_agents_in_memory(removed_ids, refresh=False)` with
the union of killed + dismissed identities, then triggers a single display refresh. The same `prior_pos` capture covers
this path because the focused agent at the time of the keystroke is the anchor; after deletion we land on the
first-surviving visible row at-or-below that anchor, which is the correct end-of-bulk-action focus.

`_bulk_kill_group_agents` (`_kill_pin.py:156-184`) routes through `_present_bulk_kill_modal` and ultimately the same
bulk path — no special handling needed.

### 6. Pinned panel

The pinned panel is rendered flat; its visible order equals `_pinned_panel_indices`. The existing
`_main_panel_idx_map`-based clamp on the pinned panel happens to behave correctly for adjacent removals only because the
flat order matches `_agents` order — but the same edge cases (last item, panel-emptied) still benefit from the unified
helper, and pinning/unpinning side-effects already churn `current_idx` through `_build_panel_indices`. The fix uses
`_active_panel_visible_order` which delegates to `_pinned_panel_indices` for the pinned panel, so behavior on the pinned
panel is preserved/clarified rather than changed.

### 7. Banner focus (fold level < 3)

When the user kills a focused **banner** (group-bulk kill, fold level < 3), there's no single agent row to anchor. Today
after such a kill the surviving banners are walked deterministically and the cursor lands on whichever banner's
`group_key` matches `_current_group_key`, falling back to the agent-row search. We don't change that path: when
`_current_group_key is not None`, capture `prior_pos = None` so the existing fallback runs — the kill-the-group flow
already handles this and re-anchors via `_current_group_key` at the next refresh.

## Why this shape

- Mirrors the j/k fix (`agents_jk_random_jumps_at_fold_3.md`) so the two focus-restoration code paths use a single
  notion of "visible order".
- Keeps `current_idx` as the single source of truth (still a global `_agents` index) — only the _clamp_ logic learns
  about visible order.
- Doesn't touch the renderer, the `update_list` / `update_highlight` row-resolution, or `SelectionChanged` flow — the
  bug is upstream in selection, not in rendering.
- Doesn't reorder `_main_panel_indices`. That list still represents panel membership (used by ordering, marking,
  killing, bulk modals). The visible order is a presentation concern that already lives in
  `_main_panel_visible_order()`.
- Avoids alternatives:
  - **Track "highlighted visible row" in app state.** Duplicates state already owned by `OptionList.highlighted` and
    creates a sync surface across the debounce boundary.
  - **Re-fetch the selection from the widget post-refresh.** Couples app state to widget timing and breaks the
    "pure-state → render" invariant the rest of the tab follows.
  - **Snap to the next agent in `_agents` order.** Would make the bug rarer but not fix it — `_agents` order and visible
    order genuinely differ at fold level 3 with interleaved grouping keys.

## Tests

Existing test files in scope:

- `tests/test_agent_kill_single.py` — `_StubApp`-style harness for `_do_kill_agent` and the immediate post-kill state.
- `tests/test_agent_kill_bulk.py` — bulk kill via marks.
- `tests/test_agent_dismiss_in_memory.py` — `_apply_dismissal_in_memory` behavior.
- `tests/ace/tui/test_agent_group_kill.py` — group-banner bulk kill flow.
- `tests/ace/tui/test_agent_jk_navigation.py` — already exercises `_main_panel_visible_order`; useful as a reference for
  stubbing visible-order at the action level.

New cases to add (mirroring the j/k fix's regression cases):

1. **Single kill at fold 3, scrambled grouping order.** Agents in `_agents` order
   `[A(tag=zeta), B(tag=alpha), C(tag=beta)]`. Visible order `[B, C, A]`. Focus `B` (`current_idx=1`), call
   `_apply_killed_agents_in_memory({B.identity})`. Expected: `current_idx` points to `C` (the agent now at visible
   position 0 of the new visible order `[C, A]`).
2. **Single kill at end of visible order.** Same fixture, focus `A` (the visually-last agent). Expected: after kill,
   `current_idx` points to the new last-visible agent (`C` after killing `A`).
3. **Single dismiss (DONE agent), interleaved grouping.** Same shape as (1) with statuses set to `DONE`; verify the
   `_apply_dismissal_in_memory` path produces the visually-next agent.
4. **Bulk kill via marks.** Mark `{B, A}`, focus `B`, run `_do_bulk_kill_agents`. Expected: `current_idx` points to `C`
   (the only survivor) and `_pinned_panel_focused`/`_marked_agents` are cleared as today.
5. **Workflow parent kill cascades children.** `[parent, unrelated_alpha, child_of_parent]` in `_agents`; visible order
   `[parent, child_of_parent, unrelated_alpha]` (child inherits parent's grouping). Focus `parent`. After kill, children
   also get removed, and `current_idx` lands on `unrelated_alpha`.
6. **Last agent in panel killed.** Single agent in main panel, focus it, kill it. Expected: panel-empty fallback —
   either switch to pinned panel (if non-empty) or `current_idx = 0` per existing behavior.
7. **Pinned-panel kill stays correct.** Focused agent on the pinned panel; killing it lands on the next pinned agent
   (regression check that the helper's pinned-panel branch still does the simple `_pinned_panel_indices` walk).
8. **Banner-focus group kill (fold level < 3).** With `_current_group_key` set, kill the focused group; verify the
   existing banner-rebind flow runs (i.e., we did not regress the no-anchor path).

The j/k tests already build a `_StubApp` whose `_main_panel_indices = list(range(len(agents)))` and that exercises
`_main_panel_visible_order`; the kill/dismiss tests can use the same stubbing pattern.

## Files

Changed:

- `src/sase/ace/tui/actions/agents/_core.py` — add `_active_panel_visible_order()`, `_capture_focused_visible_pos()`,
  and `_restore_focus_after_removal(prior_pos)`. Keep `_clamp_agent_selection_to_active_panel` as a thin wrapper
  delegating to `_restore_focus_after_removal(None)`.
- `src/sase/ace/tui/actions/agents/_killing.py` — capture `prior_pos` at the top of `_apply_killed_agents_in_memory` and
  call `_restore_focus_after_removal(prior_pos)` instead of the bare clamp.
- `src/sase/ace/tui/actions/agents/_dismissing.py` — capture `prior_pos` at the top of `_apply_dismissal_in_memory` and
  pass it to `_refilter_agents` / `_finalize_agent_list`.
- `src/sase/ace/tui/actions/agents/_loading.py` — `_finalize_agent_list` accepts an optional `prior_pos` and uses
  `_restore_focus_after_removal(prior_pos)` when the previously selected identity is gone.
- `tests/test_agent_kill_single.py`, `tests/test_agent_kill_bulk.py`, `tests/test_agent_dismiss_in_memory.py`,
  `tests/ace/tui/test_agent_group_kill.py` — add the regression cases above; extend the stub harness to populate
  `_main_panel_indices` / `_main_panel_visible_order` if needed.

Out of scope:

- Pinned-panel grouping (the pinned panel is intentionally flat).
- Banner / fold-level-<2 navigation (already correct after `jk_banner_highlight` / `agents_jk_banner_navigation` /
  `agents_jk_random_jumps_at_fold_3`).
- `update_list` / `update_highlight` / `_row_entries` (already correct — bug is upstream in `current_idx` choice).
- Custom J/K reordering (`_ordering.py`) — orthogonal; visible order via `build_agent_tree` already accounts for the
  ordered list it's given.
- `SelectionChanged` event flow and `_programmatic_update` gating (untouched).
