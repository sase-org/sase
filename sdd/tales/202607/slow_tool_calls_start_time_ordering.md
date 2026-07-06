---
create_time: 2026-07-05 22:46:26
status: wip
prompt: sdd/prompts/202607/slow_tool_calls_start_time_ordering.md
---
# Plan: Order SLOW TOOL CALLS rows by command start time

## Problem

The SLOW TOOL CALLS section in the `sase ace` TUI (agent metadata panel and workflow-root detail view) currently orders
rows by **severity**, not by time — even though each row's leftmost column displays an `HH:MM:SS` start timestamp, which
makes the section look chronological when it isn't.

The current ordering is applied in two places:

1. **Per-source selection** — `select_slow_tool_calls()` in `src/sase/ace/tui/tools/slow.py` returns running calls first
   (longest elapsed first), then completed calls slowest-first.
2. **Cross-source merge** — `_select_sourced_slow_tool_calls()` in
   `src/sase/ace/tui/widgets/prompt_panel/_agent_slow_tools.py` merges all sources and re-sorts globally with the same
   rule: `(not is_running, -effective_duration_ms)`.

The user wants the section ordered by **command start time** instead, so it reads as a mini-timeline consistent with the
full `]` tools timeline (which sorts entries chronologically ascending via the reader's
`(_recorded_at_sort, _file_order)` key).

## Desired behavior

- Rows in the SLOW TOOL CALLS section appear in **ascending start-time order** (oldest first, newest last), matching the
  natural top-to-bottom reading of the timestamp column and the `]` tools timeline direction.
- The ordering is applied uniformly to both render surfaces (agent metadata header and `[workflow]` root detail), which
  already share the single renderer `append_slow_tool_calls_section()` — one sort change covers both.
- Running vs. completed status remains visible via the existing glyphs (`⏳`/`✔`/`✘`/`◼`) and the `● running` /
  `did not complete` badges; status no longer influences ordering.

### Truncation policy (interacts directly with the ordering change)

Today the section shows the first `MAX_VISIBLE_SLOW_TOOL_CALLS` (8) rows of the sorted list — which works because
severity-sorting puts the most important rows first. Naively keeping "first 8" under ascending start-time order would
instead keep the **oldest** rows and hide the newest — including still-running calls, defeating the section's primary
"what is my agent stuck on right now" purpose.

New policy when more than 8 calls qualify:

1. **Visible set selection** (before display ordering): all running rows are always kept; remaining slots (up to 8
   total) are filled with the most recently started non-running rows. Degenerate case: if running rows alone exceed 8,
   keep the 8 most recently started running rows.
2. **Display order**: the visible set renders in ascending start-time order.
3. **Overflow line**: unchanged in wording and position — `+ N more · press ] for the full tools timeline` at the
   bottom. ("more" stays accurate regardless of which rows were hidden; "earlier" would not be, since the running-row
   guarantee can hide rows chronologically between visible ones.)

### Tie-breaking

Calls can share the same start second (e.g. parallel child agents in root view). Sort deterministically by
`(start_time, source order index, entry.line_number)` so re-renders are stable.

## Technical design

### `src/sase/ace/tui/tools/slow.py`

- Add a `started_at: datetime` field to the frozen `SlowToolCall` dataclass, populated from the already-parsed UTC
  `start` inside `select_slow_tool_calls()` (no re-parsing downstream).
- Change `select_slow_tool_calls()` to return calls in ascending `started_at` order instead of the current
  running-first/duration-desc two-bucket sort. (Input entries arrive reader-sorted, but sorting explicitly on the parsed
  start keeps the contract independent of caller order.)
- Update the docstring to state the chronological contract.

### `src/sase/ace/tui/widgets/prompt_panel/_agent_slow_tools.py`

- `_select_sourced_slow_tool_calls()`: replace the `(not is_running, -duration)` merge sort with the ascending
  `(slow_call.started_at, source_index, entry.line_number)` sort, where `source_index` is the source's position in the
  `sources` tuple.
- `append_slow_tool_calls_section()`: replace the plain `slow_calls[:MAX_VISIBLE_SLOW_TOOL_CALLS]` slice with the
  visible-set selection described above (running rows guaranteed, most recent others fill, final ascending render
  order). Overflow line logic otherwise unchanged.
- No changes to row layout, chips, colors, summary line, threshold (`SLOW_TOOL_CALL_THRESHOLD_MS`), or the cap constant
  (`MAX_VISIBLE_SLOW_TOOL_CALLS`).

## Explicitly out of scope

- **No sase-core (Rust) changes.** Slow-call selection/rendering lives entirely in this repo's Python TUI layer (a
  documented, deliberate exception to the Rust-core boundary — see the existing slow-tool-calls plans in sdd/tales/).
  This change touches only that existing Python logic.
- No new keymaps, config values, or `default_config.yml` changes (ordering is passive display behavior).
- No help modal / footer changes — audited: no user-facing text describes the current ordering.
- No changes to the `]` tools timeline (already chronological) or to which calls qualify as slow.

## Testing

- `tests/ace/tui/tools/test_slow_selection.py`: replace `test_ordering_puts_running_first_then_slowest_completed` with a
  chronological-ordering test where running and completed calls interleave by start time (e.g. completed@14:00,
  running@14:01, completed@14:02 → asserted in that order regardless of durations).
- `tests/ace/tui/widgets/test_agent_slow_tools.py`:
  - Replace `test_slow_tools_section_sorts_running_first_across_sources` with a cross-source start-time ordering test (a
    later-started completed call from one source renders below an earlier-started running call from another).
  - Add a tie-break test: identical start seconds across two sources render in source order deterministically.
  - Update the existing cap/overflow test for the new visible-set policy, and add a case proving a long-running call
    that started before 8 newer completed calls is still visible (running-row guarantee) while the overflow line reports
    the hidden count.
- `tests/ace/tui/widgets/test_prompt_panel_header.py`: existing SLOW TOOL CALLS assertions are presence-based; verify
  they still pass, adjusting only if an assertion implicitly encoded the old order.
- No PNG visual goldens currently render the SLOW TOOL CALLS section (audited), so no golden churn is expected; confirm
  with `just test-visual`.
- Full `just check` before completion (run `just install` first).
