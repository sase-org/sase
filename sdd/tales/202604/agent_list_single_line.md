---
create_time: 2026-04-27 11:39:07
status: done
prompt: sdd/prompts/202604/agent_list_single_line.md
---
# Agent List Single-Line Rendering Plan

## Problem

The Agents tab list rows are rendered through Textual's `OptionList`. The row builders in
`src/sase/ace/tui/widgets/_agent_list_rendering.py` deliberately pad agent rows and banner rows to a shared target width
so runtime suffixes and banner chips align. That target is then reported to the app as `AgentList.WidthChanged`, but the
app clamps the left pane to `_MAX_AGENT_LIST_WIDTH = 80`.

The visible row width inside `OptionList` is smaller than the outer container because it loses cells to the border,
`AgentList` padding, option padding, and the stable scrollbar gutter. When the padded Rich `Text` exceeds that inner
width, Textual's default `text-wrap: wrap` behavior treats a single option as multiple visual lines. This is why the
snapshot shows banner chips and agent runtime suffixes pushed onto their own lines.

The fix should make list options intrinsically one-line renderables, independent of current terminal width and
independent of whether a future row becomes wider than the current max left-pane width.

## Scope

- Keep the existing alignment behavior when there is enough horizontal space.
- Prevent all `AgentList` options from soft-wrapping when there is not enough horizontal space.
- Preserve selection, row indexing, banner click resolution, patch updates, and per-panel height calculations.
- Add regression coverage at the rendering boundary that Textual actually uses, not just by checking `Text.plain`.

## Implementation

1. Configure `AgentList` with `text-wrap: nowrap` and `text-overflow: clip` in `styles.tcss`.
   - Textual's `Content.from_rich_text()` does not preserve `Rich.Text(no_wrap=True)`, so CSS is the correct control
     point for `OptionList` height and strip generation.
   - `clip` is appropriate because these rows already put critical details first and the detail pane contains the full
     agent information.

2. Add a small `AgentList` render regression test.
   - Mount an `AgentList` in a deliberately narrow harness.
   - Add agents with long names, grouped banners, and runtime suffixes/chips that previously exceeded the inner width.
   - Assert that Textual's internal line cache assigns exactly one visual line per option after `_update_lines()`.

3. Run focused tests for agent list rendering and then the repo-required `just check`.
   - Because workspace memory says this ephemeral checkout may need setup first, run `just install` if the check tooling
     cannot import the package or dependencies.

## Risks

- Clipping means the far-right runtime suffix can be partially hidden in narrow terminals. That is preferable to row
  wrapping because wrapping breaks visual scanning, navigation geometry, and the per-panel height model.
- If another `AgentList` CSS rule overrides text wrapping later, the regression test should catch it by measuring
  Textual's actual option line cache.
