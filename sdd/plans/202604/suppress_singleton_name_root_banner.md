---
create_time: 2026-04-25 17:47:33
status: wip
prompt: sdd/prompts/202604/suppress_singleton_name_root_banner.md
---

# Plan: Suppress name-root banner for single-entry groups

## Goal

In the Agents tab of `sase ace`, the level-2 (name-root) banner currently renders for every dotted agent name even when
only **one** entry sits beneath it. The result is visually noisy — see this excerpt from the user's snapshot:

```
· d ·1 agent
✘ [agent] sase (PLAN DONE) (6 steps) @d.plan
...
· j ·1 agent
✘ [agent] sase (PLAN DONE) (6 steps) @j.plan
```

A header that wraps a single child is pure chrome. We want the level-2 banner to render **only when the name-root group
contains at least two entries**. Tag and project banners are unaffected — they remain top-level structural markers.

## Design

The grouping tree is built in `src/sase/ace/tui/models/agent_groups.py`. Two builders matter:

- `_build_full_tree` — the L3 (fully-expanded) renderer. Currently it emits a level-2 `GroupRow` whenever `k.name_root`
  is truthy, regardless of how many agents share that root.
- `_build_collapsed_tree` — used at L0/L1/L2 (headers-only). At L2 it currently emits one banner per unique name-root
  group, again regardless of population.

We will gate the level-2 banner on the **size of the name-root index list**:

- Threshold: emit only when `len(root_indices[(tag, project, name_root)]) >= 2`.
- "Size" counts every entry in that group, including workflow children (they inherit their parent's grouping keys via
  `_grouping_keys_for`). This matches what is rendered, and means a workflow-parent + child pair still gets a banner —
  that group has two visible entries, so the banner is informative.

Both code paths use the same threshold, so behavior stays consistent across fold levels:

- **L3 (full tree)**: a singleton name-root group simply skips the banner; the agent row continues to render under its
  project banner exactly as it does today for dotless names.
- **L2 (headers-only)**: the level-2 banner is also skipped for singletons. The agent is still represented at L2 via its
  project banner's `agent_indices` (and via snap-to-ancestor when fold-level changes hide it). No agent becomes
  unreachable, because every project banner already carries the full index set of its members.

### Why size-based, not "count of non-workflow-children"

The `compute_banner_summary` helper excludes workflow children when computing the displayed `N agents` count. It would
be tempting to use that count for the threshold so the banner aligns with what the user reads. But the threshold should
match what the user _sees as rows_, not what the summary chip reports — and rows include workflow children. Using
`len(root_indices[...])` is also the only datum already available at tree-build time without a second pass over the
agent list.

The two interpretations only diverge for "one parent + N workflow children" groups, where the summary would say "1
agent" but the renderer would emit 1 + N rows. A banner is welcome there.

### Edge cases reviewed

- **Workflow parent + child sharing a name root** (`test_workflow_child_inherits_parent_grouping`): two entries, banner
  still emits. No change.
- **Two unrelated agents with the same name root** (`test_two_agents_sharing_name_root_share_one_name_root_banner`): two
  entries, banner emits. No change.
- **Single dotted-name agent** (`test_named_agent_emits_name_root_banner_when_name_has_dot`): banner suppressed. Test
  must be updated to expect `[group L0, group L1, agent 0]`.
- **Single dotless agent**: already produces no level-2 banner. No change.
- **Non-contiguous tag clusters with single-agent name-roots** (e.g. alpha → beta → alpha, each alpha an isolated root):
  each cluster's level-2 banner is suppressed if its root index set has size 1. The level-0 and level-1 banners still
  repeat across clusters. No regression in `test_non_contiguous_same_tag_emits_repeated_banners`.

## Implementation

### `src/sase/ace/tui/models/agent_groups.py`

1. **`_build_full_tree`**: in the level-2 emit branch, gate on `len(root_indices[(k.tag, k.project, k.name_root)]) >= 2`
   in addition to the existing `if k.name_root`. Keep `cur_root = k.name_root` updates outside the gate so the boundary
   tracking still works (a singleton root should reset `cur_root` so subsequent sibling roots are evaluated correctly).
2. **`_build_collapsed_tree`**: in the level-2 branch, apply the same `>= 2` gate before adding the banner. `seen_roots`
   should still record the root id so we don't accidentally re-evaluate it (though with the suppression in place,
   re-evaluation is also a no-op).
3. **Module docstring**: add a short note that level-2 banners only appear for groups with two or more entries.

### Tests

#### `tests/ace/tui/models/test_agent_groups.py`

- Update `test_named_agent_emits_name_root_banner_when_name_has_dot` so the assertion no longer expects a level-2 banner
  for a single dotted-name agent. Rename it to `test_no_name_root_banner_for_single_dotted_agent` to make intent
  obvious.
- Keep `test_two_agents_sharing_name_root_share_one_name_root_banner` and `test_workflow_child_inherits_parent_grouping`
  exactly as-is — they already cover the "≥ 2 entries → banner emits" path.
- Add a new test `test_singleton_name_root_emits_no_banner_among_other_roots` covering the snapshot scenario: three
  agents with name roots `coder.claude`, `coder.codex`, `solo.gemini`. Assert the `coder` root emits one banner; the
  `solo` root emits none; rows interleave correctly.
- Update `test_fold_level_2_emits_name_root_banners_but_no_agent_rows` — its current dataset already has two `coder.*`
  agents (two entries) but only one `planner.claude` (one entry). Adjust expectation so only the `coder` level-2 banner
  appears, then add a second `planner.codex` agent in a sibling test to keep coverage of the multi-root case.
- Add `test_fold_level_2_skips_singleton_name_root_banner` to lock in the L2 collapsed-tree behavior.
- `find_visible_ancestor_banner` tests: `test_find_visible_ancestor_banner_picks_deepest_match` uses a 2-agent
  shared-root setup, so it still passes. Add `test_find_visible_ancestor_banner_falls_back_when_root_singleton` to
  verify a singleton-root agent falls back to the project banner.

#### `tests/ace/tui/widgets/test_agent_list_grouping.py`

- `test_named_agents_share_name_root_banner` already uses two `coder.*` agents — still passes.
- Add `test_singleton_name_root_emits_no_level2_banner_in_main_panel` exercising
  `widget._row_entries == [_BR, _BR, (0, None)]` for a single `coder.claude` agent (just tag + project banners).

### Manual verification

- Run `just check` in the workspace.
- Open `sase ace` and confirm the snapshot's `· d ·` and `· j ·` headers no longer appear above their lone children.
  Confirm `· sase-r ·` and `· sase-q ·` (multi-entry roots) still render their banners.
- Cycle fold levels (`l` / `h`) to confirm L2 also drops the singleton-root banners and that snap-to-ancestor still
  works (focus a singleton root agent, fold up to L2, focus should land on the project banner).

## Out of scope

- Changing the threshold itself into a configurable setting. If users later want to tune it (e.g. banner only for ≥ 3),
  it's a one-line change.
- Any change to tag- or project-level banners. Those remain unconditional structural markers.
- Pinned panel — still flat per Phase 3 design in `agents_tab_nested_groups.md`.

## Risks

- **Selection regression on banner rows**: at L3, rendering currently routes banner clicks to the first agent in their
  `agent_indices` (`_resolve_row` in `agent_list.py`). Suppressing a singleton banner removes that navigation target,
  but the agent row itself is still selectable, so behavior is strictly simpler. No risk.
- **Visual rule continuity**: the project banner currently shows `── sase / sase 16 agents · 3 running ────` followed by
  the level-2 banner (or directly the agent rows). Skipping the level-2 banner for singletons just collapses the section
  header — already the established behavior for dotless names, so the layout is uniform.
