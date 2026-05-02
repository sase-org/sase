---
create_time: 2026-04-25 22:05:53
status: done
prompt: sdd/prompts/202604/agents_tab_ungrouped_first.md
---
# Sort ungrouped agents above all level-2 groups on the Agents tab

## Problem

On the Agents tab of `sase ace`, agents are grouped at two levels:

- **Level 0 (project)** — a banner per `(project, changespec)` pair.
- **Level 2 (name-root)** — a banner per shared prefix-before-`.` _only when_ the prefix is shared by two or more agents
  in the project. Singleton dotted agents (e.g. a lone `solo.gemini` next to `coder.claude` + `coder.codex`) suppress
  their would-be banner and render bare under the project banner.

Within a project, `_name_root_sort_key()` in `src/sase/ace/tui/models/agent_groups.py:105-107` only treats _dotless_
agents (empty name-root) as "ungrouped":

```python
def _name_root_sort_key(name_root: str) -> tuple[int, str]:
    return (0, "") if not name_root else (1, name_root.lower())
```

This means **suppressed-banner singletons sort interleaved with the alphabetized level-2 group banners**, even though
visually they belong with the dotless agents that hang directly under the project. Concrete example with three agents in
one project:

```
solo.gemini       ← singleton, no level-2 banner
coder.claude      ← level-2 group "coder"
coder.codex       ← level-2 group "coder"
```

Current render order (alphabetical by name-root): `coder.claude`, `coder.codex`, `solo.gemini` — the bare singleton is
buried below the `coder` banner. Expected: dotless and singleton agents always render before any level-2 group banner.

## Fix

Generalize the level-2 sort key so an agent counts as "ungrouped" iff it would render bare — i.e. either its name-root
is empty _or_ it is the only agent in the project sharing that name-root. The existing singleton-suppression rule
(`build_agent_tree`, line 238 — `len(root_indices[(k.project, k.name_root)]) >= 2`) becomes the single source of truth
for whether an agent participates in a level-2 group.

### Change 1 — `src/sase/ace/tui/models/agent_groups.py`

`_walk_order()` already has `keys_per_agent` available; pre-compute per-`(project, name_root)` counts and pass an
`in_group` bool into the sort key. Two viable shapes:

- Inline the count into `_walk_order` and replace the `_name_root_sort_key(...)` call with
  `(0, "") if not k.name_root or count[(k.project, k.name_root)] < 2 else (1, k.name_root.lower())`.
- Or factor a small `_in_level_2_group(k, counts) -> bool` helper and update `_name_root_sort_key()` to take that bool
  rather than the bare name-root.

Either way, the resulting order within a project becomes:

1. **Ungrouped bucket** — dotless agents and singleton-name-root agents, in stable input order (and workflow children
   pinned to their parent via the existing parent-inheritance plumbing in `_grouping_keys_for`).
2. **Level-2 group banners**, alphabetical by name-root, each followed by its members in stable input order.

### Behaviors preserved

- L0 (project) ordering is unchanged — named projects before `(no project)`, alphabetical by project name.
- L1 banner suppression for singletons is unchanged — the same `count >= 2` condition still gates banner emission in
  `build_agent_tree()` (line 238) and in `enumerate_group_keys()` (line 169).
- Workflow children continue to inherit grouping keys from their parent, so they stay parent-adjacent regardless of the
  new bucket boundary.
- `compute_banner_summary`, `banner_label`, `find_visible_ancestor_banner`, and the fold registry all key off `GroupRow`
  membership, not render order — untouched.
- Determinism is preserved: counts are derived from the agent list itself, so the same input set always yields the same
  partition.

### Behaviors changed (intentional)

- Within a project: dotless agents _and_ singleton dotted agents always render before any level-2 group banner.
- The visible jump-hint sequence on the Agents tab (which already follows tree-walk order per the
  `agents_jump_hint_order` fix) shifts accordingly — no code change needed in the jump-hint path.

## Tests

Add to `tests/ace/tui/models/test_agent_groups.py`:

1. **`test_singleton_dotted_agent_sorts_above_level_2_group`** — three agents in one project: `solo.gemini`,
   `coder.claude`, `coder.codex`. Assert tree-walk agent order is `[solo.gemini, coder.claude, coder.codex]` and that
   exactly one L1 banner (`coder`) is emitted between the singleton and the group members.
2. **`test_dotless_and_singleton_agents_both_precede_level_2_group`** — mix `bare`, `lone.x`, `grp.a`, `grp.b` in one
   project. Assert agent order puts `bare` and `lone.x` (in stable input order) before the `grp` banner.
3. **`test_ungrouped_bucket_preserves_input_order`** — interleave a dotless agent and a singleton dotted agent in
   different input permutations, assert each permutation is preserved within the ungrouped bucket (stable sort).
4. **Update `test_full_tree_singleton_name_root_still_suppressed_after_sort`** — extend the existing assertion to also
   check the agent order, locking in the new "singleton above group" invariant alongside the existing banner-count
   check.

The existing determinism, project-sort, and workflow-child tests already cover invariants that must continue to hold
under the new sort key — no rewrite needed.

## Validation

- `just check` passes.
- Manual: launch `sase ace` against a project with at least one singleton dotted agent and one multi-member name-root
  group. Confirm the singleton renders above the group banner, that the per-group fold key still toggles only the
  multi-member group, and that backtick-jump hints read top-to-bottom in `JUMP_HINT_CHARS` order.

## Out of scope

- L0 (project) ordering — no change.
- The fold registry, banner labels, banner summaries, and jump-hint plumbing — all derived from membership, not
  ordering.
- The ChangeSpecs and AXE tabs — they do not use the two-level grouping tree.
