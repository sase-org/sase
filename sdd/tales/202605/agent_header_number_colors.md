---
create_time: 2026-05-09 11:44:00
status: done
prompt: sdd/prompts/202605/agent_header_number_colors.md
---
# Plan: Agents Header Number Colors

## Goal

Make the Agents tab header visually scan well after the recent count-format change, with each count number in the metric
strip highlighted in its own unique color.

The header should keep the same plain text:

`Agents(<total>): <running> running · <waiting> waiting · <unread> unread · <read> read`

Only the Rich styling of the numeric values should change unless implementation reveals an accessibility issue that
requires a very small formatting adjustment.

## Current State

The header is rendered by `AgentInfoPanel._update_display()` in `src/sase/ace/tui/widgets/agent_info_panel.py`.

Current number styling:

- `total` inside `Agents(<total>)`: `dim`
- `running`: `bold #00D7AF`
- `waiting`: `bold #AF87FF`
- `unread`: `bold #FFAF5F`
- `read`: `dim`

So the active counts already have separate colors, but `total` and `read` are both de-emphasized instead of uniquely
highlighted. That makes the header less scannable and falls short of "each number is highlighted using a unique color"
if we treat every count number in the strip as part of the request.

## Design

Keep the labels and separators dim so the counts remain the visual anchors. Use a small named style map local to
`AgentInfoPanel` for the five count roles:

- `total`: a header-adjacent sky blue, distinct from the dim punctuation and from the `Agents` label by weight or hue.
- `running`: keep teal (`#00D7AF`) because it already matches active/success-oriented TUI accents.
- `waiting`: keep amethyst (`#AF87FF`) because it matches `WAITING` rows in the agent list.
- `unread`: keep warm amber/orange (`#FFAF5F`) because it already reads as attention/newness.
- `read`: use a visible neutral/cool completed color instead of `dim`; likely a muted light grey-blue such as
  `bold #BCBCBC` or `bold #87AFAF`, chosen to be unique while remaining quieter than running/waiting/unread.

Avoid changing the count computation in `AgentDisplayMixin._update_agents_info_panel()`. The previous semantic fix
already landed; this change should be presentation-only.

## Implementation Steps

1. Add explicit count-style constants or a `_COUNT_STYLES` mapping in `AgentInfoPanel`.
2. Apply the total count style to the number inside `Agents(<total>)`, leaving the parentheses and colon dim.
3. Apply the role styles to running, waiting, unread, and read counts. Keep labels such as `running`, `waiting`,
   `unread`, and `read` dim.
4. Keep the loading state `Agents: …` unchanged; there are no count numbers to color while loading.
5. Add test coverage in `tests/ace/tui/widgets/test_agent_info_panel.py` that captures the `Rich Text` object rather
   than only `.plain`, then verifies each count number span has the expected unique style.
6. Keep the existing plain-text tests so the exact header text remains stable.
7. Update `tests/ace/tui/test_startup_loading_indicators.py` only if the implementation changes helper behavior or
   direct assertions need to capture the styled object; otherwise leave it alone.

## Verification

Run the focused widget tests first:

```bash
./.venv/bin/python -m pytest tests/ace/tui/widgets/test_agent_info_panel.py tests/ace/tui/test_startup_loading_indicators.py
```

Because implementation files will change, run the repo-required check before reporting completion:

```bash
just check
```

If this workspace is stale and dependencies are missing, run `just install` first as required by the local memory.
