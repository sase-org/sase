---
create_time: 2026-04-25 18:40:53
status: done
prompt: sdd/prompts/202604/agents_jk_random_jumps_at_fold_3.md
---
# `sase ace` Agents tab: `j`/`k` jumps to random rows at fold level 3 once nested groups exist

## Problem

On the Agents tab of `sase ace`, pressing `j`/`k` (next / previous entry) at the default group fold level (3 — fully
expanded, all agent rows visible) jumps to seemingly random visible rows whenever the agent list contains nested groups
that aren't already in tag/project/name-root order.

Reproduction (matches the user's report):

- Open `sase ace`, switch to the Agents tab, leave the global group fold at level 3.
- Have agents whose grouping keys (tag, project, name-root) interleave when listed in upstream / recency order — e.g.
  `[tag=zeta, tag=alpha, tag=beta]` or two `(untagged)` agents separated in input order by an `@name_level`-tagged
  agent.
- Highlight the top visible row, press `j`. Expected: highlight moves down one visible row. Actual: highlight jumps to
  some other visible row that happens to correspond to the next agent in the upstream list order.

The same symptom appears walking upward with `k`. Repeated `j` cycles through every agent eventually but in scrambled
order — the cursor visually "ping-pongs" rather than walking down the screen.

## Root cause

The recent dedupe-and-sort fix (commit `17e1c817`, plan `plans/202604/agents_tree_dedupe_and_sort.md`) introduced a
deterministic walk over the agents tree:

- `src/sase/ace/tui/models/agent_groups.py:122-132` — `_walk_order(...)` returns a stable permutation of agent indices
  sorted by `(tag, project, name_root, original_index)`.
- `src/sase/ace/tui/models/agent_groups.py:195-259` — `_build_full_tree(...)` (used at fold level 3) walks `walk_order`,
  so the rendered row order on the main panel is the **grouping order**, not the upstream agent order.

Meanwhile the navigation path was never updated:

- `src/sase/ace/tui/actions/navigation/_basic.py:31-35` — at `level >= 3`, `_navigate_agents_panel` falls through to
  `_navigate_flat`.
- `src/sase/ace/tui/actions/navigation/_basic.py:57-68` — `_navigate_flat` walks the focused panel's flat index list via
  `_active_panel_indices()` / `_active_panel_idx_map()`.
- `src/sase/ace/tui/actions/agents/_core.py:114-155` — `_build_panel_indices` builds `_main_panel_indices` by iterating
  `enumerate(self._agents)` in the upstream agent order. So `_navigate_flat` cycles `current_idx` through
  `_main_panel_indices` in **upstream agent order**.

The two orderings diverge whenever the grouping permutation isn't the identity. After `j`:

1. `_navigate_flat` advances `current_idx` to the **upstream-next** main-panel agent.
2. `current_idx` setter triggers `_refresh_agents_display_debounced` →
   `agent_list.update_highlight(local_idx, ..., group_key=None)` (group key is forcibly `None` at level 3 — see
   `_basic.py:32-34`).
3. `AgentList.update_highlight` (`src/sase/ace/tui/widgets/agent_list.py:299-334`) finds the rendered row whose
   `_row_entries` tuple matches `(local_idx, None)` and highlights it. That row is wherever the new agent ended up in
   the **grouping** order — not the visually-next row.

The result is exactly the user's "random jumps". The pinned panel and fold levels < 3 are unaffected:

- The pinned panel renderer (`agent_list.py:218-220`) skips `build_agent_tree` and walks the flat input order directly,
  matching `_pinned_panel_indices`.
- Fold levels < 3 use the banner-cycle branch in `_navigate_agents_panel` (`_basic.py:37-55`), which already walks
  `build_agent_tree` results. (This branch was added by `agents_jk_banner_navigation` and refined by
  `jk_banner_highlight`.)

## Fix

Make the level-3, main-panel `j`/`k` walk the same sequence the renderer is showing.

### 1. New helper: visible main-panel agent order at level 3

In `src/sase/ace/tui/actions/navigation/_basic.py` (or co-located in `src/sase/ace/tui/actions/agents/_core.py` if we
want it reusable), add a small helper that mirrors what the renderer does for the main panel:

```python
def _main_panel_visible_order(self) -> list[int]:
    """Return global agent indices in the order rendered on the main panel.

    Mirrors AgentList.update_list's tree walk so j/k navigation steps
    through the same sequence the user sees.
    """
    from ...models.agent_groups import build_agent_tree

    main_agents = [self._agents[i] for i in self._main_panel_indices]
    tree = build_agent_tree(main_agents, group_fold_level=3)
    return [
        self._main_panel_indices[entry.agent_idx]
        for entry in tree
        if entry.kind == "agent" and entry.agent_idx is not None
    ]
```

Notes:

- At fold level 3, `_build_full_tree` emits every agent (including workflow children) exactly once in walk order — so
  the returned list has the same length as `_main_panel_indices`.
- Because the renderer feeds `build_agent_tree` the **local-indexed** `main_agents` (see
  `actions/agents/_display.py:98,124`), `_walk_order`'s grouping-key derivation runs against the same agent slice, so
  the helper produces the exact visible order, including parent-aware grouping for workflow children.

### 2. Use the helper in `_navigate_agents_panel` at level 3

`src/sase/ace/tui/actions/navigation/_basic.py:_navigate_agents_panel`:

```python
if level >= 3:
    self._current_group_key = None
    if self._pinned_panel_focused == "main":
        self._navigate_main_visible(direction)
    else:
        self._navigate_flat(direction)  # pinned panel stays flat
    return
```

`_navigate_main_visible` is a thin wrapper that:

1. Calls `_main_panel_visible_order()`.
2. Finds the position of `self.current_idx` in that list.
3. Sets `self.current_idx` to the entry at `(pos + direction) % len(visible)`, falling back to `visible[0]` when the
   current index isn't in the list (off-panel after a refresh / fold change).

Pinned-panel navigation is unchanged because the pinned renderer uses the flat input order — `_navigate_flat` already
matches it.

### 3. Don't recompute the tree on every keypress (optional but wanted)

Building the tree per-keystroke is O(N log N) over `_agents` and is wasteful when the user is holding `j`. Two options:

- **A. Cache on `_build_panel_indices`.** Since the visible order depends only on `_main_panel_indices` plus the agents
  themselves, recompute the cached `_main_panel_visible_order_cache: list[int]` inside `_build_panel_indices` (called
  whenever the agent set changes — `actions/agents/_loading.py`). Invalidate it nowhere else: agent attribute changes
  that affect grouping go through a full `_load_agents` reload anyway.
- **B. Compute lazily and cache on a `_visible_order_dirty` flag.** Slightly more flexible but more bookkeeping.

Option A is simpler and matches how `_main_panel_idx_map` is already maintained. The plan picks A unless we discover a
group-mutation path that doesn't reload.

## Why this shape

- Fixes the bug at its source: navigation now walks the same sequence the renderer paints.
- Reuses `build_agent_tree` so the navigation order is guaranteed to track any future grouping rule changes (singleton
  suppression, name-root coloring, etc.) without parallel logic.
- Leaves the existing fold-level < 3 banner-cycle branch and pinned-panel branch untouched — both are already correct.
- Does not alter the `SelectionChanged`, `update_highlight`, or `update_list` contracts. `update_highlight` still
  receives `group_key=None` at level 3 and finds the right row via its existing `_row_entries` search.
- Avoids alternatives that would have been heavier or wrong:
  - **Reorder `_main_panel_indices` to match the visible order.** Would silently change every other consumer of
    `_main_panel_indices` (`_active_panel_indices`, ordering, killing, marking, ...). The visible order is a
    presentation concern, not a panel-membership one.
  - **Make the renderer preserve input order at level 3.** Would re-introduce the duplicated banners that
    `agents_tree_dedupe_and_sort` just fixed.
  - **Track the "currently highlighted visible row" in app state and increment that.** Duplicates state already owned by
    `OptionList.highlighted` and creates a sync surface across debounce boundaries.

## Tests

Existing relevant test files:

- `tests/ace/tui/test_agent_jk_navigation.py` — j/k flow at the action level (`_StubApp` harness). The current
  `test_l3_keeps_flat_agent_navigation` only uses input that's already in tag-alphabetical order, which is why this bug
  went undetected.
- `tests/ace/tui/widgets/test_agent_list_grouping.py` / `_attempts.py` / `_bindings.py` — `AgentList` rendering and
  highlight resolution.
- `tests/ace/tui/models/test_agent_groups.py` — tree builder semantics.

Add cases:

1. **Regression at the action level (level 3, scrambled input).** Build agents in input order
   `[tag=zeta, tag=alpha, tag=beta]`, level=3, current_idx=1 (the `alpha` agent — visually first because of
   `_walk_order`). Press `j` once: `current_idx` must become `2` (the `beta` agent — visually second), not `2` because
   it happens to coincide. Press `j` again: `current_idx` becomes `0` (`zeta`, visually third). Press `j` again: wraps
   to `1`.
2. **Regression at the action level (interleaved tags).** Mirrors the user's snapshot:
   `[(untagged), (untagged), @name_level, (untagged)]`. Walking `j` from the first `(untagged)` agent must visit the
   second `(untagged)`, then the third `(untagged)` (still inside the contiguous `(untagged)` block per the dedupe fix),
   then the `@name_level` agent — never jumping back and forth across the rendered banner boundary.
3. **Reverse direction symmetry** for both above cases — `k` walks the visible order in reverse.
4. **Pinned-panel branch stays flat** at level 3 — extend the existing pinned test with a scrambled input order to
   confirm the helper is not wired into the pinned branch.
5. **Workflow children inherit parent grouping** — agents ordered `[parent, unrelated_tag_agent, workflow_child]`. The
   visible order should be `[parent, workflow_child, unrelated_tag_agent]` (child renders contiguous with parent per
   `_grouping_keys_for`). Pressing `j` from the parent must land on the workflow child, not the unrelated agent.

The `_StubApp` harness in `test_agent_jk_navigation.py` builds `_main_panel_indices = list(range(len(agents)))` so the
helper falls into the "everything is on the main panel" path with no extra plumbing required.

## Files

Changed:

- `src/sase/ace/tui/actions/navigation/_basic.py` — branch `_navigate_agents_panel` at level 3 on `main` to a new
  `_navigate_main_visible(direction)` helper. Add the helper.
- `src/sase/ace/tui/actions/agents/_core.py` — add `_main_panel_visible_order` (cached, recomputed in
  `_build_panel_indices`) and the `_main_panel_visible_order_cache` attribute declaration.
- `tests/ace/tui/test_agent_jk_navigation.py` — add the cases above; update the `_StubApp` to build the cache (or
  recompute the helper on demand if we keep it un-cached for the tests).

Out of scope:

- Pinned-panel navigation (already correct).
- Fold-level < 3 banner cycle (already correct after `jk_banner_highlight` and `agents_jk_banner_navigation`).
- Tree builders in `models/agent_groups.py` (already correct after `agents_tree_dedupe_and_sort`).
- The `update_highlight` / `_row_entries` row-resolution logic in `AgentList` (already correct — the bug is upstream in
  `current_idx` selection, not in rendering).
- `SelectionChanged` event flow and `_programmatic_update` gating (untouched).
