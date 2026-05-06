---
create_time: 2026-05-06 12:58:30
status: done
prompt: sdd/prompts/202605/live_runtime_clock.md
---
# Live Runtime Clock Marker Plan

## Context

The Agents tab already has a focused runtime model:

- `src/sase/ace/tui/models/agent_time.py` computes whether a row displays a runtime suffix and whether that suffix can
  tick every second.
- `runtime_suffix_ticks(agent)` is the existing live-update predicate used by `AgentList.patch_active_runtime_rows()`.
- `src/sase/ace/tui/widgets/_agent_list_render_layout.py` builds the right-aligned runtime suffix text.
- `src/sase/ace/tui/widgets/_agent_list_render_cache.py` includes quantized `now` in cache keys only for rows where
  `runtime_suffix_ticks(agent)` is true.
- `tests/ace/tui/widgets/test_agent_list_runtime.py` already covers active, terminal, waiting, workflow-child, and
  approved-parent runtime behavior.

The requested UI change is presentation-only: add a small live marker to the left of any runtime that is actively being
incremented live every second. The key product rule is that the marker must mean "this row is on the one-second patch
path", not merely "this row has an elapsed duration".

Implementation note: the visible marker was later changed from the originally planned clock emoji to the gendered
running-man marker `🏃‍♂️` so the UI reads as an actively running runtime rather than only a ticking clock.

## Proposed Behavior

Rows whose runtime suffix is live-ticking render the suffix with a running-man marker immediately before the elapsed duration:

- Running row: `🏃‍♂️ 38m45s`
- Waiting row that has already started running: `🏃‍♂️ 5m`
- Retrying row: `🏃‍♂️ 12s`
- Approved workflow parent whose visible runtime is still advancing: `🏃‍♂️ 1m`
- Running workflow child with `step_type == "agent"`: `🏃‍♂️ 2m05s`

Rows that have a static runtime suffix do not get the marker:

- Terminal rows with finish timestamp: `20:17:03 · 6h17m`
- Terminal prompt-step agent rows: `14:02:30 · 1m30s`
- `WAITING` rows that have not reached `run_start_time`: no runtime suffix
- Non-agent workflow children (`bash`, `python`): no runtime suffix
- Any row with an elapsed value that is not patched by the one-second live path

## Design

Use `runtime_suffix_ticks(agent)` as the sole marker eligibility predicate. That keeps marker ownership aligned with the
already-tested one-second row patch path:

- `AgentList.patch_active_runtime_rows()` uses `runtime_suffix_ticks()` to choose rows to patch every second.
- `_agent_list_render_cache._runtime_signature()` already treats those rows as time-sensitive.
- The new marker should be emitted only when that same predicate is true.

Keep `compute_row_runtime()` unchanged. It should remain a model/helper function that returns timing facts: finish
timestamp and elapsed duration. The marker is visual chrome and belongs in the rendering layer.

Implement the marker in `build_runtime_suffix()` in `_agent_list_render_layout.py`:

- Import `runtime_suffix_ticks` from `agent_time`.
- After `compute_row_runtime()` returns a visible suffix, calculate `is_live = runtime_suffix_ticks(agent)`.
- If `is_live` and `elapsed is not None`, prepend the marker before the elapsed portion.
- Do not prepend before timestamp/date parts on terminal rows, because terminal rows do not tick.
- Use a dedicated style constant for the marker, likely a dim/neutral or soft gold style that distinguishes it without
  competing with status colors.

Emoji width can vary across terminal fonts. Rich `Text.cell_len` is already used throughout suffix alignment, so the
implementation should rely on `Text.cell_len` rather than manual `len()` math. The marker should be a stable literal
plus a following space, currently `🏃‍♂️ `, and all alignment tests should assert rendered suffix content rather than
hard-coded total width for emoji internals.

## Test Plan

Update `tests/ace/tui/widgets/test_agent_list_runtime.py`:

1. Active rendering:
   - Change `test_format_agent_option_active_suffix_contains_only_elapsed` to expect the marker-prefixed live suffix.
   - Add or update coverage for `WAITING` with `run_start_time`, `RETRYING`, and active approved parent statuses if
     existing tests do not already assert rendered suffix text.

2. Static rendering:
   - Keep terminal finished suffix expectations unchanged.
   - Keep terminal prompt-step agent suffix expectations unchanged.
   - Keep non-agent workflow child and pure waiting rows unchanged.

3. Patch path:
   - Update active row patching assertions so before/after rows end with `🏃‍♂️ 59s` and `🏃‍♂️ 1m`.
   - Preserve assertions that row count and marker state survive single-row patching.
   - Keep skip tests for terminal and pre-run waiting rows unchanged.

4. Alignment:
   - Update the right-alignment test so the live row includes the marker while the terminal row does not.
   - Continue asserting equal rendered cell widths or, if terminal emoji width varies in CI, assert suffix right-edge
     behavior through Rich cell lengths instead of Python string length.

## Verification

After implementation:

1. Run the focused runtime tests:
   - `.venv/bin/python -m pytest tests/ace/tui/widgets/test_agent_list_runtime.py`

2. Because this repo's memory requires full validation after source changes:
   - `just install`
   - `just check`

## Non-Goals

- Do not change runtime duration math.
- Do not change which rows are patched every second.
- Do not add backend or Rust-core behavior; this is Textual presentation only.
- Do not add marker state to the `Agent` model.
- Do not mark static elapsed durations that only update on normal refreshes.
