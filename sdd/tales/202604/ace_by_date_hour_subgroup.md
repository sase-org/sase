---
create_time: 2026-04-27 22:41:10
status: done
prompt: sdd/prompts/202604/ace_by_date_hour_subgroup.md
---
# Plan: Hour-of-day sub-grouping under BY_DATE in the `sase ace` Agents tab

## Goal

In the `sase ace` TUI Agents tab, the "by date" grouping strategy (`GroupingMode.BY_DATE`) currently buckets agents at
one level only — each agent lands in `Today` / `Yesterday` / `This Week` / `Earlier` and the bucket renders as a flat
newest-first list (the `name_root` sub-banner is intentionally suppressed under BY_DATE). The lists in `Today` and
`Yesterday` get long quickly, so the user wants a second level of grouping nested inside each date bucket that buckets
each agent by the **hour** of its anchor time:

- For **running / non-terminal** agents → hour-of-day of `start_time`.
- For **terminal** agents (`DONE` / `PLAN DONE` / `EPIC CREATED`) → hour-of-day of `stop_time`, falling back to
  `start_time` when `stop_time` is missing.

This matches the existing anchor-selection rule in `walk_anchors()` so the new hour banners agree with the sort order
already used inside each date bucket.

In user terms the resulting hierarchy is:

```
Level 1: date bucket    (existing)   — Today / Yesterday / This Week / Earlier
Level 2: hour bucket    (NEW)        — 14:00 / 13:00 / 12:00 / …
```

(In the code these correspond to `GroupRow.level == 0` and `GroupRow.level == 1`; the BY_DATE tree never had a `level=1`
banner before — the changespec level is unused in this mode and the `name_root` level is suppressed.)

## Product behavior

### Banner shape

Inside each date bucket, agents that share the same hour-of-day on their anchor render under a sub-banner labeled
`HH:00` (zero-padded, 24-hour, e.g. `14:00`, `09:00`). The banner uses the same visual treatment as the existing
name-root sub-banner (`▸ ` branch glyph, teal label, dim-gray rule) — they live at the same level (L1 in code, L2 in
user vocabulary), and reusing the styling avoids inventing a new visual register on a tab that already has three
(project bar, ChangeSpec bar, name-root branch).

### Singleton suppression

If an hour bucket contains exactly one agent, no banner is emitted — the agent renders directly under its date banner.
This mirrors the existing rule for `name_root` banners: a sub-banner labeling a single-row group is noise.

### Cross-day collisions inside `Earlier`

The `Earlier` date bucket spans every agent older than seven days, so two agents with the same hour-of-day but different
calendar dates land in the same `HH:00` sub-bucket. This is acceptable for v1 — the design intentionally trades calendar
precision for compactness inside the already-coarse `Earlier` bucket — but should be called out in the docstring for
`hour_bucket_for()` so a future contributor doesn't read it as a bug. (If this turns out to be confusing in practice, a
follow-up could fall back to a date-and-hour label inside `Earlier`, e.g. `Apr 18 09:00`. Out of scope for this change.)

### Missing anchor

Agents with no usable anchor time (no `start_time` and either no `stop_time` or non-terminal) get a synthetic
`(no time)` hour bucket, sorted last within the parent date bucket. These already exist exclusively in the `Earlier`
date bucket.

### Sort order

- Hour buckets within a date bucket sort **newest hour first** (e.g. `14:00` → `13:00` → … → `00:00` → `(no time)`).
- Inside an hour bucket the agent walk order is unchanged: still keyed off `walk_anchors()` (newest anchor first, with
  workflow children glued to their parent).

### Workflow children

Workflow children inherit grouping identity from their parent at every level, including the new hour bucket. A child
whose own `start_time` falls in a different hour than its parent still renders under the parent's hour banner,
immediately after the parent — consistent with the existing rule.

### Folding

The new hour-bucket banner participates in `AgentGroupFoldRegistry` automatically because the registry keys off
`GroupRow.group_key` tuples. Nothing tab-level needs to change to support collapsing an hour group.

### Sort/group cycle UX

The grouping-mode cycle (`STANDARD` → `BY_DATE` → `BY_STATUS`) is unchanged. The user accesses hour sub-grouping by
virtue of being in BY_DATE; there is no new key binding and no new cycle entry.

## Out of scope

- Configurable hour granularity (per-15-minute, per-2-hour, etc.).
- Renaming, removing, or otherwise restructuring the existing date buckets.
- Hour sub-grouping under `BY_STATUS`. (Calling out only because the same anchor logic could in principle apply; we are
  deliberately not doing it.)
- Time-zone handling. The TUI uses naive datetimes throughout; we match that.
- Showing the hour count inline with the date banner chip (e.g. "Today · 12 agents · 4 hours") — leave for a follow-up
  if asked.
- Tweaking the cycle order or adding a new GroupingMode.

## Technical design

### Anchor selection helper

Add a small private helper in `_buckets.py` that returns the hour-anchor `datetime` for an agent (the same time
`walk_anchors()` uses). `walk_anchors()` should be refactored to call this helper so the two implementations cannot
drift.

```python
def _hour_anchor_time(agent: Agent) -> datetime | None:
    if (agent.status or "") in _TERMINAL_STATUSES:
        return agent.stop_time or agent.start_time
    return agent.start_time
```

### `hour_bucket_for(agent)`

Public helper in `_buckets.py`:

```python
NO_HOUR_LABEL = "(no time)"

def hour_bucket_for(agent: Agent) -> str:
    """Map an agent's anchor time to an HH:00 bucket label.

    Uses ``stop_time`` for terminal agents (falling back to
    ``start_time`` when missing) and ``start_time`` otherwise — same
    rule as :func:`walk_anchors` so hour banners agree with the sort
    order inside each date bucket.

    Returns ``"(no time)"`` for agents with no usable anchor; that
    bucket sorts last within its date bucket.
    """
```

Lives next to `date_bucket_for` and `status_bucket_for`. Not gated on `now` because the hour is a pure function of the
agent.

### Keys

Extend `_GroupingKeys` in `_keys.py` with a 4th field:

```python
@dataclass(frozen=True)
class _GroupingKeys:
    project: str
    changespec: str
    name_root: str
    hour: str = ""        # NEW — populated only under BY_DATE
```

Default `""` keeps STANDARD / BY_STATUS callers behaviorally unchanged. `grouping_keys_for()` populates
`hour = hour_bucket_for(target)` when `mode is GroupingMode.BY_DATE` and `""` otherwise.

The choice to add a dedicated field rather than overloading the existing `name_root` slot is deliberate: `name_root`
semantics (dot-prefix of the agent name, used for STANDARD's L2) are entirely unrelated to hour-of-day, and overloading
would entangle two independent concepts in places (`_name_root_sort_key`, banner label selection) that already
special-case BY_DATE.

### Sort

`walk_order()` gains a sort tier between the L0 (date bucket) and the existing anchor tiebreak: an `_hour_sort_key()`
that orders hours descending (newest first) and parks `(no time)` after `00:00`.

```python
def _hour_sort_key(hour: str) -> tuple[int, int]:
    if hour == NO_HOUR_LABEL:
        return (1, 0)
    # "HH:00" → -HH so newer hours sort first.
    return (0, -int(hour[:2]))
```

Inserted in the sort-key tuple so the order is:

```
(project_sort, changespec_sort_or_(0, ""), hour_sort, name_root_sort, anchor, is_child, i)
```

Under non-BY_DATE modes `hour` is `""`, and we treat empty as neutral (`(0, 0)`) so the existing orderings are
byte-for-byte preserved.

### Tree builder

`build_agent_tree()` in `_tree.py` learns a new level. The cleanest shape:

- Track `cur_hour` alongside `cur_proj` / `cur_cs` / `cur_root`.
- When `mode is GroupingMode.BY_DATE` and `cur_hour` changes, emit a `GroupRow(level=1, group_key=(date_bucket, hour))`
  banner — but only if the hour group has 2+ members (singleton suppression, mirroring `root_indices`).
- The existing `name_root` branch stays unreachable under BY_DATE because `name_root` is `""` (already true today).

Index bookkeeping adds an `hour_indices` dict keyed by `(date_bucket, hour)`. The tree-walk update is mechanical and
parallel to the existing `root_indices` machinery.

### Banner label

`banner_label()` currently distinguishes 1-tuple (project) from N-tuple (anything deeper) and labels the latter by
`group_key[-1]`. Hour banners follow the same rule — `group_key = (date_bucket, "14:00")`, suffix `"14:00"` is the human
label — so `banner_label()` needs no change, modulo a clarifying comment in its docstring listing hour banners as
another shape.

### Enumeration

`enumerate_group_keys()` mirrors the tree builder: when `mode is GroupingMode.BY_DATE`, after emitting each L0
date-bucket key, emit the corresponding `(date_bucket, hour)` keys whose hour group has 2+ members.

### Banner rendering

`format_banner_option()` in `src/sase/ace/tui/widgets/_agent_list_render_banner.py` currently falls into the name-root
branch for any non-L0, non-changespec banner. That branch is exactly the visual style we want for hour banners, so no
rendering changes are strictly required. We will add a one-line comment noting that hour banners under BY_DATE share
this branch by design.

### Help modal

`?` help popup must list the new hour sub-grouping under the BY_DATE description. Per `src/sase/ace/AGENTS.md`, the help
popup must stay in sync, and `_BOX_WIDTH = 57` / `_CONTENT_WIDTH = 50` constraints apply. We'll touch
`src/sase/ace/tui/widgets/help_modal.py` to add a single line of text.

## Files to change

- `src/sase/ace/tui/models/agent_groups/_buckets.py` — new `hour_bucket_for()`, `_hour_anchor_time()` helper,
  `NO_HOUR_LABEL` sentinel.
- `src/sase/ace/tui/models/agent_groups/_keys.py` — extend `_GroupingKeys` with `hour`, populate under BY_DATE, add
  `_hour_sort_key()`, update `walk_order()` and `walk_anchors()` to share `_hour_anchor_time()`.
- `src/sase/ace/tui/models/agent_groups/_tree.py` — emit hour banner level inside BY_DATE in `build_agent_tree()` and
  `enumerate_group_keys()`.
- `src/sase/ace/tui/models/agent_groups/__init__.py` — export `hour_bucket_for`, `NO_HOUR_LABEL`.
- `src/sase/ace/tui/widgets/_agent_list_render_banner.py` — documentation comment only (no behavior change).
- `src/sase/ace/tui/widgets/help_modal.py` — one-line update to the BY_DATE help description.
- `tests/ace/tui/models/test_agent_groups_grouping_mode.py` — add hour-bucket unit tests and BY_DATE tree-shape tests
  (see below).

## Test plan

New cases in `test_agent_groups_grouping_mode.py` (or a sibling `test_agent_groups_hour_subgroup.py` if it grows):

- `test_hour_bucket_for_running_uses_start_time` — `start_time=09:30 → "09:00"`.
- `test_hour_bucket_for_terminal_uses_stop_time` — DONE with `start_time=07:30, stop_time=11:45 → "11:00"`.
- `test_hour_bucket_for_terminal_no_stop_falls_back_to_start_time`.
- `test_hour_bucket_for_no_anchor_returns_no_time_label`.
- `test_build_agent_tree_by_date_emits_hour_banner_under_date_bucket` — two same-hour agents in `Today` get a
  `("Today", "09:00")` L1 banner.
- `test_build_agent_tree_by_date_singleton_hour_no_banner` — one agent at 09:00 and one at 10:00 in `Today` produce no
  L1 banners.
- `test_build_agent_tree_by_date_hour_buckets_newest_first` — agents at 08:00 / 14:00 / 09:00 within `Today` render as
  `14:00 → 09:00 → 08:00`.
- `test_build_agent_tree_by_date_no_time_hour_sorts_last`.
- `test_build_agent_tree_by_date_workflow_child_inherits_parents_hour` — child at a different hour stays under the
  parent's hour banner.
- `test_build_agent_tree_by_date_terminal_and_running_share_hour` — a DONE agent with `stop_time=09:30` and a RUNNING
  agent with `start_time=09:15` cluster under the same `09:00` banner.
- `test_enumerate_group_keys_by_date_includes_hour_keys`.

Existing BY_DATE tests (e.g. `test_build_agent_tree_by_date_emits_no_name_root_banner`) must continue to pass —
`name_root` banners stay suppressed; the new banners are hour banners and live at the same level slot.

## Risks / things to double-check during implementation

- The sort-key tuple in `walk_order()` is shared across all modes; inserting a new tier requires that empty-string
  `hour` stays a no-op for STANDARD and BY_STATUS. The `_hour_sort_key("")` → `(0, 0)` choice handles this, but worth a
  regression test that STANDARD output is byte-identical (the existing
  `test_build_agent_tree_default_mode_matches_standard` already guards the shape).
- Render cache (`AgentRenderCache`) keys banner Options by `banner_render_key` — the new banners have a
  `(date, "HH:00")` group_key tuple, which is already hashable and distinct from existing keys, so no cache-key changes
  are needed.
- `find_visible_ancestor_banner()` picks the deepest ancestor by `level`. With hour banners at `level=1`, an agent's
  deepest ancestor banner will now be the hour banner (when emitted). This is the desired behavior for keymap-footer /
  focus targeting, but flagging for a sanity check during review.
