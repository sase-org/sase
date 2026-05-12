---
create_time: 2026-05-12 11:52:40
status: done
prompt: sdd/prompts/202605/axe_chop_when_full_time.md
---
# Plan: Show Full Time In AXE Chop Header

## Goal

When a chop row is selected on the AXE tab, change the top status header's `When:` field from the current relative-only
value, such as `1h ago`, to:

```text
HH:MM:SS (<relative_time>)
```

For example:

```text
When: 14:05:09 (1h ago)
```

The `<relative_time>` portion should remain the exact relative formatting currently used by that field.

## Current Implementation

The selected-chop header is rendered by `src/sase/ace/tui/widgets/axe_dashboard.py` in
`_AxeStatusSection._render_chop_display`.

The current `When:` field appends:

```python
_format_relative_time(entry.started_at)
```

That helper is imported from `src/sase/ace/tui/widgets/_axe_dashboard_render.py`, where AXE dashboard time formatting
helpers already live.

`ChopRunEntry.started_at` values produced by normal chop execution are timezone-aware ISO timestamps from
`datetime.now(get_timezone()).isoformat()`. Some tests intentionally use naive timestamps and currently get the existing
`unknown` fallback from relative-time formatting.

## Proposed Design

Add a small formatter in `_axe_dashboard_render.py`, likely named `format_time_with_relative`, that:

1. Parses the ISO timestamp using the same `datetime.fromisoformat` path as the existing helpers.
2. Converts aware timestamps to `get_timezone()` before rendering the clock time, so the TUI shows local SASE time
   consistently.
3. Formats the clock portion with `strftime("%H:%M:%S")`.
4. Reuses `format_relative_time(iso_timestamp)` for the parenthesized value, so the relative text stays byte-for-byte
   aligned with the current `When:` behavior.
5. Preserves the existing invalid/unparseable fallback as `unknown`.

For timestamps that parse but cannot produce a meaningful current relative value under the existing helper, keep the
behavior conservative by returning `unknown` rather than introducing a new partial format. This avoids changing
edge-case semantics while still implementing the desired display for normal timezone-aware chop timestamps.

## Implementation Steps

1. Update `_axe_dashboard_render.py` with the new formatter and a focused docstring.
2. Import the formatter into `axe_dashboard.py` next to `_format_relative_time`.
3. Change only the selected-chop header `When:` append in `_AxeStatusSection._render_chop_display` to use the new
   formatter.
4. Leave lumberjack overview tables, activity summaries, and other relative-time displays unchanged.
5. Add focused unit coverage in `tests/ace/tui/widgets/test_axe_dashboard_chop_detail.py`:
   - a normal aware timestamp renders `When: HH:MM:SS (<current relative>)`;
   - invalid or otherwise unsupported timestamp input remains `When: unknown`.
6. Run the focused test file first.
7. Because this repo's instructions require it after code changes, run `just install` if needed, then `just check`
   before final response.

## Risks And Mitigations

- The status header is a single no-wrap line with ellipsis overflow. The new field is longer, but the widget already
  truncates safely, and this change is limited to the selected chop view requested by the user.
- Visual PNG snapshots for AXE chop detail may shift because the header text is longer. Run visual tests or `just check`
  to catch snapshot impact; update snapshots only if the rendered change is intentional and required by the test
  workflow.
- Avoid changing core/backend timestamp logic. This is presentation-only TUI formatting, so the change belongs in the
  Python TUI widget helpers.
