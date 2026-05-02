---
create_time: 2026-04-25 17:45:25
status: done
prompt: sdd/prompts/202604/widen_agents_tab_side_panel.md
---
# Plan: Widen the Agents-tab side panel in `sase ace`

## Context

The "Agents" tab of the `sase ace` TUI has a left-hand side panel (the agent list / pinned panel pair) and a right-hand
detail panel. The left panel grows dynamically based on the widest row currently rendered, but is clamped between two
width bounds. Today the upper bound is too tight: longer agent rows get truncated, hiding suffix metadata, status
badges, and timestamps that would otherwise be useful at a glance.

The user wants the side panel to be allowed to be a little wider so more information fits on a single line.

## Current behavior

The dynamic width pipeline already exists and is the right vehicle for this change — we only need to relax the cap.

- **Width bounds (constants)** — `src/sase/ace/tui/app.py:69-71`
  ```py
  _MIN_AGENT_LIST_WIDTH = 40
  _MAX_AGENT_LIST_WIDTH = 70
  ```
- **CSS bounds (must stay in sync)** — `src/sase/ace/tui/styles.tcss:650-655`
  ```tcss
  #agent-list-container {
      width: 40;            /* Default, will be set programmatically */
      min-width: 40;
      max-width: 70;
      height: 100%;
  }
  ```
- **Width measurement** — `src/sase/ace/tui/widgets/agent_list.py:285-288` computes
  `optimal_width = max(max_width, banner_width) + _PADDING` (where `_PADDING = 8` for border + scrollbar + comfort) and
  posts a `WidthChanged` message.
- **Width application** — `src/sase/ace/tui/actions/event_handlers.py:329-348` listens to `AgentList.WidthChanged` from
  both the main and pinned panels, takes the max of the two requests, clamps to
  `[_MIN_AGENT_LIST_WIDTH, _MAX_AGENT_LIST_WIDTH]`, and assigns `agent_list_container.styles.width = width`.

For comparison, the ChangeSpecs tab uses `width: 43; min-width: 43; max-width: 80;` in the same stylesheet
(`#list-container`, `styles.tcss:49`). So an Agents-tab cap of 70 is the tighter of the two sibling panels.

## Goal

Increase the upper bound on the Agents-tab side panel so wider rows are allowed to render fully when the user's terminal
has the room, without forcing the panel wider when content does not need it (the dynamic sizing keeps narrow content
compact).

Non-goals:

- No change to the minimum width — 40 cells is fine for short rows and preserves muscle memory for users on smaller
  terminals.
- No change to row formatting / no new columns — this is purely a layout cap change.
- No change to the ChangeSpecs or Axe tab side panels.

## Proposed change

Raise `_MAX_AGENT_LIST_WIDTH` from `70` → `80`, matching the ChangeSpecs tab cap, and update the matching CSS
`max-width` on `#agent-list-container` so the two stay in sync.

Rationale for `80` specifically:

- Brings the Agents tab in line with ChangeSpecs tab (`max-width: 80`), which already lives next to it in the same TUI
  and has not caused complaints about being too wide on common terminals.
- Still leaves >=40 cells for the right-hand detail panel on an 80×24 terminal in the worst case (the right panel is
  `width: 1fr` and a user sitting at 80 columns would, in practice, never pin and main-panel both to 80 — the dynamic
  logic only grows when content actually demands it).
- Keeps the width still capped — we are not switching to unbounded growth, which would let a single oversized row
  swallow the whole tab.

### Files touched

1. `src/sase/ace/tui/app.py` — bump the constant.

   ```py
   _MAX_AGENT_LIST_WIDTH = 80   # was 70
   ```

2. `src/sase/ace/tui/styles.tcss` — bump the CSS cap on `#agent-list-container` from `max-width: 70` to `max-width: 80`.

That is the entire surface area. The `WidthChanged` plumbing, the main/pinned `max()` combination, and the per-row width
measurement all keep working as-is — they just clamp against a higher ceiling.

## Verification

- Manual: open `sase ace`, switch to the Agents tab, and confirm rows that previously truncated at ~70 cells now render
  in full when content justifies it. Confirm the panel still shrinks back when only short rows remain (e.g. after a
  filter).
- Manual: confirm narrow-terminal behavior is unchanged — on an 80-column terminal, growth is still bounded by the 1fr
  competition with the detail panel.
- Manual: visit ChangeSpecs and Axe tabs to confirm we did not inadvertently regress their widths.
- Automated: `just check`.

## Risks and reversibility

Low risk. The change is two numeric edits inside an already-clamped dynamic-sizing system. If 80 turns out to feel too
wide, the constant / CSS pair is a one-line revert. No data-format or persisted-state changes.
