---
name: agents_untagged_full_height
description: Fix Agents-tab untagged panel not filling available height when no tagged
  panels exist
create_time: 2026-04-26 03:08:50
status: done
prompt: sdd/prompts/202604/agents_untagged_full_height.md
---

# Fix: Agents-tab untagged panel must fill available height

## Problem

In the `sase ace` Agents tab, when there are zero tagged agents (only the `(untagged)` panel exists), the untagged panel
renders with its natural content height and leaves a large empty region below it inside the agent-list column. The user
expects the untagged panel to fill the full available height in this case.

User-visible repro: open `sase ace` → Agents tab with no tagged agents → the only panel sits flush against the top of
the column with empty space beneath it.

## Root cause

`AgentDisplayMixin._apply_panel_heights` in `src/sase/ace/tui/actions/agents/_display.py` (lines 313–351) sizes panels
via two regimes:

- **Fits** (`Σ natural ≤ container_height`): every panel is pinned to its **exact natural cell height**
  (`option_count + 2` border rows).
- **Overflow** (`Σ natural > container_height`): every panel gets a fractional weight so they share the available height
  proportionally.

The Fits branch (line 343–345) gives every panel a fixed cell height. When the sum is strictly less than the container,
the leftover rows are simply unallocated — Textual leaves them blank below the last panel. With a single (untagged)
panel this is the entire empty region the user is seeing; the docstring's claim of "no space is wasted" only holds when
`Σ natural == container_height`, which is rarely true.

The Phase 2/3 grouping work (commits f68eebbf, 2fb1d770) didn't change this logic — it is a pre-existing latent bug from
the original panel sizing feature (commit 3c59b7f2) that has only become user-visible now that the BY_DATE/BY_STATUS
bucket banners pad the untagged panel's content enough that users notice the gap. The single-panel case (i.e. no tagged
agents) makes the regression maximally obvious because 100% of the leftover space lands below one panel.

CSS context (`src/sase/ace/tui/styles.tcss` lines 650–676): the container is `height: 100%` and the per-panel CSS
fallback is `height: 1fr`. The Python sizing logic overrides that fallback every refresh, so the CSS fallback only
protects the pre-mount frame.

## Fix design

Change the Fits branch so that **the last panel absorbs the leftover height** instead of being pinned to its natural
cell count. The remaining (non-last) panels keep their exact cell heights so small panels don't grow disproportionately.
With a single panel this naturally collapses to the desired behavior: the only panel gets all the height. With multiple
panels it eliminates the dead zone at the bottom of the column without disturbing the per-panel sizing the user already
accepts.

Concretely, in `_apply_panel_heights`:

- If `total_natural <= container_height`:
  - For every widget except the last: set `Scalar(natural, CELLS, HEIGHT)` as today.
  - For the last widget: set `Scalar(1.0, FRACTION, HEIGHT)` so it expands to fill the remainder.
- Overflow branch: unchanged.

The "last panel" is unambiguous because `_apply_panel_heights` is already called with an ordered widget list
(`ordered_widgets` in `_display.py:306`), and the untagged panel is rendered last in the default ordering — but even
when it isn't last (e.g. user has chosen a different ordering), the visual outcome is still correct: the bottom panel
grows, and there's no dead zone.

Update the docstring on `_apply_panel_heights` to reflect the new behavior ("the last panel grows to fill leftover
space; earlier panels keep their natural cell heights").

## Out of scope

- Changing the Overflow regime — it already shares the container proportionally.
- Reordering panels so the untagged panel is always last.
- Touching CSS rules. The Python override covers all post-mount frames.
- New tests beyond the focused unit test below — the Agents-tab grouping Phase work already added coverage for panel
  ordering and the bucket banners.

## Verification

1. **Unit test** in the existing `_display.py` test module (or the nearest existing tests for `_apply_panel_heights`):
   construct a mock container with `size.height = 30` and a single mock widget with `option_count = 3`. Assert the
   widget's `styles.height` is set to `Scalar(1.0, FRACTION, HEIGHT)` (not `Scalar(5.0, CELLS, ...)`). Add a second case
   with two widgets where Σ natural < container, and assert: widget[0] keeps its cell height, widget[-1] gets the
   fractional unit.
2. **Manual TUI check**: `sase ace` → Agents tab with no tagged agents. The untagged panel must extend to the bottom of
   the column. Then tag at least one agent (`N` keymap) and confirm the resulting 2-panel layout still uses the full
   column height with no dead zone below the last panel.
3. `just check` passes in this workspace (run after `just install`, per the workspace gotcha).

## Files touched

- `src/sase/ace/tui/actions/agents/_display.py` — modify `_apply_panel_heights` (Fits branch) and its docstring.
- The matching unit test file (locate via grep for `_apply_panel_heights` under `tests/`).

## Risks

Low. The only behavioral change is "the last panel in the Fits regime now uses `1fr` instead of a fixed cell count." The
Overflow regime, focus highlighting, panel ordering, and pre-mount fallback are all untouched. The CSS fallback still
keeps panels visible during the pre-mount frame.
