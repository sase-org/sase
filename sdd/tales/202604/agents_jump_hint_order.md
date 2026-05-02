---
create_time: 2026-04-25 21:57:23
status: done
prompt: sdd/prompts/202604/agents_jump_hint_order.md
---
# Fix unsorted jump-hint characters on the Agents tab

## Problem

When the user presses `` ` `` (backtick) on the Agents tab of `sase ace`, the single-key jump hints rendered next to
each agent are not in alphabetical / numerical order. A typical snapshot shows hints down the visible list as:

```
1, 2, b, c, d, e, 9, 8, 0, 7, n, 6, i, g, a, h, o, p, q, r, s, t, f, j, k, l, m, 3, 5, 4
```

Expected behavior: hints should march top-to-bottom through `JUMP_HINT_CHARS = "1234567890abcdef…"` so the user sees
`1, 2, 3, 4, …, 9, 0, a, b, c, …` reading down the visible list.

## Root cause

Two layers of ordering disagree:

1. **Hint assignment** — `action_jump_to_entry()` in `src/sase/ace/tui/actions/navigation/_advanced.py:133-148` calls
   `_jump_candidate_indices()` (lines 150-156). For the agents tab it returns `list(range(len(self._agents)))` — i.e.
   agent indices in **storage order** (the order `load_agents_from_disk()` returned them, mostly chronological).
   `build_jump_hint_maps()` in `src/sase/ace/tui/actions/navigation/jump_hints.py:6-13` then `zip`s `JUMP_HINT_CHARS`
   with those indices, so hint `'1'` → index 0, `'2'` → 1, …, `'a'` → 10, `'b'` → 11, etc.

2. **Render order** — `AgentList.update_list()` in `src/sase/ace/tui/widgets/agent_list.py:211-269` walks
   `build_agent_tree()` from `src/sase/ace/tui/models/agent_groups.py:177-256`, which sorts agents by
   `(project_sort_key, name_root_sort_key, original_index)` (`_walk_order()`, lines 110-119). Workflow children inherit
   parent grouping, further breaking storage order.

When the renderer reads `jump_hints.get(i)` per agent in tree-walk order, it pulls characters from the alphabet at
scattered indices — producing the jumbled sequence above. Decoding the visible sequence back to indices yields exactly
the tree-walk permutation of `self._agents`, confirming the diagnosis.

## Fix

Make hint order match render order by computing hints from the same tree walk the renderer uses.

### Change 1 — `src/sase/ace/tui/actions/navigation/_advanced.py`

In `_jump_candidate_indices()` (lines 150-156), add an `agents`-tab branch that builds the tree (using the app's
existing fold registry, `self._group_fold_registry` — confirmed via grep: every test stub and the real `update_list`
call site pass this attribute) and returns agent indices in tree-walk order:

```python
def _jump_candidate_indices(self) -> list[int]:
    if self.current_tab == "changespecs":
        return list(range(len(self.changespecs)))
    if self.current_tab == "agents":
        from ...models.agent_groups import build_agent_tree
        tree = build_agent_tree(
            self._agents,
            fold_registry=self._group_fold_registry,
        )
        return [
            e.agent_idx for e in tree
            if e.kind == "agent" and e.agent_idx is not None
        ]
    return list(range(len(self._axe_items)))
```

`build_agent_tree()` already omits agents inside collapsed groups, so collapsed-out agents will not receive hints —
desirable, since hints on invisible rows are unusable.

### Change 2 — Test coverage

Add a unit test under `tests/ace/tui/` (sibling to the existing `test_agent_jk_navigation.py` /
`test_agent_fold_transitions.py`, which already construct an app stub with `_group_fold_registry` and `_agents`)
asserting:

1. With agents whose storage order differs from tree-walk order, `_jump_candidate_indices()` returns indices in
   tree-walk order — the same permutation `build_agent_tree()` would render.
2. With one L0 group collapsed, that group's agent indices are excluded from the returned list.

## Behaviors preserved

- The back-jump (`'`) handler stores **agent indices** in `_entry_jump_last_index[self.current_tab]`, not hint chars —
  unaffected.
- `_handle_entry_jump_key` uses `self._entry_jump_hint_to_index.get(key)` to look up an agent index and assign it to
  `self.current_idx`. Indices stay semantically identical; only their pairing with hint characters changes.
- The CLs tab and AXE tab branches are untouched.

## Behaviors changed (intentional)

- Agents inside a collapsed L0/L1 group no longer receive a hint.
- The visible hint sequence now reads top-to-bottom as `1, 2, 3, …, 9, 0, a, b, c, …`.

## Validation

- `just check` passes.
- Manual: launch `sase ace`, switch to Agents tab, press `` ` ``. Verify hints read top-to-bottom in `JUMP_HINT_CHARS`
  order. Collapse a group with the per-group fold key and re-press `` ` `` — confirm the collapsed group's agents get no
  hint and the remaining hints stay contiguous.

## Out of scope

- The hint assignment for the CLs tab and AXE tab is left untouched. Both use straight `range(len(...))` against lists
  rendered in their own native order (no grouping layer), so no mismatch exists.
- No change to `JUMP_HINT_CHARS` or `build_jump_hint_maps()`; the bug is purely in _which_ indices are passed in.
