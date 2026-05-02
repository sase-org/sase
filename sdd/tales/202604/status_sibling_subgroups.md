---
create_time: 2026-04-28 10:29:31
status: done
prompt: sdd/prompts/202604/status_sibling_subgroups.md
---
# Plan — Sibling-Root Sub-Banners under `BY_STATUS` on the CLs Tab

## Goal

When the CLs tab is grouped by status, expose a second level of grouping that bundles `foobar_1` / `foobar_2`-style
sibling CLs together under a shared sub-banner inside each L0 status bucket — mirroring what `BY_PROJECT` already does
inside each project bucket.

The user described this as "L2 headings/groups for siblings when grouping by status." In our existing terminology the CL
tree only has banner levels `0` and `1` (L0 status / L1 sibling-root in `BY_PROJECT`). This plan adds the same `level=1`
sub-banner to `BY_STATUS`. Calling it "L2" in conversation is fine — in code it's `level=1`, the second hierarchical
tier — but the plan and tests will keep the existing `level=0` / `level=1` vocabulary so the model and docs stay
consistent.

## Current State

`BY_STATUS` on the CLs tab today is single-level:

- `_keys.keys_for_changespec()` populates `sibling_root` **only** when `mode is BY_PROJECT`; in `BY_STATUS` it's the
  empty string.
- `_keys.walk_order()` in `BY_STATUS` mode falls through to `(l0, i)` — siblings stay in input order, no grouping.
- `_tree.build_changespec_tree()` only emits an L1 sibling-root banner when `mode is BY_PROJECT and k.sibling_root`.
- `_tree.enumerate_changespec_group_keys()` matches: `BY_STATUS` enumerates only L0 keys.
- The agents-tab `BY_STATUS` mode already does sibling-root sub-grouping (`agent_groups/_tree.py`), so the visual
  precedent and the user's mental model are already established on the other tab.

## Proposed Design

### Level shape

```
L0  Mailed                       (status banner — already exists)
      foobar_1                   <- sibling-root suppressed (singleton)
L1    foobar  (suffix-grouped)   <- new: sibling-root sub-banner
        foobar_baz_1
        foobar_baz_2
      solo                       <- singleton, suppressed L1
L0  Ready
      ...
```

Suppression rule mirrors `BY_PROJECT`: emit the L1 banner **only** when 2+ visible CLs share the same sibling root
inside the same L0 status bucket. Singletons render directly under the status banner.

### Sort order inside a status bucket

Mirror `BY_PROJECT`:

1. Singletons first (so a "real" name like `solo` renders before grouped clusters).
2. Then grouped roots, alphabetized by lowercased root.
3. Within a grouped root, preserve input list order (stable).

This matches how `walk_order()` already builds `BY_PROJECT`'s `(l0, sibling, i)` key. We extend the existing
singletons-first branch from "`BY_PROJECT` only" to "`BY_PROJECT` or `BY_STATUS`".

### Group-key shape

L1 keys become `(status_label, sibling_root)`, parallel to `(project, sibling_root)` in `BY_PROJECT`. The
`GroupFoldRegistry` keys are arbitrary tuples so this drops in cleanly with no fold-storage changes.

Suffixed status labels (`"Ready - (!: REVIEWERS PENDING)"`) are bucketed verbatim today and keep that behavior — their
sibling sub-banner key will be `("Ready - (!: REVIEWERS PENDING)", "<root>")`, sharing the same suppression and sort
rules as plain statuses.

## Files to Touch

1. **`src/sase/ace/tui/models/changespec_groups/_keys.py`**
   - In `keys_for_changespec()`, populate `sibling_root` for **both** `BY_PROJECT` and `BY_STATUS`. (Leave `BY_DATE`
     alone — out of scope.)
   - In `walk_order()`, extend the existing "singletons first → grouped roots alphabetically" branch to fire under
     `BY_STATUS` as well. The status `_l0_sort_key` already returns the display-order index, so the L0 ordering is
     preserved; we just gain a sibling-aware secondary key.

2. **`src/sase/ace/tui/models/changespec_groups/_tree.py`**
   - `enumerate_changespec_group_keys()`: extend the `BY_PROJECT` branch (root counting + L1 emission with the 2+
     suppression rule) to also handle `BY_STATUS`. Cleanest is to widen the branch to "any mode that has a sibling
     level" rather than introducing parallel logic.
   - `build_changespec_tree()`: change the gate `if mode is ChangeSpecGroupingMode.BY_PROJECT and k.sibling_root:` to
     also accept `BY_STATUS`. Same for the `root_indices` accumulation loop above it. Singleton suppression / collapse
     handling already lives behind that gate and applies as-is.

3. **Docstrings / comments**
   - `_keys._ChangeSpecKeys.sibling_root` doc currently says "populated only in `BY_PROJECT` mode" — update.
   - `__init__.py` module docstring: under `BY_STATUS`, mention the sibling-root sub-banner with the same wording style
     used for `BY_PROJECT`.
   - `_tree.ChangeSpecGroupRow` docstring: it currently says "level is 0 for project / date / status banners and 1 for
     sibling-root banners (only emitted in `BY_PROJECT`)" — drop the `BY_PROJECT` parenthetical.

## Tests to Add / Update

In `tests/ace/tui/models/test_changespec_groups_layout.py`:

1. **New test — sibling sub-banner emitted under a status bucket.**  
   Build CLs `[foobar_1@WIP, foobar_2@WIP, solo@WIP]`, expect entries:
   - `("group", 0)` — `("WIP",)`
   - `("changespec", 2)` — `solo` first (singleton)
   - `("group", 1)` — `("WIP", "foobar")`
   - two `foobar_*` CLs

2. **New test — singleton root suppresses L1 banner under a status bucket.**  
   `[foobar_1@WIP, baz@WIP]` → no L1 banner; both CLs render directly under WIP.

3. **New test — sibling sub-banner is scoped to its status bucket.**  
   `[foobar_1@WIP, foobar_2@Mailed]` produces no L1 banner anywhere (the two siblings live in different L0 buckets, so
   each is a singleton inside its own bucket).

4. **New test — `enumerate_changespec_group_keys` includes only grouped sibling roots at L1.**  
   Mirror `test_by_project_enumerate_keys_includes_only_grouped_roots_at_l1`.

5. **New test — collapsed L1 sibling banner under status hides only its members.**  
   Mirror `test_collapsed_sibling_root_hides_only_its_members`, but with `BY_STATUS` and a `("WIP", "foobar")` collapse
   key.

6. **Update — `test_by_status_emits_only_l1_banners_in_display_order`.**  
   This name and assertion are now stale ("only L1 banners" — actually meaning only L0). Rename to
   `test_by_status_l0_banners_in_display_order` and either keep the `_group_keys(entries, 1) == []` check (because the
   test inputs are all unique names — no siblings) or replace it with explicit data that exercises both levels. I'll
   keep it as a pure L0-ordering test, with non-sibling names so the L1 list stays empty by design, and add the new
   tests above to cover the L1 cases.

`test_changespec_groups_buckets.py` is unaffected — it tests `_buckets.py` helpers, none of which change.

`test_changespec_groups_perf.py` should be re-run unchanged; the new sort key is the same shape as `BY_PROJECT`'s, so no
asymptotic change.

## Docs to Touch

`docs/ace.md` — the CL grouping table under "CL Grouping and Folding":

- `BY_STATUS` row: change the "Notes" cell from "L0 only — bucket from the literal `status` field, in lifecycle order."
  to wording parallel to `BY_PROJECT`: "Adds an L1 sibling-root sub-banner shared by `foobar_1` / `foobar_2` style
  suffixed siblings. Singletons suppress their L1 banner." Keep the bullet about display order.
- The `h` keymap row already says "on a collapsed L1 banner, escalate to its parent" — that behavior carries over for
  free, no doc change needed.

## What I Explicitly Won't Change

- **`BY_DATE` grouping.** Out of scope. (Adding a sibling-root level there is plausible but the user asked specifically
  about status. If it comes up later, it's a copy of this same change.)
- **Bucketing logic** (`status_bucket_for_changespec`, `_base_status`, `_STATUS_DISPLAY_ORDER`): unchanged. Status
  labels with `" - (!: ...)"` annotation suffixes still get their own L0 bucket, just like today.
- **`status_sort_index` / `_l0_sort_key`**: unchanged — L0 status display order from the previous reorder PR remains the
  source of truth.
- **Banner rendering** (`changespec_tree.py`-rendering widgets, gutter / fold-tier-guide visuals): the L1 banner under
  `BY_STATUS` reuses the exact same `level=1` row type, so renderers already know how to draw it. Worth a manual TUI
  pass to confirm but no widget code should need to change.
- **`GroupFoldRegistry`** persistence: keys are opaque tuples, no schema change.

## Validation

1. `just check` (lint + mypy + tests) — must pass. Existing tests stay green; new tests cover the new behavior.
2. Manual TUI: open `sase ace`, switch CLs tab to `BY_STATUS`, find a project that has `foobar_1` / `foobar_2`-style
   siblings sharing a status (e.g. two `Ready` siblings), confirm the L1 sub-banner renders, fold/unfold works with `h`
   / `l`, and the singleton suppression rule looks right.
3. Sanity: run `BY_PROJECT` again afterward to confirm no regression in the existing sibling rendering.

## Risk

**Low.** The change reuses an already-tested pattern (`BY_PROJECT`'s sibling-root level) and extends it to a second
mode. The fold registry, the tree-walk traversal, and the renderer are all level-agnostic. The only behavior change a
user could be surprised by is "my CLs reordered inside a status bucket" — singletons-first ordering is a deliberate
shift from "input order" to "input order, but grouped." That's the desired feature, not a regression, and it matches how
`BY_PROJECT` has always behaved.

## Open Questions

- **Naming nit:** the `_keys` docstring and `__init__.py` module docstring frame `sibling_root` as a `BY_PROJECT`-only
  field. After this change, the field is shared by `BY_PROJECT` and `BY_STATUS`. I'll rephrase to "populated for modes
  that emit a sibling-root sub-banner" rather than enumerate modes inline, so adding `BY_DATE` later is a pure code
  change.
- **Should singletons-first apply to `BY_STATUS`?** Yes — see "Sort order" above. Calling out explicitly because it's a
  subtle behavior shift from the current "input order" rule for `BY_STATUS`. If the user wants to preserve strict input
  order inside a status bucket (and only group siblings without reordering singletons), say so before I implement and
  I'll switch to a different sort key (`(l0, root_or_empty, i)`) that keeps singletons interleaved.
