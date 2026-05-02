---
create_time: 2026-05-01 12:14:12
status: done
prompt: sdd/prompts/202605/cls_by_date_subgroups.md
---
# CLs BY_DATE Second-Level Grouping

## Goal

Make the CLs tab's `by date` grouping more scannable by adding second-level headings where the current coarse buckets
become too broad:

- `Yesterday` groups by the same 4-hour windows used by the Agents tab.
- `This Week` groups by calendar day.
- `Earlier` groups by calendar week.

The design should preserve the existing CL grouping model, fold/navigation behavior, and visual language, while making
older work progressively coarser instead of dumping many CLs under one flat banner.

## Product Design

Keep the top-level BY_DATE buckets exactly as they are today:

1. `Today`
2. `Yesterday`
3. `This Week`
4. `Earlier`

Then add second-level headings only where they add meaningful structure:

- `Today`: remain flat, sorted newest first. Today is already the narrowest and highest-churn bucket; extra headings
  would make the active-work list noisier.
- `Yesterday`: add 4-hour windows, newest window first:
  - `8PM-12AM`
  - `4PM-8PM`
  - `12PM-4PM`
  - `8AM-12PM`
  - `4AM-8AM`
  - `12AM-4AM`
- `This Week`: add one heading per date, newest day first, with compact labels like `Fri Apr 24`.
- `Earlier`: add one heading per Monday-start calendar week, newest week first, with compact range labels like
  `Apr 13-19` and cross-month labels like `Mar 30-Apr 5`.
- CLs with no parseable TIMESTAMPS remain under top-level `Earlier`, inside a final `(no timestamp)` second-level
  heading.

This gives a useful visual rhythm: immediate work is dense, yesterday is time-of-day searchable, this week is day
searchable, and older work is week searchable.

## Technical Shape

### 1. Reuse the 4-hour window language

Create a small shared helper module for date/time subgroup labels rather than copying the Agents-tab literals into CL
code. The helper should provide:

- 4-hour window label creation from a `datetime`.
- A sort key for those window labels, newest window first.
- Day label creation for `This Week`.
- Monday-start week label creation for `Earlier`.
- Deterministic sort keys for day/week subgroups.

The existing Agents BY_DATE grouping should keep its current behavior and labels. If practical, switch its private
window-label/sort helper to the shared helper under test coverage; otherwise, keep the shared helper CL-focused and
leave Agents untouched.

### 2. Extend CL grouping keys

Extend the internal ChangeSpec grouping key to carry an optional BY_DATE subgroup:

- Existing `l0`: project/date/status.
- Existing `sibling_root`: project/status sibling grouping.
- New `date_subgroup`: only populated for BY_DATE when the L0 bucket is `Yesterday`, `This Week`, or `Earlier`.

Subgroup selection should use the same `latest_changespec_timestamp()` cache already used for BY_DATE bucketing and
sorting, so timestamp parsing remains one pass per refresh.

### 3. Build BY_DATE second-level rows

Update `build_changespec_tree()` and `enumerate_changespec_group_keys()` so BY_DATE can emit level-1 subgroup banners
under selected date buckets:

- L0 collapsed: hide all descendants as today.
- L1 collapsed: hide only CLs in that time/day/week subgroup.
- L1 keys should be shaped as `(date_bucket, subgroup_label)`, matching existing fold registry semantics.
- `Today` should not emit an L1 subgroup.
- BY_PROJECT and BY_STATUS behavior should remain unchanged.

Within BY_DATE sort order:

- L0: existing fixed date-bucket order.
- `Today`: latest TIMESTAMPS descending, unchanged.
- `Yesterday`: window sort newest first, then latest TIMESTAMPS descending.
- `This Week`: date sort newest first, then latest TIMESTAMPS descending.
- `Earlier`: week sort newest first, `(no timestamp)` last, then latest TIMESTAMPS descending.

### 4. Preserve rendering style

Reuse the existing CL banner renderer:

- L0 remains the strong sky-blue bucket banner.
- New L1 date subgroups reuse the secondary `▸` teal/dim rule treatment already used for sibling-root banners.
- Existing `N CLs` chips continue to appear on subgroup headings, which is enough information without adding a new
  visual system.

Update comments/docstrings to describe that BY_DATE now has conditional second-level headings.

### 5. Update help text

The help modal currently says Agents `by date` is sub-grouped by 4-hour windows. Add or adjust the CL grouping help
surface if there is an existing CL-specific section; otherwise leave global grouping copy concise and avoid implying
every BY_DATE bucket uses 4-hour windows.

Recommended wording where applicable:

`CL by date: yesterday by 4h, this week by day, earlier by week`

## Test Plan

Add focused model tests under `tests/ace/tui/models/test_changespec_groups_*`:

- Timestamp subgroup helper tests:
  - all six 4-hour boundary windows for `Yesterday`;
  - day label/sort for `This Week`;
  - week label/sort for same-month, cross-month, and cross-year weeks;
  - `(no timestamp)` sorts last in `Earlier`.
- BY_DATE layout tests:
  - `Today` remains L0-only and newest-first;
  - `Yesterday` emits L1 4-hour banners in newest-window-first order;
  - `This Week` emits L1 day banners newest-first;
  - `Earlier` emits L1 week banners newest-first plus `(no timestamp)` last;
  - collapsing a BY_DATE L1 subgroup hides only that subgroup;
  - `enumerate_changespec_group_keys()` includes the new L1 BY_DATE keys.
- Regression tests:
  - BY_PROJECT sibling grouping unchanged;
  - BY_STATUS sibling grouping unchanged;
  - grouped widget rendering now shows BY_DATE L1 banner rows and maps them correctly.

Run:

1. `just install`
2. focused pytest for ChangeSpec grouping/widget tests
3. `just fmt-py`
4. `just check`

## Files Expected To Change

- `src/sase/ace/tui/models/changespec_groups/_buckets.py`
- `src/sase/ace/tui/models/changespec_groups/_keys.py`
- `src/sase/ace/tui/models/changespec_groups/_tree.py`
- `src/sase/ace/tui/models/changespec_groups/__init__.py`
- possibly a new shared helper under `src/sase/ace/tui/models/`
- possibly `src/sase/ace/tui/models/agent_groups/_buckets.py` / `_keys.py` if reusing the shared window helper is
  low-risk
- `src/sase/ace/tui/widgets/_changespec_list_banner.py` comments/docstrings only, unless rendering needs mode-aware
  wording
- relevant help text if a CL grouping line exists
- `tests/ace/tui/models/test_changespec_groups_buckets.py`
- `tests/ace/tui/models/test_changespec_groups_layout.py`
- `tests/ace/tui/widgets/test_changespec_list_grouped.py`
- possibly the Agents date-window tests if a helper extraction touches Agents

## Risks And Mitigations

- Fold/navigation regressions: keep group keys tuple-shaped and use the existing tree entry model, then cover collapsed
  L1 BY_DATE behavior.
- Timestamp parsing overhead: reuse `precompute_latest_timestamps()` and pass the map through key and sort helpers.
- Visual clutter: deliberately keep `Today` flat and use the existing L1 banner style for the new headings.
- Ambiguous week boundaries: use Monday-start calendar weeks consistently and cover boundary labels with deterministic
  tests.
