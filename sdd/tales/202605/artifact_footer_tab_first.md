---
create_time: 2026-05-09 11:33:10
status: done
---
# Plan: Move Artifact Viewer Tab Hint To Footer Start

## Goal

Make the artifact viewer tmux pane footer place the `<tab>: Ace` hint at the beginning of the footer line whenever the
return-to-Ace pane shortcut is available.

This should preserve all existing navigation behavior: `<tab>` still focuses the original Ace pane and keeps the
artifact viewer open, while `j`/`k`, `n`/`p`, `r`, and `q` continue to behave as they do today.

## Current Behavior

The tmux artifact viewer path launches `python -m sase.ace.tui.graphics.viewer`, which calls
`run_artifact_sequence_loop()` in `src/sase/ace/tui/graphics/_viewer_loop.py`.

The footer text is built by `print_page_prompt()` from the ordered tuple returned by `page_loop_available_keys()`. That
tuple currently appends the return-to-Ace key after page and artifact navigation keys:

- page navigation: `j`, `k`
- artifact navigation: `n`, `p`
- return-to-Ace: `<tab>`
- utility actions: `r`, `q`

In a multi-page or multi-artifact viewer this renders `<tab>: Ace` in the middle of the footer action list instead of as
the first visible action.

## Design

Treat return-to-Ace as the primary pane-control action and order it before viewer-local navigation in the footer.

The smallest coherent change is to update `page_loop_available_keys()` so `_RETURN_TO_ACE_KEY` is added first when
`return_pane_available=True`. Because `print_page_prompt()` already renders labels in `page_loop_available_keys()`
order, this moves `<tab>: Ace` to the start of the action list without adding a second formatting path.

For the tmux sequence loop, `print_page_prompt(..., show_position=False)` means the footer line itself will begin with
`<tab>: Ace` when the return pane is available. For the standalone page loop, existing page-position text may still
prefix the action list; that path is not the tmux artifact pane path, but the available-key order should still be
consistent.

## Implementation Steps

1. Update `src/sase/ace/tui/graphics/_viewer_loop.py`.
   - Move `_RETURN_TO_ACE_KEY` insertion to the beginning of `page_loop_available_keys()` when
     `return_pane_available=True`.
   - Keep all existing key handling logic unchanged.

2. Update `tests/ace/tui/artifact_viewer/test_loops.py`.
   - Adjust the expected `page_loop_available_keys(..., return_pane_available=True)` order.
   - Add or update prompt assertions showing `<tab>: Ace` appears before page navigation actions.
   - Add coverage for the tmux/sequence-loop shape (`show_position=False`) so a multi-page artifact footer starts with
     `<tab>: Ace`.

3. Verify focused behavior.
   - Run `pytest tests/ace/tui/artifact_viewer/test_loops.py`.
   - Because this repo requires it after source changes, run `just install` if needed and then `just check` before
     finishing.

## Acceptance Criteria

- In the artifact viewer tmux pane, when a return pane is available, the footer line begins with `<tab>: Ace`.
- `<tab>` still focuses the original Ace pane and leaves the artifact viewer open.
- Existing page, artifact, refresh, and quit keys remain available in the same relative order after the `<tab>` hint.
- Focused artifact viewer loop tests pass, and repository checks are run before completion.

## Risks

- Tests may rely on the exact tuple ordering from `page_loop_available_keys()`. Updating those expectations is correct
  because that tuple is also the footer ordering contract.
- If a future caller wants position metadata before `<tab>`, it can still set `show_position=True`; the tmux viewer path
  currently uses `show_position=False`, which directly satisfies the requested footer placement.
