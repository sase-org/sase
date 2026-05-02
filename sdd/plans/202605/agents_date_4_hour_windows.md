---
create_time: 2026-05-01 12:04:35
status: done
prompt: sdd/prompts/202605/agents_date_4_hour_windows.md
---
# Plan: Agents by-date 4-hour windows

## Context

The Agents tab grouping model lives in `src/sase/ace/tui/models/agent_groups`. `GroupingMode.BY_DATE` currently builds a
two-level hierarchy:

1. Date bucket: `Today`, `Yesterday`, `This Week`, `Earlier`.
2. Time bucket: currently one-hour labels such as `09:00`.

The second level is produced by `hour_bucket_for()` in `_buckets.py`, threaded through `_GroupingKeys.hour`, sorted by
`_hour_sort_key()` in `_keys.py`, and rendered as a normal level-1 banner by `_tree.py`/`_agent_list_render_banner.py`.
Tests already cover anchor behavior for running vs terminal agents, workflow child inheritance, visible banner
enumeration, and TUI row structure.

## Goal

Change the `BY_DATE` second-level bucket size from one hour to 4-hour windows, matching user-facing windows like
`12AM-4AM`, `4AM-8AM`, `8AM-12PM`, `12PM-4PM`, `4PM-8PM`, and `8PM-12AM`.

The existing anchoring rule should remain unchanged:

- Terminal agents bucket by `stop_time`, falling back to `start_time`.
- Non-terminal agents bucket by `start_time`.
- Workflow children inherit their parent's grouping anchor.
- Agents without a usable anchor remain in `(no time)` and sort last.

## Approach

1. Introduce 4-hour window bucketing in `_buckets.py`.
   - Add a small formatter that floors `anchor.hour` to a multiple of 4 and emits the 12-hour range labels above.
   - Prefer a new semantic helper name such as `time_window_bucket_for()`.
   - Keep `hour_bucket_for` as a compatibility alias if existing code/tests or downstream imports still reference it.

2. Update sorting in `_keys.py`.
   - Replace the current `int(hour[:2])` sort with a label-aware window sort that orders real windows newest-first by
     their start hour: `8PM-12AM`, `4PM-8PM`, `12PM-4PM`, `8AM-12PM`, `4AM-8AM`, `12AM-4AM`.
   - Preserve `(no time)` sorting last and non-BY_DATE neutral sorting.

3. Update tree/enumeration terminology without changing tree shape.
   - The group key shape remains `(date_bucket, time_window_label)`.
   - The visible banner emission rule remains: real windows always render, while singleton `(no time)` stays suppressed.
   - Rename internal comments/docstrings from hour bucket/banner to time window where practical, while avoiding
     unnecessary churn.

4. Update user-facing help text.
   - `src/sase/ace/tui/modals/help_modal/bindings.py` should say by-date mode is sub-grouped by 4-hour windows instead
     of hour-of-day.
   - Adjust render-banner docs that currently identify BY_DATE L1 as `HH:00`.

5. Update tests.
   - Convert existing hour-bucket assertions to 4-hour window labels.
   - Add or adjust boundary coverage for the six expected windows, especially `12AM-4AM`, `12PM-4PM`, and `8PM-12AM`.
   - Keep regression coverage for terminal stop-time anchoring, workflow child inheritance, `(no time)` sorting,
     newest-window ordering, group-key enumeration, and widget row structure.

6. Verify.
   - Run focused pytest for the agent group model/widget tests touched.
   - Because this repo requires it after edits, run `just install` if needed and then `just check` before reporting
     back.

## Expected impact

This should only affect `GroupingMode.BY_DATE` on the Agents tab. Standard project/ChangeSpec grouping, status grouping,
agent ordering within a window, fold/collapse mechanics, and status summaries should remain unchanged.
