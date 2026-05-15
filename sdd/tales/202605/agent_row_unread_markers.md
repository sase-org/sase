---
create_time: 2026-05-15 01:02:45
status: done
prompt: sdd/prompts/202605/agent_row_unread_markers.md
---
# Replace Agents Tab Unread Terminal Markers

## Goal

Replace the terminal-unread status markers in the `sase ace` Agents tab row suffix:

- non-failed terminal/unread rows: `😇` -> green check mark emoji (`✅`)
- failed terminal/unread rows: `😈` -> red X emoji (`❌`)

These markers live in the right-side runtime suffix slot for unread terminal rows. The existing placement should remain
unchanged so completed-unread rows still scan in the same column as live runtime markers.

## Current Behavior

The row rendering path is presentation-only TUI code:

- `src/sase/ace/tui/widgets/_agent_list_render_layout.py`
  - `_RUNTIME_UNREAD_DONE_MARKER = "😇 "`
  - `_RUNTIME_UNREAD_FAILED_MARKER = "😈 "`
  - `_unread_marker()` chooses the failed marker when `status_bucket_for_values(agent.status) == "Failed"`; otherwise it
    chooses the done marker.
- `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
  - combines activity and runtime suffixes for each row.
- Tests currently assert the old angel/devil glyphs in:
  - `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
  - `tests/ace/tui/widgets/test_agent_render_cache.py`

## Implementation Plan

1. Update the marker constants in `_agent_list_render_layout.py`:
   - use `✅ ` for non-failed unread terminal rows
   - use `❌ ` for failed unread terminal rows
   - revise the nearby comment so it describes completed/failed markers rather than angel/devil variants.

2. Keep suffix placement and whitespace behavior unchanged:
   - preserve trailing-space constants because elapsed suffixes render as `<marker> <duration>`
   - preserve `.rstrip()` use for marker-only suffixes so rows without runtime still render a single glyph.

3. Update focused tests that assert rendered suffix text:
   - all `😇` expectations become `✅`
   - all `😈` expectations become `❌`
   - negative assertions should check the new opposite marker where useful and stop referencing removed glyphs unless
     guarding absence of legacy glyphs is intentionally valuable.

4. Run focused verification first:
   - `just install` if this workspace is not already prepared
   - `pytest tests/ace/tui/widgets/test_agent_list_runtime_rendering.py tests/ace/tui/widgets/test_agent_render_cache.py`

5. Run repo-required verification after code changes:
   - `just check`

## Notes

The requested check mark and red X are emoji glyphs. Their terminal color is usually intrinsic, but the existing Rich
style can remain as a fallback for terminals that render text-style emoji.
