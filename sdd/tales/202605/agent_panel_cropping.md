---
create_time: 2026-05-27 09:58:30
status: done
prompt: sdd/prompts/202605/agent_panel_cropping.md
---
# Plan: Agent Panel Cropping Priority

## Problem

The ACE Agents tab stacks one `AgentList` widget per tag panel. In the current overflow regime,
`PanelRefreshMixin._apply_panel_heights()` assigns every panel a fractional height weighted by `option_count + 1`. That
works for rough proportional sharing, but it can shrink a small panel such as `#chop · 1 [R1]` to a height that shows
only its status banner and no agent row. It also crops the first `(untagged)` panel even when that panel's natural
height is small enough to fit comfortably.

The desired behavior is:

- A small tag panel should not be squeezed so far that its only agent disappears when larger panels can absorb the
  overflow instead.
- The `(untagged)` panel should stay at natural height unless its natural height would consume more than half of the
  available agent-list column height.
- When `(untagged)` is larger than that half-height threshold, crop it and let it scroll.
- If the full stack fits, keep the existing behavior where the first panel absorbs leftover vertical space.

## Scope

This is presentation-only ACE TUI layout behavior. It belongs in the Python TUI layer, not in `sase-core`.

Primary files:

- `src/sase/ace/tui/actions/agents/_display_panel_refresh.py`
- `tests/ace/tui/test_agent_panels_display.py`

Potential verification:

- `just test tests/ace/tui/test_agent_panels_display.py`
- `just test tests/ace/tui/test_agent_panel_titles.py tests/ace/tui/test_agent_panel_first_selection.py`
- `just test-visual` if the targeted tests reveal a visual snapshot drift worth inspecting
- `just check` after code changes, per project memory

## Design

Keep the existing "fits" regime unchanged:

1. Compute each panel's natural height as `option_count + border_rows`.
2. Compute separator rows as `len(widgets) - 1`.
3. If natural heights plus separators fit inside the container, keep panel 0 at `1fr` so it absorbs leftover space, and
   keep later panels at exact cell heights.

Replace the overflow regime with a prioritized allocation:

1. Work with a content budget that excludes separator rows, because Textual margins consume those rows outside the
   widgets.
2. Derive a minimum useful height per panel:
   - empty panel: border-only natural height,
   - one visible option: border plus one row,
   - two or more options: border plus two rows, so a one-agent grouped panel can show both its status banner and its
     agent row.
3. Handle `(untagged)` specially:
   - If panel 0 is really the untagged panel and its natural height is at most half of the available content budget,
     reserve its full natural cell height before sharing overflow with other panels.
   - If its natural height is more than half the content budget, reserve only the half-height cap so it becomes
     scrollable.
4. Protect compact tagged panels next, in ascending natural-height order, while leaving enough budget for every
   remaining unprotected panel to receive its minimum useful height. This lets small panels like `#chop` render their
   agent rows while larger panels like `#research` scroll.
5. Assign fixed cell heights to protected panels and fractional heights to the remaining cropped panels, weighted by
   their remaining overflow demand.
6. If the terminal is too short to satisfy all minimums, degrade gracefully by using fractional heights for all
   unprotected panels rather than overcommitting fixed cell heights.

## Tests

Update the existing dynamic height tests so they describe the new allocation model instead of the old proportional-only
overflow model:

- Existing fit-boundary tests should continue to pass with unchanged expectations.
- Replace the proportional-overflow assertion with a test that a small dynamic tag panel is fixed to its natural height
  while the large panel remains fractional/cropped.
- Add a regression test for the `(untagged)` priority: when `(untagged)` is below the half-height threshold, it receives
  its natural height in overflow.
- Add a regression test for the `(untagged)` cap: when `(untagged)` exceeds half the available height, it is assigned
  the half-height cap and can scroll.
- Keep the zero-height and reapply-without-rebuild tests; update reapply expectations to match the new overflow regime.

## Risks

- The user-facing visual result depends on how Textual distributes mixed fixed-cell and fractional heights with margins.
  The unit tests should assert the scalar regime, and a visual snapshot run can confirm the rendered stack.
- A very small terminal can make it impossible to show two rows in every panel. The algorithm should avoid claiming more
  fixed cell height than the container can provide.
