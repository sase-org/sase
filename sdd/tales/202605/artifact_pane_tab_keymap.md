---
create_time: 2026-05-09 10:51:56
status: done
prompt: sdd/prompts/202605/artifact_pane_tab_keymap.md
---
# Artifact Pane Tab Keymap Plan

## Goal

Change the artifact-pane focus controls from directional keys to a symmetric tab toggle:

- In the Ace TUI, `<tab>` should focus the tracked artifact viewer tmux pane while that pane is live.
- Inside the artifact viewer tmux pane, `<tab>` should focus back to the originating Ace TUI pane and keep the viewer
  open.
- `l` in the Ace TUI should return to its normal fold/layout behavior.
- `h` in the artifact viewer should stop being the return-to-Ace key.
- While the artifact viewer pane is live, `q` in the Ace TUI should close that pane using the same path as `A` in this
  context, instead of quitting Ace.

This remains presentation-only TUI/tmux behavior, so it belongs in this repo rather than the Rust core boundary.

## Current Context

The existing artifact-pane implementation already provides most of the necessary state and tmux plumbing:

- `AgentPanelsMixin` tracks the artifact pane id in `_artifact_tmux_pane_id`.
- `_artifact_tmux_pane_visible()` checks tmux state, clears stale pane ids, and syncs the collapsed Agents layout.
- `_focus_tracked_artifact_tmux_pane()` selects the live tracked pane with `select_tmux_pane()`.
- `_toggle_tracked_artifact_tmux_pane()` closes the live tracked pane, clears state, syncs layout, and surfaces
  warnings.
- `A` already uses `_toggle_tracked_artifact_tmux_pane()` before opening the artifact selection modal.
- `view_artifact_files_in_tmux_pane()` passes `SASE_ARTIFACT_RETURN_PANE_ID` to the viewer pane when the originating Ace
  pane id is available.
- The artifact viewer loop accepts `h` when a return pane exists and calls the same pane selection helper.

Important keymap constraints:

- `<tab>` is already the app-level `next_tab` key in `src/sase/default_config.yml`, with priority binding metadata.
- `q` is already the app-level `quit` key.
- `l` is already the app-level `expand_or_layout` key.
- Because the requested TUI behavior is context-sensitive and uses existing configured app keys, we should not add new
  app keymap fields or rewrite `default_config.yml`.

## Design

### 1. Move TUI artifact focus from `l` to `<tab>`

Update the Agents/TUI routing so the artifact focus branch lives on `action_next_tab()` instead of
`action_expand_or_layout()`:

- In `AgentFoldingMixin.action_expand_or_layout()`, remove the artifact-focus precheck so `l` always follows the
  existing fold expansion path on the Agents tab.
- In `action_next_tab()` in `src/sase/ace/tui/actions/navigation/_basic.py`, add an early Agents-tab branch:
  - If `current_tab == "agents"` and `_focus_tracked_artifact_tmux_pane()` exists and returns `True`, return
    immediately.
  - Otherwise continue with the normal next-tab behavior.
- Preserve normal `<tab>` tab switching everywhere else, including Agents when no live artifact pane exists.
- Preserve `<shift+tab>` as normal previous-tab behavior. The request only changes `<tab>`.

This uses the current pane visibility/staleness logic:

- Live pane: focus it and consume `<tab>`.
- Stale tracked pane: `_artifact_tmux_pane_visible()` clears state, `_focus_tracked_artifact_tmux_pane()` returns
  `False`, and `<tab>` falls through to normal tab switching.
- Selection failure after a live check: warning is surfaced and the key is still consumed, matching the current `l`
  behavior.

### 2. Make `q` close the artifact pane before quitting Ace

Update `LifecycleMixin.action_quit()` to check for a live tracked artifact pane before the running-task quit
confirmation:

- Look up `_toggle_tracked_artifact_tmux_pane()` dynamically to keep the lifecycle mixin decoupled from the Agents
  mixin.
- If it is callable and returns `True`, return immediately without quitting Ace.
- If there is no live pane, or the tracked pane was stale and got cleared, continue with the existing quit flow
  unchanged.

This intentionally reuses the same path as `A`:

- tmux `kill-pane` is called through `close_artifact_tmux_pane()`.
- `_artifact_tmux_pane_id` is cleared.
- the artifact-viewer layout class is removed.
- warnings are surfaced the same way.

### 3. Change the artifact viewer return key from `h` to raw tab

Update `src/sase/ace/tui/graphics/_viewer_loop.py` so the viewer accepts the raw tab byte (`"\t"`) for return focus:

- Introduce a small constant for the return-to-Ace key, e.g. `_RETURN_TO_ACE_KEY = "\t"`, to avoid scattering a control
  character literal.
- Change `page_loop_available_keys(..., return_pane_available=True)` to include the tab key instead of `"h"`.
- Change `print_page_prompt()` to label that key as `<tab>: Ace` or `tab: Ace`.
- In both `run_artifact_page_loop()` and `run_artifact_sequence_loop()`, replace the `key == "h"` return-pane branch
  with the tab key.
- Keep `q` inside the artifact viewer as viewer quit. The new `q` close behavior applies to Ace while the split pane is
  visible, not to the viewer process itself.

Direct non-tmux viewer usage remains unchanged: no return pane id means no tab return affordance is shown or accepted.

### 4. Update conditional footer hints

Update the Agents footer so it advertises the transient behavior accurately while the artifact pane is active:

- Replace the current `l artifact pane` hint with `<tab> artifact pane` by using `self._kd("next_tab")`.
- Add a `q close artifact pane` hint using `self._kd("quit")` while `artifact_viewer_active=True`.
- Keep the existing `A artifacts`/artifact action behavior intact. `A` still works as the explicit artifact toggle/open
  key; `q` becomes an additional close affordance only in this context.

This footer-only change avoids modifying the global help sections, which still correctly describe baseline global keys.
The footer is where this codebase already surfaces transient context-sensitive action changes.

### 5. Tests

Update and add focused tests around the changed routing:

- `tests/ace/tui/artifact_viewer/test_loops.py`
  - Update available-key expectations from `"h"` to `"\t"` when a return pane exists.
  - Update prompt assertions from `h: Ace` to the new tab label.
  - Update the return-focus loop test to press `"\t"` and assert the same pane-selection/stay-open behavior.
  - Add or adjust a negative assertion that `h` is not accepted as a return key when a return pane exists.

- `tests/ace/tui/actions/test_agent_artifact_image_actions.py`
  - Keep coverage for `_focus_tracked_artifact_tmux_pane()` itself.
  - Add coverage that `action_quit()`/the quit interception path closes a live tracked pane via the same toggle helper
    behavior and does not run the normal quit path.
  - Keep coverage that stale pane state clears and does not close/select a nonexistent pane.

- `tests/ace/tui/test_agent_fold_transitions.py`
  - Remove or rewrite the current assertion that `l` focuses the artifact pane before expanding.
  - Add/keep an assertion that `l` expands folds normally even when the stub focus helper would have returned true,
    because `l` should no longer consult artifact focus.

- Navigation/tab tests, likely near `tests/ace/tui/test_axe_selection_identity.py` or a new narrow navigation test
  - With `current_tab == "agents"` and `_focus_tracked_artifact_tmux_pane()` returning `True`, `action_next_tab()`
    consumes the key and stays on Agents.
  - With no live pane or a stale pane path returning `False`, `action_next_tab()` still switches Agents to Axe.
  - Non-Agents tabs keep existing next-tab behavior.

- `tests/test_keybinding_footer_agent.py`
  - Update the active artifact viewer footer expectation from `("l", "artifact pane")` to the configured next-tab
    display, normally `("tab", "artifact pane")` or the footer display format for tab.
  - Add the active-only `q close artifact pane` expectation.
  - Assert neither transient hint appears when `artifact_viewer_active=False`.

Existing tmux launch tests should not need behavioral changes because `SASE_ARTIFACT_RETURN_PANE_ID` and
`select_tmux_pane()` remain the same.

## Verification

After implementation:

1. Run the focused tests:

   ```bash
   just test tests/ace/tui/artifact_viewer/test_loops.py tests/ace/tui/artifact_viewer/test_tmux.py tests/ace/tui/actions/test_agent_artifact_image_actions.py tests/ace/tui/test_agent_fold_transitions.py tests/test_keybinding_footer_agent.py
   ```

2. Run the navigation/keymap-focused tests touched or added for `action_next_tab()`.

3. Run `just lint`.

4. Because this repo requires it after code changes, run `just check` before the final implementation response.

If `just check` reports unrelated baseline failures, report the exact failing area and include the focused test and lint
results.
