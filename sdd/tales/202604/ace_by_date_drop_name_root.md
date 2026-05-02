---
create_time: 2026-04-27 10:18:33
status: done
prompt: sdd/prompts/202604/ace_by_date_drop_name_root.md
---
# Plan: `sase ace` "by date" grouping should not sub-group by base name

## Problem

In the `sase ace` TUI "Agents" tab, the `o` key cycles the L0 grouping mode through `STANDARD` ("by project") →
`BY_DATE` ("by date") → `BY_STATUS` ("by status").

Under `BY_DATE`, each panel currently lays out as:

```
Today                        ← L0 date bucket
  coder                      ← L1 name-root banner (suppressed if singleton)
    coder.foo
    coder.bar
  solo
```

The "by date" mode reuses the same name-root grouping the "by project" mode uses for L2. The user's complaint: when
bucketing by date, the name-root banner is noise — within a date bucket, agents from the same base name are not a
meaningful unit. The user wants a **flat list within each date bucket** sorted by run time:

```
Today                        ← L0 date bucket
  coder.foo    09:32          ← newest first
  coder.bar    09:15
  solo         08:01
```

## Goals

1. Under `BY_DATE`, drop the name-root banner level entirely. A date bucket is followed directly by its agents — no L1
   banner anywhere in the bucket.
2. Sort agents within a date bucket by `start_time`, **newest first**, to match the bucket order (which is already
   newest-first: Today → Yesterday → This Week → Earlier).
3. Workflow children must remain adjacent to their parent (the existing invariant — a banner must never appear between a
   parent and its workflow steps). Children inherit their grouping anchor from the parent so they continue to sort with
   the parent and not by their own `start_time`.
4. Leave `STANDARD` and `BY_STATUS` modes untouched. The user's request is scoped to "by date"; `BY_STATUS` still
   benefits from the name-root banner (e.g. seeing all `coder.*` agents in a single Running group).

## Non-goals

- No change to date-bucket definition (Today/Yesterday/This Week/Earlier).
- No change to L0 ordering (still newest-bucket-first).
- No change to the cycle order, the keymap, or the persisted setting name.
- No change to fold-registry semantics for `STANDARD` / `BY_STATUS` keys.
- No new "secondary sort" UI — sort within a bucket is fixed at start_time-descending; the user is not asking for a
  configurable sort.

## Design

### Where the change lives

All three behaviors come together in `agent_groups.py`:

- **Drop name-root banners under BY_DATE**: change `_grouping_keys_for` so that when `mode is GroupingMode.BY_DATE`, the
  returned `name_root` is `""`. The downstream tree builder already suppresses banners for empty name-roots, so this
  single change removes the L1 banner without further plumbing.
- **Sort by start_time within a bucket**: extend `_walk_order` (and `_grouping_keys_for_agents`'s consumers as needed)
  with a per-mode tiebreak that, under `BY_DATE`, places agents in descending `start_time` order before falling back to
  input index. The natural shape: a new `_walk_tiebreak` value computed per-agent, combined into the existing sort key
  tuple as the slot just above the current `i` fallback.
- **Preserve parent/child adjacency**: the tiebreak for workflow children must use the **parent's** `start_time` (and a
  "child-after-parent" flag), so the child sorts immediately after its parent regardless of the child's own
  `start_time`. This mirrors the existing approach where workflow children inherit their parent's `_GroupingKeys`.

### Sketch of the new tiebreak

Per agent, compute:

```
anchor_start  = parent.start_time if workflow_child else agent.start_time
is_child      = 1 if workflow_child else 0
```

Under `BY_DATE`, the sort key for index `i` becomes:

```
(
  _project_sort_key(BY_DATE, k.project),       # bucket order, newest-first
  (0, ""),                                     # changespec slot (unused)
  (0, ""),                                     # name-root slot (always ungrouped)
  -anchor_start_epoch,                         # newest first within bucket
  is_child,                                    # parent before its child
  i,                                           # final stable fallback
)
```

`None` start times sort last within the bucket (they already land in "Earlier" via the bucket logic, so this is a
tiebreak among themselves).

For `STANDARD` and `BY_STATUS`, the new `anchor_start` / `is_child` slots collapse to constants (e.g. `(0, 0)`) so the
existing sort is unchanged.

### Why not also drop name-root under BY_STATUS?

BY_STATUS users care about "what's happening to my coder agents right now", so collapsing several `coder.*` rows into a
`coder` banner remains useful. The user did not ask for this and the `BY_STATUS` UX is not broken — leave it alone.

## Touch list (anticipated)

- `src/sase/ace/tui/models/agent_groups.py`
  - `_grouping_keys_for`: force `name_root=""` when `mode is BY_DATE`.
  - `_walk_order`: add the start_time / parent-anchor tiebreak (active under `BY_DATE`, no-op elsewhere). Needs the
    agent list itself, not just the keys, so the signature gains an `agents` parameter (or a parallel `anchors` list
    computed by the caller).
  - `enumerate_group_keys` and `build_agent_tree`: thread the agent list (or the parallel anchor list) into
    `_walk_order`. No L1 keys will be enumerated under `BY_DATE` because every name-root is empty.
- Tests in `tests/ace/tui/models/`:
  - `test_agent_groups_grouping_mode.py`:
    - `test_build_agent_tree_by_date_l1_key_extends_bucket` becomes "no L1 banner emitted under BY_DATE"; assert
      `l1_banners == []`.
    - `test_enumerate_group_keys_respects_grouping_mode`: drop the `("Today", "coder")` expectation.
    - Add: under BY_DATE, given `coder.foo` (09:00), `coder.bar` (10:00), `solo` (08:00) all today, the agent rows
      appear in order `coder.bar, coder.foo, solo` (newest first).
    - Add: workflow child stays adjacent to its parent under BY_DATE even when child's `start_time` is much later than
      parent's.
    - Existing BY_STATUS tests (e.g. `_groups_by_name_root_within_bucket`) continue to pass — that mode still emits L1
      banners.
- No widget-layer changes in `agent_list.py`: `build_agent_tree`'s output shape stays the same; banner rendering and
  tier-style computation already handle a 1-level (bucket-only) tree.

## Edge cases to cover in tests

- All agents in one date bucket, mix of dotted and dotless names → single bucket banner, no name-root banner, agents
  sorted newest-first by start_time.
- Parent (start 09:00) with workflow child (start 12:00) on the same day → parent appears immediately above child in the
  rendered list, parent ordered against other parents using its own 09:00 anchor.
- Mixed buckets (Today + Earlier) where the same base name appears in both → no name-root banner anywhere; each bucket
  lists its members independently in newest-first order.
- Agent with `start_time=None` → still buckets as "Earlier" and sorts after start_time-bearing entries within that
  bucket.

## Risks

- **Fold registry stale entries**: any persisted `("date-bucket", "name-root")` fold keys from before this change are
  now unreachable. Harmless — the registry treats unknown keys as expanded, and `enumerate_group_keys` no longer emits
  them so they cannot be looked up. No migration needed.
- **Signature change to `_walk_order`** is internal (single call site). No public-API impact.
- **Snapshot tests / golden TUI captures**: if any exist for `BY_DATE` panels, they will need refreshing. Check
  `tests/ace/tui/widgets/test_agent_list*` and any snapshot fixtures.

## Validation

- `just check` (lint + mypy + tests).
- Manual TUI smoke: launch `sase ace`, switch to Agents tab, press `o` until the status reads "by date", confirm a
  bucket containing two agents sharing a base name shows them as a flat sorted list with no intermediate banner; confirm
  a workflow parent and its children stay adjacent.
