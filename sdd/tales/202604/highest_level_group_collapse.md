---
create_time: 2026-04-29 19:26:14
status: done
prompt: sdd/prompts/202604/highest_level_group_collapse.md
---
# Plan: `H` Collapses Only One Group Heading Level

## Problem

The `H` keymap currently collapses every expanded group banner visible in the current grouped tree snapshot. In the
Agents tab this lives in `AgentFoldingMixin._collapse_all_folds()`, and the CLs tab has the same behavior in
`ChangeSpecGroupingNavMixin._collapse_all_changespec_group_folds()`.

That makes one `H` press collapse multiple heading levels at once. The intended behavior is one level at a time:
collapse only the highest available group heading level that still has at least one uncollapsed/expanded group. With the
existing numeric group levels, “highest available” should mean the deepest rendered level first (`level=2` before
`level=1` before `level=0`). This matches the existing “peel one layer per press” model better than collapsing top-level
banners first, because it preserves visible context while reducing detail.

## Proposed Behavior

- Build the visible grouped tree using the current fold registry.
- Collect visible group entries whose `is_collapsed` is false.
- If none exist, leave group fold state unchanged.
- Find the maximum `group.level` among those expanded visible groups.
- Collapse only expanded visible groups at that level.
- Preserve existing workflow behavior in the Agents tab: visible workflow folds may still step one notch toward
  collapsed in the same `H` press, but group banners should only collapse at the selected deepest expanded group level.
- Keep focus re-anchoring behavior after a successful group/workflow collapse.

Example in a three-level Agents tree:

- First `H`: collapse all visible level-2 name-root groups.
- Second `H`: collapse all visible level-1 ChangeSpec groups that still have expanded banners visible.
- Third `H`: collapse all visible level-0 project groups.

## Implementation Steps

1. Add a small helper for selecting the deepest expanded group level from visible tree entries, or implement the logic
   locally in each mixin if the tree entry types make a shared helper awkward.
2. Update `AgentFoldingMixin._collapse_all_folds()` so its group-collapse pass only collapses expanded visible group
   entries whose `level` equals the selected maximum expanded level.
3. Update `ChangeSpecGroupingNavMixin._collapse_all_changespec_group_folds()` with the same level-selection rule so the
   `H` keymap has consistent grouped-heading semantics across Agents and CLs.
4. Update stale comments/docstrings that currently say `H` collapses every expanded banner.
5. Add focused tests:
   - Agents: with visible L0, L1, and L2 banners, one `H` collapses only L2 groups and leaves L0/L1 expanded.
   - Agents: after L2 groups are already collapsed or absent, `H` collapses the next deepest expanded level.
   - CLs: with visible L0 and L1 banners, one `H` collapses only L1 sibling-root groups and leaves L0 expanded.
   - Existing simple L0-only fixtures should still collapse L0 banners.
6. Run targeted tests for the affected fold/navigation modules, then run `just check` because repo memory requires it
   after changes.

## Verification

Targeted commands:

```bash
pytest tests/ace/tui/test_agent_fold_transitions.py tests/ace/tui/test_changespec_grouped_navigation.py
pytest tests/ace/tui/models/test_agent_groups_folds.py tests/ace/tui/models/test_changespec_groups_layout.py
```

Final command:

```bash
just check
```
