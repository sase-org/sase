---
create_time: 2026-05-02 12:56:53
status: done
prompt: sdd/prompts/202605/agents_panel_width_runtime.md
---
# Plan: Keep Agents Left Panel Wide Enough for Runtime Suffixes

## Problem

The Agents tab left column can shrink so far that the main untagged panel no longer shows the right-aligned completion
timestamp / runtime suffix. The screenshots show the same stack of agent rows in two states:

- Good: the upper `(untagged)` panel is wide enough for suffixes like `12:25:57 · 7m41s`.
- Bad: the upper panel has collapsed to roughly the minimum width, so rows show only the left label and long names are
  clipped before the runtime suffix.

This is not a backend data issue. `Agent` timing data and runtime suffix formatting are already present, and the row
formatter already splits each row into `(left, suffix)` and pads the suffix to a right-aligned column.

## Diagnosis

The relevant path is:

- `src/sase/ace/tui/widgets/_agent_list_build.py`
  - formats each visible agent row;
  - computes `target_width = max(_MIN_BANNER_WIDTH, max_left + gap + max_suffix)`;
  - posts `AgentList.WidthChanged(optimal_width)` where `optimal_width = target_width + 8`.
- `src/sase/ace/tui/actions/event_handlers.py`
  - handles each `AgentList.WidthChanged`;
  - clamps the event width to `_MIN_AGENT_LIST_WIDTH.._MAX_AGENT_LIST_WIDTH`;
  - assigns the result to `#agent-list-container.styles.width`.
- `src/sase/ace/tui/actions/agents/_display_panels.py`
  - mounts one stacked `AgentList` widget per tag panel inside the same `#agent-list-container`.

The bug is the last part: there can be multiple `AgentList` widgets in the same left column. Each one independently
posts a `WidthChanged` event, but the handler treats each event as authoritative for the whole column. A short tagged
panel such as `@comedy` can request the 60-cell minimum after the large `(untagged)` panel requested a wider column.
Whichever event is processed last wins, so the column width is sometimes driven by the shortest panel instead of the
widest panel.

That matches the screenshots: snapshot #2 has a lower `@comedy` panel whose short rows fit at the minimum width, while
the upper `(untagged)` panel needs much more width for its runtime suffixes.

## Goal

The width of `#agent-list-container` must be the maximum width needed by any currently mounted Agents-tab panel, not the
most recent width requested by one panel. This should make the left column stable and always wide enough for the full
runtime suffix whenever the terminal and `_MAX_AGENT_LIST_WIDTH` allow it.

## Proposed Fix

1. Store each `AgentList` widget's latest requested full container width.
   - Add an instance field on `AgentList`, e.g. `_requested_width`.
   - In `_agent_list_build.build_list`, set it to `optimal_width` immediately before posting `WidthChanged`.
   - This keeps the latest width demand available after all stacked panels finish rebuilding.

2. Change `on_agent_list_width_changed` to aggregate across mounted panel widgets.
   - Query `#agent-list-container AgentList`.
   - Compute `desired_width = max(event.width, *(w._requested_width for mounted AgentList widgets if > 0))`.
   - Clamp `desired_width` using the existing `_MIN_AGENT_LIST_WIDTH` and `_MAX_AGENT_LIST_WIDTH`.
   - Apply the clamped width to `#agent-list-container.styles.width`.
   - Keep `event.width` in the max as a defensive fallback for early events, tests, or unusual message ordering.

3. Keep existing min/max constants and row formatting unchanged.
   - `_MIN_AGENT_LIST_WIDTH = 60` and `_MAX_AGENT_LIST_WIDTH = 130` are already large enough for the good screenshot.
   - The bug is not that the cap is too low; it is that a narrower panel can overwrite the wider panel's request.

## Tests

Add or extend focused unit tests rather than introducing a full TUI snapshot:

- `tests/ace/tui/test_agent_left_panel_width.py`
  - Existing test verifies clamping to `_MAX_AGENT_LIST_WIDTH`.
  - Add a fake container with multiple mounted `AgentList`-like children carrying `_requested_width`.
  - Send a narrow `WidthChanged` event and assert the applied container width is the maximum requested width among all
    children.
  - Add a clamp variant to confirm aggregation still respects `_MAX_AGENT_LIST_WIDTH`.

Optional low-level coverage:

- `tests/ace/tui/widgets/test_agent_list_runtime.py` or a small new widget test can assert that `AgentList.update_list`
  records a nonzero `_requested_width` after rendering rows with runtime suffixes.

## Verification

Run targeted tests first:

```bash
just install
pytest tests/ace/tui/test_agent_left_panel_width.py tests/ace/tui/widgets/test_agent_list_runtime.py
```

Then run the repo-required check:

```bash
just check
```

Manual follow-up if practical:

- Open `sase ace`, switch to Agents, and confirm stacked panels choose the width of the widest panel.
- Check that short single-panel views still use the minimum width and that the right detail panel remains usable.

## Risks

Low. This is a presentation-only Textual layout change. It does not touch agent loading, timing calculation, grouping,
tags, or persisted state. The main risk is stale `_requested_width` on removed widgets, but aggregation only considers
currently mounted children, and stale unmounted panel widgets are removed before normal refresh completion.
