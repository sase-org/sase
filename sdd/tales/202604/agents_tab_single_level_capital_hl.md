---
create_time: 2026-04-27 15:40:06
status: done
prompt: sdd/prompts/202604/agents_tab_single_level_capital_hl.md
---
# Single-level `H` / `L` on the Agents tab

## Problem

On the Agents tab of `sase ace`, capital `H` and `L` currently jump straight to the fully-collapsed / fully-expanded
endpoints:

- `L` (`_expand_all_folds`, `src/sase/ace/tui/actions/agents/_folding.py:340`) marks **every** known L0 / L1 group key
  expanded, then runs a `while self._fold_manager.expand(key)` loop that drives every visible workflow fold all the way
  to `FULLY_EXPANDED`.
- `H` (`_collapse_all_folds`, `src/sase/ace/tui/actions/agents/_folding.py:368`) is symmetric: it `while`-loops every
  workflow fold down to `COLLAPSED`, then collapses every known L0 / L1 key.

The user wants `H` / `L` to instead behave "as if I navigated to each currently-open entry / heading and pressed the
lowercase `h` / `l` once." That is: each press should advance the visible tree by exactly one logical level, not jump
straight to the endpoint. Pressing `H` or `L` repeatedly should peel one layer at a time.

The lowercase `h` / `l` actions already implement the per-row "one step" semantics we want to broadcast (`_expand_fold`,
`_collapse_fold` in the same file). The lowercase ops have three "kinds" of step:

| Focus context                              | `h` (collapse one)          | `l` (expand one)          |
| ------------------------------------------ | --------------------------- | ------------------------- |
| Banner focused, expanded                   | banner → collapsed          | (already expanded; no-op) |
| Banner focused, collapsed                  | (escalates to parent)       | banner → expanded         |
| Workflow agent focused, fold non-collapsed | fold steps one level down   | fold steps one level up   |
| Workflow agent focused, fold collapsed     | (collapses enclosing group) | fold steps to `EXPANDED`  |

For the bulk `H` / `L` analog we only care about the "applies to a currently-visible _open_ row" subset of those rules,
since a literal "navigate to each open entry/heading and press h/l" walk would never land on a row that is currently
invisible or already at its endpoint.

## Goal

Redefine `_expand_all_folds` and `_collapse_all_folds` (agents-tab branches only) so that one keypress advances the tree
by exactly one level across _all_ currently-visible nodes simultaneously.

The non-agents-tab branches (axe, changespecs) keep their current semantics — this change is scoped to
`self.current_tab == "agents"`.

## Design

### Visibility snapshot

Compute the visible tree once at the start of each `H` / `L` invocation using the existing helper:

```python
entries = build_agent_tree(
    self._agents,
    fold_registry=self._group_fold_registry,
    mode=self._active_grouping_mode(),
)
```

This snapshot is the iteration domain. Anything that becomes visible _as a result of_ this press is **not** stepped —
the next `L` press will pick those up. That snapshot-at-start rule is what gives the "one level per press" feel
naturally, without level-by-level branching logic.

### `L` (`_expand_all_folds`, agents tab)

For each `TreeEntry` in the snapshot:

1. **`kind == "group"`, currently collapsed banner** → call `self._group_fold_registry.expand(group_key)`. (An expanded
   banner in the snapshot is a no-op — same as lowercase `l` on it.)
2. **`kind == "agent"`, agent has a workflow key whose fold is not `FULLY_EXPANDED`** → call
   `self._fold_manager.expand(wf_key)` once (no `while` loop — single level only). Use `_get_workflow_key_for_agent` for
   resolution; keys must be deduplicated since a workflow parent and its children all share the same key.

If anything changed:

- Clear `self._current_group_key` so a banner that just stopped being selectable (because its rows became visible)
  doesn't leave a stale banner focus. (Mirrors the existing post-expand behavior.)
- Call `self._refilter_agents()` to rebuild the rendered tree.

### `H` (`_collapse_all_folds`, agents tab)

For each `TreeEntry` in the snapshot:

1. **`kind == "agent"`, agent has a workflow key whose fold is not `COLLAPSED`** → call
   `self._fold_manager.collapse(wf_key)` once. Dedup workflow keys.
2. **`kind == "group"`, currently expanded banner** → call `self._group_fold_registry.collapse(group_key)`.

Order matters mildly: stepping workflow folds **before** collapsing the banners means we don't waste work on workflow
folds whose enclosing banner is about to hide them. (Same observable end-state either way; just slightly cleaner.)

If anything changed:

- `self._snap_focus_after_group_fold_change()` so focus survives banner collapses (existing helper handles the "snap to
  nearest visible ancestor banner" rule).
- `self._refilter_agents()`.

### Why "snapshot at start" is the right interpretation

The user's analogy ("navigate to each open entry/heading and press h/l") implies a fixed enumeration of currently-open
targets — not a level-by-level walk that recomputes visibility between steps. Two concrete consequences fall out of the
snapshot rule:

- After `H` on a fully-expanded tree (L0 expanded, L1 expanded, workflows at `FULLY_EXPANDED`): all expanded banners
  collapse, _and_ every visible workflow fold steps `FULLY_EXPANDED → EXPANDED` once. A second `H` press only sees L0
  banners (now collapsed) — it's a no-op for the banner registry; workflow agents aren't visible so their state stays at
  `EXPANDED`. This is fine: workflow state is stored, not displayed, when the enclosing banner is collapsed.
- After `L` on a fully-collapsed tree (L0 collapsed, L1 collapsed): only L0 banners are in the snapshot, so only those
  expand. A second `L` press now sees L1 banners and expands those. A third `L` finally sees workflow agents and steps
  their folds up. Three presses to reach a fully-expanded tree from the most-collapsed state — exactly what "single
  level" means.

This design also requires no changes to `AgentGroupFoldRegistry` or `FoldStateManager` — both already expose the right
per-key one-step primitives (`collapse`, `expand`, `collapse_keys`, `expand_keys`). We just stop using the bulk `_keys`
flavors plus the `while` loops, and walk the visible tree instead.

### What we are _not_ changing

- Lowercase `h` / `l` keep their current per-row behavior (they're already single-level).
- The `_expand_all_folds` / `_collapse_all_folds` branches for the `axe` and `changespecs` tabs (they already have
  appropriate semantics for those tabs).
- The binding labels in `bindings.py` (`"Expand All"`, `"Hooks / Collapse All"`) — the keymap names stay since they
  remain bulk operations. Help-modal description text gets a wording tweak (see Doc updates).

## Implementation steps

1. **Refactor agents-tab branches** in `src/sase/ace/tui/actions/agents/_folding.py`:
   - Replace lines ~347-358 (`_expand_all_folds` agents path) with a visible-tree walk that calls `expand` on each
     collapsed banner and `_fold_manager.expand` (single call, not `while`) on each deduped visible workflow key whose
     state is not `FULLY_EXPANDED`.
   - Replace lines ~376-386 (`_collapse_all_folds` agents path) with the symmetric walk: `_fold_manager.collapse`
     (single call) on each deduped visible workflow key whose state is not `COLLAPSED`, then `collapse` on each
     currently-expanded banner.
   - Preserve the existing post-mutation hooks: `_current_group_key` reset on expand,
     `_snap_focus_after_group_fold_change()` on collapse, and `_refilter_agents()` when anything actually changed.

2. **Tests** in `tests/ace/tui/test_agent_fold_transitions.py`:
   - Update `test_capital_l_expands_every_group`: it currently asserts a single `L` press from "all collapsed" empties
     the registry. Under the new semantics with a single L0 / L1 hierarchy in the test fixture (only L0 banners visible
     while L0 is collapsed) this still passes — but verify and adjust the fixture comment.
   - Update `test_capital_h_collapses_every_group_and_workflow`: the assertion
     `_fold_manager.get("ts1") == FoldLevel.COLLAPSED` after one `H` from `FULLY_EXPANDED` no longer holds —
     single-level semantics step it to `EXPANDED` only. Change the test to assert `EXPANDED`, then drive a second `H`
     and assert `COLLAPSED` plus the project banner now in `_group_fold_registry.collapsed`.
   - Add `test_capital_l_peels_one_level_per_press`: build a fixture with both L0 and L1 banners collapsed; verify (a)
     first `L` expands L0 only, (b) second `L` expands L1, (c) third `L` (with a workflow parent in fixture) steps
     workflow fold up.
   - Add `test_capital_h_peels_one_level_per_press`: symmetric — start fully expanded, verify each press peels one
     layer.
   - Add `test_capital_h_does_not_step_invisible_workflows`: confirm that workflows hidden behind a collapsed banner are
     not stepped by `H` (snapshot-at-start rule).

3. **Help text** in `src/sase/ace/tui/modals/help_modal/bindings.py:332`:
   - Change `"Expand all / collapse all groups"` to something like `"Expand / collapse one level (all groups)"` so the
     docs match the new single-level semantics. Honor the 32-char description cap from `src/sase/ace/AGENTS.md` —
     `"Expand/collapse one level (all)"` fits at 31 chars.

4. **Verification**:
   - `just check` (lint + mypy + test)
   - Manual exercise in `sase ace` against a project with at least L0 and L1 banners and at least one workflow parent:
     confirm `L` peels outward one layer per press and `H` peels inward one layer per press.

## Risks / open questions

- **Semantic change is observable.** Anyone with muscle memory of the current "single press jumps to endpoint" behavior
  will notice. This is the requested change, so it's intentional, but worth a release-notes mention if there's a
  CHANGELOG flow.
- **Workflow fold state with hidden-then-stepped workflows.** Under H, visible workflows step once even though their
  banner is about to hide them. This is faithful to the analogy but could feel like dangling state if a user later opens
  that banner. Acceptable — the fold state was always going to be whatever they last left it at, and pressing `L` from
  inside the now-visible workflow row will step it back up.
- **Empty snapshot edge case.** If `self._agents` is empty, the visible-tree walk yields no entries and both actions are
  clean no-ops. Existing tests that pass `[]` keep working.
