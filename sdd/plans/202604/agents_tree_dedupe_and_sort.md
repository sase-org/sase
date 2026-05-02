---
create_time: 2026-04-25 18:22:25
status: done
prompt: sdd/prompts/202604/agents_tree_dedupe_and_sort.md
---
# Plan: Stop splitting `(untagged)` (and other groups) on the Agents tab + sort groups deterministically

## Goal

In the Agents tab of `sase ace`, the top-level group banners can render the **same** group twice in a single view — the
user-supplied snapshot shows `(untagged)` appearing once near the top, then `@name_level` interrupting it, then
`(untagged)` again with the rest of its members. Group ordering also drifts run-to-run because it tracks the upstream
agent list's order (roughly recency).

Two concrete fixes:

1. A given group key (tag / project / name-root) renders **at most once** in the Agents tree. Members of the same group
   always render contiguously under one banner.
2. Group ordering is **deterministic** — the same agents, regardless of input order, produce the same banner sequence.

This fix is purely about the tree-builder used by the Agents tab; the tag persistence layer, banner styling, the pinned
panel, and the `(untagged)` / `(no project)` labels are all out of scope.

## Symptom (from the user-supplied snapshot)

```
══ (untagged) 19 agents · 1 running · 1 awaiting ══
── sase / sase 19 agents · 1 running · 1 awaiting ─
[agent] sase (WAITING) @q
· p ·1 agent · 1 awaiting
[agent] sase (PLAN APPROVED) (6 steps) @p.plan
· q ·1 agent
✘ [agent] sase (PLAN DONE) (8 steps) @q.claude.plan
══ @name_level 1 agent ════════════════════════════
── sase / sase 1 agent ────────────────────────────
✘ [agent] sase (DONE) (5 steps) @name_level @m
══ (untagged) 19 agents · 1 running · 1 awaiting ══   ← SAME GROUP again
── sase / sase 19 agents · 1 running · 1 awaiting ─
· i ·1 agent
✘ [agent] sase (PLAN DONE) (6 steps) @i.plan
…
```

The banner counts (`19 agents`) confirm both untagged banners reference the **same** underlying group — the renderer
just emitted a fresh banner each time the streamed key changed.

## Root cause

File: `src/sase/ace/tui/models/agent_groups.py`. Function: `_build_full_tree()` (≈ lines 152–213).

`build_agent_tree()` walks `keys_per_agent` in the upstream agent order and emits a banner whenever the current key
differs from the previous one. There is no de-duplication: the same group key can flip in and out as a different key
appears between members. The module docstring (lines 17–18) even calls this out:

> Banners at the same level repeat when the same key appears in non-contiguous clusters.

That documented L3 behavior is exactly the bug the user is reporting. The L0/L1/L2 collapsed builder
(`_build_collapsed_tree`) already de-dupes via `seen_*` sets, so it doesn't show the symptom.

Why agents arrive interleaved: `agent_list.AgentList.update_list()` passes `agents` straight through to
`build_agent_tree()` (`src/sase/ace/tui/widgets/agent_list.py:217`). Upstream order is creation/recency, which freely
interleaves untagged agents with `@name_level`-tagged agents. `_grouping_keys_for()` already inherits the parent's
grouping for workflow children, so children of an untagged parent are correctly classified — but the parent itself can
sit on either side of an unrelated tagged agent.

## Design

### Approach

Sort the agents into grouping order **before** running the streaming tree builder. This guarantees each group key is
emitted exactly once because all members are now contiguous; it also makes the output deterministic.

Concretely, in `build_agent_tree()`:

1. After computing `keys_per_agent`, build a stable permutation `walk_order: list[int]` of agent indices sorted by
   `(tag_sort_key, project_sort_key, name_root_sort_key, original_index)`.
2. Walk in `walk_order` rather than `range(len(agents))` inside both `_build_full_tree` and `_build_collapsed_tree`.
3. `TreeEntry.agent_idx` continues to point at the **original** position in `agents` so the renderer (which still owns
   the original list) keeps working unchanged. Only the **walk** order changes.
4. Build `tag_indices` / `proj_indices` / `root_indices` while iterating in `walk_order` so the per-group
   `agent_indices` tuples are also in display order — relevant for `find_visible_ancestor_banner` and any future
   group-bulk operation that wants "members in screen order".

### Sort key

- **Tag**: case-insensitive lex order over the tag string. The synthetic `(untagged)` group (empty tag) sorts **last**
  so user-named tags come first. This matches the docstring example in `plans/202604/agents_tab_nested_groups.md` (lines
  29–43), which puts named tag banners first and `(untagged)` at the bottom.
- **Project**: lex order on `(project_name, cl_name)`; `(no project)` (empty project) sorts last within its tag.
- **Name-root**: lex order; the empty name-root sorts **first** within its project so dotless agents render under the
  project banner before any `· root ·` group.
- **Tiebreaker**: original input index (stable). Within a single group, members keep their familiar recency order.

### Why not just de-duplicate banners

We could skip a banner if its group_key was already emitted, but the agents would still be physically interleaved on
screen — e.g. two untagged agents straddling `@name_level @m`, which the user can't read coherently. The only sane way
to produce a single banner per group is to gather members under it, and that requires reordering. So sorting is the only
fix that addresses both the visual split and the determinism complaint.

### Caller impact

- `agent_list.py` consumes `TreeEntry.agent_idx` and looks up `agents[i]` — `agent_idx` still points into the original
  list, so this caller is unchanged.
- `find_visible_ancestor_banner()` and `compute_banner_summary()` consume `GroupRow.agent_indices`; those continue to
  reference original positions. Unchanged.
- `_build_collapsed_tree` already de-dupes; running it on the sorted walk order makes its first-appearance ordering
  match the new deterministic policy too. Tiny, intentional change — it removes another source of recency-driven drift
  in the L0/L1/L2 views.
- The pinned panel (line 218–220 of `agent_list.py`) bypasses the tree entirely, so it is unaffected.

### Edge cases

- **Workflow children adjacency.** Workflow children inherit the parent's grouping keys, so they share a sort key with
  the parent. Stable sort by `(key, original_index)` preserves their original sequential ordering, which is exactly the
  parent → child run we need.
- **Singleton name-root suppression** (recently shipped via `suppress_singleton_name_root_banner.md`) is unaffected: the
  `>= 2` guard in `_build_full_tree` keys off `root_indices[...]`, which is built from all members regardless of walk
  order.
- **Empty agent list.** `walk_order` is `[]`; no behavior change.
- **All agents in one group.** `walk_order` ends up equal to `range(len(agents))` modulo stable-sort tiebreaks — no
  user-visible change.
- **Dismissed / hidden agents.** Filtering happens upstream; the tree builder only sees the post-filter list, so this
  fix is invisible to the dismiss/filter pipeline.

## Tests

New tests under `tests/ace/tui/models/test_agent_groups.py`:

1. `test_full_tree_does_not_split_untagged_group` — three agents with tags `("",), ("x",), ("",)`; expect exactly one
   `level=0` banner with key `("",)` and one with key `("x",)`. Order of `agent_idx` rows reflects the sorted walk.
2. `test_full_tree_sort_is_deterministic` — feed the same agents in two different input orders, assert identical
   `_kinds()` reductions and identical `group_key` sequences.
3. `test_full_tree_named_tags_sort_before_untagged` — tags `("beta",), (), ("alpha",)`; banner sequence is `@alpha`,
   `@beta`, `(untagged)`.
4. `test_full_tree_workflow_children_stay_with_parent_after_sort` — untagged parent + two workflow children, with an
   `@x`-tagged agent inserted between them in input order; the children render contiguously immediately after the parent
   under the `(untagged)` banner; the `@x` agent renders under its own `@x` banner.
5. `test_full_tree_singleton_name_root_still_suppressed_after_sort` — re-asserts the existing singleton suppression
   invariant after a reorder, so we don't accidentally regress that behavior.
6. `test_full_tree_reproduces_user_snapshot_shape` — synthesize the snapshot's roster shape (≈19 untagged agents
   spanning multiple name roots, plus one `@name_level` agent); assert exactly one `(untagged)` level-0 banner and one
   `@name_level` level-0 banner appear in the output.
7. `test_collapsed_tree_order_is_deterministic` — feed the same agents in two orders to
   `build_agent_tree(..., group_fold_level=2)`; assert identical banner sequences.

Existing assertions in `tests/ace/tui/models/test_agent_groups.py` that depend on input order (e.g.
`test_tag_change_emits_new_tag_banner`, lines 94–100) need to be updated to the new sort order — most use small,
already-sorted inputs so should pass unchanged, but any that don't will be updated to use the deterministic order.

## Files touched

- `src/sase/ace/tui/models/agent_groups.py` — primary change: compute `walk_order`, plumb it through both builders,
  build the index dicts in walk order so per-group tuples reflect display order. Update the module docstring's "banners
  may repeat" note to "groups render exactly once in deterministic order."
- `tests/ace/tui/models/test_agent_groups.py` — new tests above; minor updates to any order-sensitive existing test.

## Out of scope

- Banner visual style and labels (`(untagged)`, `(no project)` stay).
- Tag persistence, CLI, or registry changes.
- The pinned panel (already flat).
- Re-sorting agents _within_ a group beyond the existing recency tiebreaker.

## Open question for the user

**Should `(untagged)` sort first or last among tag groups?** The plan recommends **last** (named tags carry intent;
untagged is the "everything else" bucket), matching the docstring example in `plans/202604/agents_tab_nested_groups.md`.
Worth confirming before coding so we don't churn tests.
