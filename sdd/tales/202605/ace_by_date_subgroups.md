---
create_time: 2026-05-04 18:38:49
status: done
prompt: sdd/prompts/202605/ace_by_date_subgroups.md
---
# Plan: Replace 4-Hour Window Subgroups in `sase ace` "By Date" Grouping

## Problem

Both the **Agents** tab and the **CLs** tab of `sase ace` support a "by date" grouping mode whose top-level (L1)
headings are date buckets:

```
Today
Yesterday
This Week
Earlier
```

Currently both tabs put a layer of **4-hour windows** ("12PM–4PM", "8AM–12PM", …) under those headings as their L2
sub-banner. The CLs tab is partially smarter — it already swaps the 4-hour layer for daily groups under "This Week" and
weekly groups under "Earlier" — but it still uses 4-hour windows under Today/Yesterday, with a third-level 1-hour
sub-banner beneath. The Agents tab uses 4-hour windows under every date bucket, with 1-hour sub-banners underneath.

The 4-hour window is doing no useful work:

- Under single-day buckets (Today/Yesterday) it is just a coarsened version of the 1-hour layer that already exists
  beneath it. Two layers for one piece of information is noise.
- Under "This Week" / "Earlier" on the Agents tab it actively misleads — agents from different calendar dates can land
  in the same "8AM–12PM" bucket (the existing source comment in `_buckets.py` explicitly calls this out as an
  intentional trade-off for compactness, but the user has decided the trade-off is wrong).

## Desired End State

Both tabs converge on the same date-aware subgroup scheme. Under any L1 date bucket, exactly **one** L2 subgroup layer
is rendered, chosen by the bucket:

| L1 bucket | L2 subgroup       | Example label |
| --------- | ----------------- | ------------- |
| Today     | 1-hour window     | `09:00`       |
| Yesterday | 1-hour window     | `14:00`       |
| This Week | Calendar day      | `Fri Apr 24`  |
| Earlier   | Monday-start week | `Apr 21-27`   |

The L2 layer follows the existing singleton-suppression rule (a banner is only emitted when its sub-bucket is
non-trivial), so a single agent / CL under a date bucket renders flat with no L2 banner.

The 4-hour window concept and its associated labels (`12AM-4AM`, `4AM-8AM`, …), sort keys, and tests are removed
entirely.

## Affected Code

### Shared utility

- `src/sase/ace/tui/models/date_subgroups.py`
  - Delete `four_hour_window_label`, `four_hour_window_sort_key`, the `_TIME_WINDOW_START_BY_LABEL` table, and the
    `_hour_label` helper if it is no longer used anywhere else.
  - Keep `one_hour_window_label`, `one_hour_window_sort_key`, `day_subgroup_label`, `day_subgroup_sort_key`,
    `week_subgroup_label`, `week_subgroup_sort_key`, and `NO_TIMESTAMP_LABEL`.

### CLs tab

- `src/sase/ace/tui/models/changespec_groups/_buckets.py`
  - In `date_subgroup_for_changespec`, swap `four_hour_window_label(latest)` for `one_hour_window_label(latest)` under
    the Today/Yesterday branch.
  - Remove `hour_subgroup_for_changespec` entirely.
  - In `date_subgroup_sort_key`, swap `four_hour_window_sort_key(subgroup)` for `one_hour_window_sort_key(subgroup)`
    under the Today/Yesterday branch.
  - Update the docstrings on `ChangeSpecGroupingMode.BY_DATE` and on `date_subgroup_for_changespec` to say "1-hour"
    instead of "4-hour".
- `src/sase/ace/tui/models/changespec_groups/_keys.py`
  - Drop the `hour_subgroup` field from `_ChangeSpecKeys`.
  - Stop populating `hour_subgroup` in `keys_for_changespec`.
  - In `walk_order`, drop the `hour` tier from the BY_DATE sort tuple (keeps L0 → L1 subgroup → CS-anchor → index).
  - Drop the now-unused `one_hour_window_sort_key` import.

### Agents tab

- `src/sase/ace/tui/models/agent_groups/_buckets.py`
  - Delete `time_window_bucket_for`, `one_hour_bucket_for`, and the `hour_bucket_for` compatibility alias.
  - Add a single `date_subgroup_bucket_for(agent, date_bucket)` helper that returns the appropriate L2 label by
    branching on the date bucket (mirroring `date_subgroup_for_changespec`):
    - Today / Yesterday → `one_hour_window_label(anchor)`
    - This Week → `day_subgroup_label(anchor)`
    - Earlier → `week_subgroup_label(anchor)`
    - Anchor missing → `NO_HOUR_LABEL` (renamed conceptually but the sentinel string `"(no time)"` is fine to keep for
      back-compat with fold registries).
  - Drop the lengthy comment in `time_window_bucket_for` about Earlier cross-day collisions — the new scheme fixes that
    case so the caveat is obsolete.
- `src/sase/ace/tui/models/agent_groups/_keys.py`
  - Replace the two fields `hour: str` and `one_hour: str` on `_GroupingKeys` with a single `date_subgroup: str`.
  - Replace `_hour_sort_key` / `_one_hour_sort_key` with one `_date_subgroup_sort_key(date_bucket, subgroup, anchor)`
    that mirrors the CLs tab's `date_subgroup_sort_key`.
  - Update `grouping_keys_for` to call the new helper and stash the result in `date_subgroup`.
  - Update `walk_order` to use the new sort key and drop the now-unused second hour tier from its tuple.
- `src/sase/ace/tui/models/agent_groups/_tree.py`
  - Collapse `cur_hour` / `cur_one_hour` and their `_indices` / `_collapsed` siblings down to a single `cur_subgroup`
    set of state variables.
  - Replace `_should_emit_time_window_banner` and `_should_emit_one_hour_banner` with one
    `_should_emit_date_subgroup_banner(subgroup, count)` predicate. The rule stays the same as today's outer time-window
    predicate: a real label always emits a banner; the synthetic `(no time)` label only emits when 2+ agents share it.
  - Update the docstrings on `build_agent_tree`, `enumerate_group_keys`, `GroupRow`, and the banner-label helpers so the
    references to "4-hour window" / "one-hour window" point at the new mixed subgroup layer. `banner_label` itself stays
    untouched — it just renders `group_key[-1]` and that still does the right thing.
- `src/sase/ace/tui/models/agent_groups/__init__.py`
  - Drop `hour_bucket_for`, `one_hour_bucket_for`, and `time_window_bucket_for` from the re-exports / `__all__`. Replace
    with the new `date_subgroup_bucket_for` if anything outside this package needs it (likely not — current external
    consumers only use it via the tree).

### Tests

- Delete `tests/ace/tui/models/test_agent_groups_grouping_mode_hour.py` (the entire file is dedicated to 4-hour window
  behavior). Move any still-useful cases (anchor-time selection, `(no time)` handling, banner-emission rules under
  singleton vs. multi-agent buckets) into a new `test_agent_groups_grouping_mode_subgroups.py` written against the new
  scheme. Cover at minimum:
  - Today bucket → 1-hour subgroup (`14:00`).
  - Yesterday bucket → 1-hour subgroup.
  - This Week bucket → calendar-day subgroup (`Fri Apr 24`).
  - Earlier bucket → Monday-start week subgroup (`Apr 21-27`).
  - Earlier bucket spans two weeks → two distinct L2 banners.
  - `NO_HOUR_LABEL` still suppressed when singleton.
  - Newest-first ordering preserved within each L1 bucket.
- Update `test_agent_groups_grouping_mode_date.py`, `_grouping_mode_keys.py`, `_grouping_mode_tree.py`, and
  `_agent_groups_helpers.py` for the new `_GroupingKeys` field name.
- Update `tests/ace/tui/models/test_changespec_groups_buckets.py` to assert 1-hour subgroup labels under Today/Yesterday
  and to drop assertions about the deleted `hour_subgroup_for_changespec` / `hour_subgroup` field.
- `tests/ace/tui/models/test_changespec_groups_layout.py` and `_perf.py` almost certainly reference the old layout —
  update accordingly.

### Help / docs

- `src/sase/ace/AGENTS.md` mentions the help popup must stay in sync with behavior; check `help_modal.py` for any
  literal mention of "4-hour" or "1-hour" subgroups under BY_DATE and adjust if present (the existing help text most
  likely speaks generically about "by date" grouping, in which case no change is needed).

## Implementation Order

1. Land the shared `date_subgroups.py` cleanup behind the new helpers, but keep `four_hour_window_*` temporarily — the
   order below removes them at the end so each step type-checks.
2. Update the **CLs tab** first (smaller blast radius — it already has the day/week branches, so the change is local to
   the Today/Yesterday branch plus dropping the hour sub-layer). Update CLs tests.
3. Update the **Agents tab** to mirror the CLs tab. This is the larger change: the `_GroupingKeys` shape changes,
   `walk_order`'s sort tuple shrinks, and `_tree.py` loses an entire banner level. Update Agents tests.
4. Once neither tab references `four_hour_window_label` / `four_hour_window_sort_key`, delete them from
   `date_subgroups.py`. Run `just check`.
5. Manually drive `sase ace` against a fixture set spanning Today, Yesterday, This Week (multiple days), and Earlier
   (multiple weeks) on both tabs. Confirm:
   - Today/Yesterday show only 1-hour banners under them, never `12PM-4PM`- style labels.
   - This Week shows day banners (`Fri Apr 24`).
   - Earlier shows week banners (`Apr 21-27`).
   - Singletons render flat under the date bucket on both tabs.
   - Fold/unfold works on the new L2 banners.

## Non-Goals / Out of Scope

- No change to L0 date bucket boundaries (Today / Yesterday / This Week / Earlier) or to which `start_time` /
  `stop_time` is used as the agent anchor.
- No change to BY_PROJECT or BY_STATUS modes.
- No change to STANDARD-mode project / ChangeSpec / name-root layout.
- Fold-registry keys for now-deleted 4-hour banners are silently abandoned on first refresh after the upgrade. They are
  stored per-session and are not load-bearing across refreshes, so no migration shim is needed.
