---
create_time: 2026-05-09 17:10:10
status: done
---
# Plan: Give the Agents Tab Read Count a Chromatic Color

## Context

The Agents tab top info strip is rendered by `AgentInfoPanel` in `src/sase/ace/tui/widgets/agent_info_panel.py`. Its
`_COUNT_STYLES` map gives each count type a bold Rich color:

- total: `#5FAFFF`
- asking: `#FFAF00`
- running: `#00D7AF`
- waiting: `#AF87FF`
- failed: `#FF5F5F`
- unread: `#FFAF5F`
- read: `#BCBCBC`

The `read` metric is the only count rendered in a grey tone. Tests in `tests/ace/tui/widgets/test_agent_info_panel.py`
assert the exact count styles, so the style test should be updated with the implementation.

## Color Choice

Use `bold #5FD7FF` for the `read` count.

Rationale:

- It is chromatic, so it fixes the current grey outlier.
- It remains visually calmer than alerting colors like failed red, asking amber, or unread orange.
- It is distinct from the existing count colors while still fitting the TUI palette, which already uses bright cyan and
  blue accents elsewhere.
- It keeps `read` semantically separated from `unread`: unread stays warm/orange and attention-grabbing, while read
  becomes cool/cyan and acknowledged.

## Implementation Steps

1. Change `_COUNT_STYLES["read"]` in `AgentInfoPanel` from `bold #BCBCBC` to `bold #5FD7FF`.
2. Update `test_agent_count_numbers_have_rich_styles` to expect `bold #5FD7FF` for the read metric.
3. Run the focused info-panel test file.
4. Because this repo requires it after non-bead edits, run `just install` if needed and then `just check`.

## Expected Outcome

The Agents tab metric strip keeps all existing labels and ordering, but the `read` count is no longer white/grey. The
focused test should prove the Rich style assignment, and the full check should catch unrelated formatting, lint, type,
or test regressions caused by the small UI change.
