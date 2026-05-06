---
create_time: 2026-05-06 13:08:22
status: done
prompt: sdd/prompts/202605/running_man_runtime_marker.md
---
# Running Man Runtime Marker Plan

## Goal

Replace the live runtime suffix marker from the clock emoji to a running-man emoji while preserving the existing
behavior: only runtime suffixes that already tick every second should show the marker, and terminal/static elapsed
suffixes should remain unchanged.

## Recommendation

Use the exact gendered running-man sequence `🏃‍♂️ ` for the visible marker because the user asked for a man running rather
than the generic runner. Rich reports the marker plus trailing space as the same display width as the current clock
marker plus trailing space, so the existing right-alignment strategy should continue to work:

- `🕒 `: 3 cells
- `🏃 `: 3 cells
- `🏃‍♂️ `: 3 cells

There is one practical tradeoff: `🏃‍♂️` is a zero-width-joiner emoji sequence, so older terminals or fonts may render it
as multiple glyphs instead of one composed emoji. If terminal compatibility becomes more important than exact gendered
semantics, the fallback should be the generic runner `🏃 `, which is a simpler single-codepoint emoji and has the same
Rich cell width.

## Scope

1. Update `src/sase/ace/tui/widgets/_agent_list_render_layout.py`.
   - Change `_RUNTIME_LIVE_MARKER` from `🕒 ` to `🏃‍♂️ `.
   - Keep `_RUNTIME_LIVE_MARKER_STYLE` unchanged unless the new glyph reads poorly during manual inspection.
   - Keep `runtime_suffix_ticks(agent)` as the only marker eligibility predicate.

2. Update focused runtime rendering tests in `tests/ace/tui/widgets/test_agent_list_runtime.py`.
   - Replace active/ticking suffix expectations from `🕒 ...` to `🏃‍♂️ ...`.
   - Keep terminal/static elapsed expectations unchanged.
   - Preserve the alignment assertion that compares Rich `Text.cell_len`, because Python string length is misleading for
     emoji and ZWJ sequences.
   - Rename `test_format_agent_option_live_suffix_has_clock_marker` to describe a live marker rather than a clock
     marker.

3. Update the completed tale `sdd/tales/202605/live_runtime_clock.md`.
   - Add a short note that the implemented visual marker was changed from the originally planned clock to `🏃‍♂️`.
   - Update examples that show `🕒` so future readers do not treat the stale examples as the intended UI.
   - Leave the tale status as `done` if this is implemented directly as a small follow-up to the approved work.

## Validation

Run the focused runtime suite first:

```bash
.venv/bin/python -m pytest tests/ace/tui/widgets/test_agent_list_runtime.py
```

Because this repo's memory says to refresh the editable install before full validation when files change, run:

```bash
just install
just check
```

## Non-Goals

- Do not change duration math, timestamp formatting, live-row patching, or the status predicates.
- Do not introduce runtime-specific behavior.
- Do not move this into `../sase-core`; this is presentation-only TUI rendering.
