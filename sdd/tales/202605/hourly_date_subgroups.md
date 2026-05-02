---
create_time: 2026-05-01 12:46:03
status: done
prompt: sdd/prompts/202605/hourly_date_subgroups.md
---
# Add 1-Hour Date Subgroups Under 4-Hour BY_DATE Headings

## Goal

Add a third heading level for 1-hour windows beneath existing 4-hour date-window headings when the CLs tab or Agents tab
is grouped by date.

User-facing behavior:

- CLs tab, `BY_DATE`:
  - `Today` should no longer be flat.
  - `Today` and `Yesterday` should render:
    - date bucket heading
    - 4-hour window heading
    - 1-hour heading
    - CL rows
  - `This Week` should keep day headings only.
  - `Earlier` should keep week headings plus `(no timestamp)` only.
- Agents tab, `BY_DATE`:
  - Every date bucket should render 1-hour headings under every real 4-hour heading.
  - `(no time)` remains a terminal synthetic bucket; do not add a meaningless child heading under it.
- The 1-hour heading title should be the zero-padded 24-hour start time, for example `09:00`, not a range such as
  `9AM-10AM`.

Internally, this is a code-level `level=2` group row because existing tree rows are zero-indexed (`level=0` for the
outer date bucket). It is the user's "level 3" in visible hierarchy terms.

## Current State

Shared date helpers live in `src/sase/ace/tui/models/date_subgroups.py`. They currently provide:

- `four_hour_window_label()` / `four_hour_window_sort_key()`
- day subgroup labels/sort keys
- week subgroup labels/sort keys
- `NO_TIMESTAMP_LABEL`

CL date grouping currently lives in:

- `src/sase/ace/tui/models/changespec_groups/_buckets.py`
- `src/sase/ace/tui/models/changespec_groups/_keys.py`
- `src/sase/ace/tui/models/changespec_groups/_tree.py`

CL `BY_DATE` currently emits:

- `Today`: flat under the date bucket
- `Yesterday`: 4-hour L1 headings
- `This Week`: day L1 headings
- `Earlier`: week L1 headings or `(no timestamp)`

Agents date grouping currently lives in:

- `src/sase/ace/tui/models/agent_groups/_buckets.py`
- `src/sase/ace/tui/models/agent_groups/_keys.py`
- `src/sase/ace/tui/models/agent_groups/_tree.py`

Agents `BY_DATE` currently emits date bucket -> 4-hour window. It uses `hour_anchor_time()` so terminal agents anchor on
`stop_time`, non-terminal agents anchor on `start_time`, and workflow children inherit their parent's grouping anchor.
The new hourly level must reuse that same anchor rule.

## Design

### Shared date helper

Add shared helper functions in `date_subgroups.py`:

- `one_hour_window_label(anchor: datetime) -> str`
  - Returns `f"{anchor.hour:02d}:00"`.
  - Examples: `00:00`, `09:00`, `23:00`.
- `one_hour_window_sort_key(label: str) -> tuple[int, int]`
  - Sorts real hourly labels newest-first within their 4-hour parent.
  - Unknown labels sort after real hourly labels.

Keep the existing 4-hour labels unchanged unless the user later asks to rename those headings too.

### CL model changes

Update CL grouping keys to carry two BY_DATE subgroup levels:

- Existing `date_subgroup` remains the first BY_DATE subgroup under the date bucket.
  - `Today`: 4-hour label
  - `Yesterday`: 4-hour label
  - `This Week`: day label
  - `Earlier`: week label or `(no timestamp)`
- Add a new field, for example `hour_subgroup`, populated only when `date_bucket in {"Today", "Yesterday"}` and the CL
  has a parseable latest timestamp.
  - Value is `one_hour_window_label(latest)`.

Update sorting:

- Sort L0 date buckets by existing fixed order.
- Sort 4-hour L1 headings newest-first for `Today` and `Yesterday`.
- Sort 1-hour L2 headings newest-first under each 4-hour heading.
- Preserve newest-first CL row order inside each 1-hour heading using the latest timestamp tie-break.
- Preserve existing day/week/no-timestamp sort behavior for `This Week` and `Earlier`.

Update `build_changespec_tree()` and `enumerate_changespec_group_keys()`:

- Emit `(bucket,)` L0 keys as today.
- Emit `(bucket, date_subgroup)` for all non-empty first-level BY_DATE subgroups.
- Emit `(bucket, date_subgroup, hour_subgroup)` only for `Today` / `Yesterday` hourly groups.
- Respect collapse at all three visible hierarchy levels:
  - Collapsed L0 hides L1/L2/CL rows.
  - Collapsed 4-hour L1 hides hourly L2/CL rows.
  - Collapsed hourly L2 hides only that hour's CL rows.

### Agents model changes

Extend agent BY_DATE keys with a separate hourly subgroup:

- Keep the existing `hour` field as the 4-hour window label for compatibility with current code and tests.
- Add a new field, for example `one_hour`, populated only for real anchored agents in `BY_DATE`.
  - Value is `one_hour_window_label(hour_anchor_time(target))`.
  - Empty for agents with no usable anchor, including the `(no time)` synthetic bucket.

Update sorting:

- Keep date bucket order unchanged.
- Keep 4-hour windows newest-first, `(no time)` last.
- Sort 1-hour headings newest-first within their 4-hour parent.
- Preserve the existing anchor tie-break and workflow child adjacency after the hourly key.

Update `build_agent_tree()` and `enumerate_group_keys()`:

- Emit existing `(date_bucket,)` L0 keys.
- Emit existing `(date_bucket, four_hour_window)` L1 keys using the current visibility rule:
  - real 4-hour windows always visible, even singleton
  - `(no time)` only visible when it has 2+ agents
- Emit `(date_bucket, four_hour_window, one_hour)` L2 keys under real 4-hour windows.
- Do not emit an L2 key below `(no time)`.
- Respect collapse at all levels:
  - Collapsed date bucket hides everything beneath it.
  - Collapsed 4-hour heading hides hourly headings and agents beneath it.
  - Collapsed hourly heading hides only that hour's agents.

### Rendering and row mapping

The existing banner label helpers already use the final group key segment for non-L0 labels, so hourly headings can
display `09:00` without special label formatting.

Update comments/docstrings so the hierarchy is clear:

- Agents:
  - `level=0`: date/status/project bucket
  - `level=1`: 4-hour window in BY_DATE, ChangeSpec/name-root elsewhere
  - `level=2`: 1-hour window in BY_DATE, name-root in STANDARD 3-level mode
- CLs:
  - `level=0`: project/date/status bucket
  - `level=1`: sibling root or first BY_DATE subgroup
  - `level=2`: hourly BY_DATE subgroup under Today/Yesterday

For Agents, update `compute_tier_styles()` so BY_DATE 4-hour headings contribute an ancestor guide to hourly headings
and agent rows. This keeps the visual hierarchy readable once BY_DATE has three visible levels.

For CLs, keep the existing banner renderer path unless implementation shows the level-2 row is visually ambiguous. If
needed, add a minimal level-aware indent while preserving the existing L0/secondary palette.

### Help text

Update help modal grouping descriptions:

- CLs: from "Yesterday by 4h, this week by day, older by week" to wording that mentions
  `Today/Yesterday by 4h then hour`.
- Agents: from "Sub-grouped by 4-hour windows" to wording that mentions `4-hour then hourly windows`.

## Tests

Add/update focused tests before broader checks:

Shared helper tests:

- `one_hour_window_label()` returns `00:00`, `09:00`, `23:00`.
- `one_hour_window_sort_key()` sorts newest-first and unknown labels last.

CL model tests:

- `Today` now emits 4-hour and hourly headings, with hourly labels like `09:00`.
- `Yesterday` emits 4-hour headings newest-first and hourly children newest-first.
- Collapsing an hourly key hides only that hour's CL rows.
- Collapsing a 4-hour key hides its hourly headings and CL rows.
- `enumerate_changespec_group_keys()` includes three-part hourly keys for `Today` / `Yesterday`.
- `This Week` and `Earlier` retain existing day/week/no-timestamp behavior and do not gain hourly children.

Agents model tests:

- Real 4-hour headings now contain hourly L2 headings in `Today`, `Yesterday`, `This Week`, and `Earlier`.
- Hourly headings sort newest-first within each 4-hour window.
- Workflow children inherit the parent's hourly key.
- Terminal agents use `stop_time` for the hourly key, falling back to `start_time`.
- `(no time)` has no hourly child.
- `enumerate_group_keys()` includes hourly 3-tuples for real windows only.
- Collapse tests cover both 4-hour and hourly keys.

Widget tests:

- CL widget row mapping includes hourly banner rows and resolves collapsed hourly banners to their 3-tuple group key.
- Agent widget row mapping includes hourly banner rows under BY_DATE.
- Existing row-count expectations that assumed CL `Today` was flat or Agents had only two BY_DATE levels should be
  updated.

Integration/help tests:

- Update integration expectations that count BY_DATE banners if they now include hourly rows.
- Add or update help text assertions if present.

## Verification

Because this workspace may have stale dependencies, run:

```bash
just install
```

Then run focused tests:

```bash
.venv/bin/python -m pytest \
  tests/ace/tui/models/test_changespec_groups_buckets.py \
  tests/ace/tui/models/test_changespec_groups_layout.py \
  tests/ace/tui/models/test_agent_groups_grouping_mode_hour.py \
  tests/ace/tui/models/test_agent_groups_grouping_mode_tree.py \
  tests/ace/tui/widgets/test_changespec_list_grouped.py \
  tests/ace/tui/widgets/test_agent_list_grouping_buckets.py
```

Then run formatting and the required full repo check:

```bash
just fmt
just check
```

## Risks and Decisions

- More headings mean more vertical space. This is intentional per request, but the implementation should avoid adding
  hourly children under synthetic no-time/no-timestamp groups.
- Existing fold keys for 4-hour Agent groups remain the same 2-tuples, so prior per-mode collapse state for those
  headings can still apply. New hourly fold state uses 3-tuples.
- CL `Today` changes from flat to grouped, so tests and any user expectations around row counts must change.
- The 1-hour title format is explicitly `HH:00`; do not use AM/PM ranges for this level.
