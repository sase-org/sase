---
create_time: 2026-04-28 10:20:09
status: done
prompt: sdd/prompts/202604/reorder_status_groups.md
---
# Plan — Reorder Status Groups in the ACE CLs Tab

## Goal

When the user groups the ACE CLs tab by status, the L0 group banners should render in this order:

1. **Mailed** (top — CLs out for review, awaiting response)
2. **Ready** (CLs ready to mail)
3. then the remaining lifecycle order: **WIP → Draft → Submitted → Reverted → Archived**

Today the order follows the canonical ChangeSpec lifecycle:
`WIP → Draft → Ready → Mailed → Submitted → Reverted → Archived`, so `Mailed` and `Ready` show up _below_ `Draft`. The
user's day-to-day workflow surfaces the actionable buckets ("CLs I'm waiting on", "CLs I should mail next") at the top
instead.

## Why Just a Tuple Reorder

Status group order is driven by a single fixed tuple, `_STATUS_LIFECYCLE`, in
`src/sase/ace/tui/models/changespec_groups/_buckets.py`. The `status_sort_index()` helper returns
`(_STATUS_LIFECYCLE.index(base), status)` as the sort key, and that key is the only input the tree builder
(`_keys.walk_order` → `_l0_sort_key`) uses for `BY_STATUS` ordering.

So the entire visual change is "swap the tuple order." Suffixed labels (`"Ready - (!: REVIEWERS PENDING)"`) keep
grouping with their base via the existing `_base_status()` strip; unknown statuses still sort last alphabetically. No
bucketing logic, tree-build code, or rendering code needs to change.

## Proposed Order

```python
_STATUS_LIFECYCLE: tuple[str, ...] = (
    "Mailed",
    "Ready",
    "WIP",
    "Draft",
    "Submitted",
    "Reverted",
    "Archived",
)
```

`Mailed` and `Ready` move to the top (in that order); the rest preserve their relative lifecycle ordering. Terminal
states (`Submitted`, `Reverted`, `Archived`) stay at the bottom where they're least likely to need attention.

## Naming Note

The constant is named `_STATUS_LIFECYCLE` and its docstring/comment frame it as "lifecycle order." After this change the
order is no longer strictly the lifecycle — it's the display order for the CLs tab. Rename to `_STATUS_DISPLAY_ORDER`
and rephrase the comment to "display order for the `BY_STATUS` group; surfaces actionable buckets first." This keeps
future readers from "fixing" the tuple back to lifecycle order.

## Files to Touch

1. `src/sase/ace/tui/models/changespec_groups/_buckets.py`
   - Reorder the tuple.
   - Rename `_STATUS_LIFECYCLE` → `_STATUS_DISPLAY_ORDER` and refresh the surrounding comment + the `status_sort_index`
     docstring (currently says "Lifecycle-order sort key"; should say "Display-order sort key … see
     `_STATUS_DISPLAY_ORDER` for rationale").

2. `tests/ace/tui/models/test_changespec_groups_buckets.py`
   - `test_status_sort_index_follows_lifecycle_order` is the test that pins the ordering. Rename it (e.g.
     `…follows_display_order`), update its docstring, and update the expected sequence to
     `Mailed, Ready, WIP, Draft, Submitted, Reverted, Archived`. The `indices == sorted(indices)` and
     `indices == list(range(7))` assertions stay correct against the new sequence.
   - The other tests (`…groups_suffixed_variants_with_their_base`, `…unknown_sorts_after_known`, etc.) are independent
     of order and should keep passing untouched.

## What I Explicitly Won't Change

- Bucketing (`status_bucket_for_changespec`): still returns the literal `cs.status` string so suffix annotations like
  `" - (!: REVIEWERS PENDING)"` remain visible in the banner.
- Tree-build code in `_tree.py` / `_keys.py`: it consumes `status_sort_index()` opaquely, so reordering the tuple is
  enough.
- `BY_DATE` ordering or `BY_PROJECT` ordering: out of scope.
- Documentation outside the affected module: I'll search for any user-facing docs that pin the ordering, but the
  lifecycle docs in `glossary.md` are about the ChangeSpec state machine itself (which is unchanged), not the ACE
  display order, so they should stay as-is.

## Validation

1. `just check` (lint + mypy + tests) — must pass.
2. Manually scan for any other module referencing `_STATUS_LIFECYCLE` (rename will surface any stragglers); fix imports
   if found.
3. Optional: open `sase ace`, switch the CLs tab to `BY_STATUS`, confirm `Mailed` and `Ready` banners render at the top
   in that order. (Reported as "manual UI step" if the agent can't drive the TUI interactively.)

## Risk

Very low. The change is a tuple reorder + rename in one tightly scoped module, with one test that needs to be re-pinned
to the new ordering. No runtime data, file format, or persisted state is affected — refreshing the TUI is enough to see
the new order.
