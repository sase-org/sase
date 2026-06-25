---
create_time: 2026-06-25 17:28:06
status: done
prompt: sdd/prompts/202606/move_pencil_after_runtime.md
---
# Plan: Move Agent Row Pencil After Runtime

## Goal

Move the file-change pencil glyph (`✏️`) in `sase ace` agent rows from immediately before the runtime suffix to
immediately after it, so the row reads as:

- Running: `🏃‍♂️ 1m23s ✏️`
- Finished: `Apr 24 20:17 · 38m45s ✏️`
- No runtime suffix: `✏️`

The pencil should remain in the right-side suffix column, not return to the left-side display-name/provider flow.
Provider badges, row status text, activity suffixes, unread markers, and user-paused markers should otherwise keep their
existing behavior.

## Current Behavior

The relevant rendering path is pure Python row formatting:

- `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
  - `format_agent_option(...)` builds `(left, suffix, option_id)`.
  - It currently calls `build_runtime_suffix(...)`, then wraps that suffix as `✏️ <runtime>` when
    `_has_file_change_hint(agent)` is true.
  - The wrapped runtime fragment is combined with any activity suffix through
    `combine_suffixes(build_activity_suffix(agent), runtime_with_file_change)`.
- `src/sase/ace/tui/widgets/_agent_list_render_layout.py`
  - `build_runtime_suffix(...)` owns the timestamp/elapsed/live marker text.
  - `combine_suffixes(...)` joins activity and runtime fragments with `·`.
  - `assemble_padded_option(...)` right-aligns the suffix column.
- `src/sase/ace/tui/widgets/_agent_list_render_cache.py`
  - `agent_file_change_hint(...)` decides whether the pencil renders.
  - `agent_render_key(...)` already includes diff/live-hint inputs, so this ordering-only change should not require
    cache-key changes.

This change is layout-only. It should not touch detection of file changes, live workspace diff classification, agent
loading, or the selective row-patch/full-rebuild machinery.

## Implementation Approach

1. In `format_agent_option(...)`, keep building the existing `runtime_suffix` first.
2. Replace the current “prepend pencil” wrapping logic with “append pencil” wrapping logic:
   - If the agent has no file-change hint, keep using the bare `runtime_suffix`.
   - If the agent has a file-change hint and `runtime_suffix.cell_len > 0`, create a new `Text` fragment containing the
     existing runtime suffix, then a single space, then the styled `_FILE_CHANGE_GLYPH`.
   - If the agent has a file-change hint and the runtime suffix is empty, create a fragment containing only the styled
     `_FILE_CHANGE_GLYPH`.
3. Continue feeding that fragment into `combine_suffixes(build_activity_suffix(agent), runtime_with_file_change)` so
   rows with activity still render as `<activity> · <runtime> ✏️`. The pencil remains the final element of the
   right-side metadata group.
4. Avoid introducing new I/O, refresh paths, or widget rebuild behavior. This is a pure `Text` assembly change and
   respects the TUI performance rule to keep row rendering on the existing fast path.

## Tests To Update Or Add

Update the existing focused row-rendering tests in `tests/ace/tui/widgets/test_agent_display_list_rendering.py`:

- Keep tests that assert the pencil is absent from `left.plain`.
- Keep no-runtime file-change cases expecting `suffix.plain == "✏️"`.
- Change running runtime ordering from `✏️ 🏃‍♂️ 1m23s` to `🏃‍♂️ 1m23s ✏️`.
- Change finished runtime ordering from `✏️ Apr 24 20:17 · 38m45s` to `Apr 24 20:17 · 38m45s ✏️`.
- Rename test names that currently say “precedes” so they describe the new “follows runtime” behavior.

Scan for other pencil suffix expectations and update only ordering assertions that depend on the previous placement. In
particular:

- `tests/test_agent_loader_status_override_tale.py` has no-runtime pencil expectations that should remain
  `suffix.plain == "✏️"`.
- Provider-placement tests should continue to assert provider emoji stays on the left and pencil stays out of the
  display-name flow.

If existing coverage does not cover marker-rich suffixes, add one small focused assertion for an unread or user-paused
runtime case only if needed after the first test run. The main requested behavior is already covered by running and
finished suffix tests.

## Validation

After implementation, run:

```bash
just install
pytest tests/ace/tui/widgets/test_agent_display_list_rendering.py tests/ace/tui/widgets/test_agent_list_runtime_rendering.py tests/test_agent_loader_status_override_tale.py
just check
```

`just check` is required for code changes in this repo. The change is small and pure-rendering, but if visual snapshot
tests fail through `just check`, inspect the diff and update goldens only if the only visual change is the intended
pencil relocation.

## Non-Goals

- Do not change what qualifies as a file-change hint.
- Do not change runtime timestamp/duration computation.
- Do not move provider/runtime badges on the left.
- Do not alter agent-list refresh, patching, or caching behavior beyond whatever cached rendered text naturally changes.
