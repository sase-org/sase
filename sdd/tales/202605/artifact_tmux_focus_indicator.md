---
create_time: 2026-05-09 11:37:10
status: done
prompt: sdd/prompts/202605/artifact_tmux_focus_indicator.md
---
# Plan: Artifact Viewer Tmux Focus Indicator

## Problem

When an artifact viewer tmux pane is visible, `<tab>` can move focus between the SASE TUI pane and the artifact viewer
pane, but the UI does not make the currently focused pane obvious. The existing implementation tracks the artifact pane
id, collapses the Agents list while the pane is live, and lets the viewer return focus to the originating pane. It does
not provide a strong focus affordance beyond the artifact viewer footer hint and the TUI footer binding label.

## Product Goal

Make focus state obvious at a glance whenever the artifact viewer tmux pane is open:

- The active pane should be visually distinct even when focus changes through native tmux controls, not only through
  SASE keymaps.
- The TUI should still explain what `<tab>` and `q` do while the artifact pane is live.
- The artifact viewer should clearly identify itself and show that `<tab>` returns to Ace/SASE.
- Closing or staling the artifact pane should restore normal TUI layout and tmux presentation.

## Proposed Approach

Use tmux pane decoration as the primary focus indicator, because tmux owns pane focus and can reflect native focus
changes more reliably than either the Textual app or the artifact viewer subprocess.

1. Add a small tmux decoration helper near the existing artifact pane tmux helpers in
   `src/sase/ace/tui/graphics/_viewer_launch.py`.
   - It should set readable pane titles for the origin pane and artifact pane, such as `SASE TUI` and `Artifact Viewer`.
   - It should temporarily enable pane border status for the current tmux window and use a pane border format/style that
     visibly marks `#{pane_active}`.
   - It should save the previous relevant window options before changing them so they can be restored later.
   - It should fail soft: missing tmux, old tmux option failures, or restoration failures should only produce warnings
     where appropriate and should not prevent artifact viewing.

2. Track the decoration state from `AgentPanelsMixin`.
   - Extend the artifact pane state initialized in `src/sase/ace/tui/actions/_state_init.py` with a small snapshot of
     prior tmux options, or a token/object returned by the graphics helper.
   - When `_open_agent_artifact()` or `_open_agent_artifacts()` successfully opens a tmux pane, install the decoration
     after `_artifact_tmux_pane_id` is known.
   - When `_toggle_tracked_artifact_tmux_pane()`, `_clear_artifact_viewer_layout_from_signal()`, stale-pane checks, or
     quit cleanup clear the tracked pane, restore the previous tmux window options.
   - Keep cleanup idempotent so SIGUSR1 close notification, explicit close, and quit can race without leaving bad state.

3. Make the TUI footer wording more explicit while the artifact pane is live.
   - In `src/sase/ace/tui/widgets/_keybinding_bindings.py`, change the existing artifact bindings from terse labels like
     `artifact pane` to action-oriented labels like `focus artifact pane` and `close artifact pane`.
   - Consider adding a short non-binding badge in the formatted footer content, such as `artifact pane open`, only if it
     fits the existing footer conventions without making hot-path rendering noisy.

4. Improve the artifact viewer footer/header copy as a secondary cue.
   - In `src/sase/ace/tui/graphics/_viewer_loop.py`, update the prompt label from `<tab>: Ace` to a clearer label such
     as `<tab>: focus SASE TUI`.
   - Keep this text short because it shares a single terminal line with page/artifact navigation keys.

## Technical Notes

- Do not put focus-state truth solely in the Textual app, because the app is inactive when the artifact viewer has focus
  and will not reliably receive every native tmux focus transition.
- Do not put focus-state truth solely in the artifact viewer loop, because the viewer can be inactive while the TUI is
  focused and may not redraw when focus returns through tmux-native navigation.
- Tmux `#{pane_active}` in pane border formatting is the correct layer for the primary indicator because it is evaluated
  by tmux itself as focus changes.
- The helper should be conservative about changing user tmux configuration: use window-scoped options, save the previous
  values, and restore them when the artifact pane closes.

## Test Plan

Add focused unit coverage around the new behavior:

- `tests/ace/tui/artifact_viewer/test_tmux.py`
  - Launching an artifact pane captures the pane id as before.
  - The new decoration helper issues tmux commands to save current window options, set pane titles, set pane border
    status/format/style, and restore them.
  - Decoration failures do not make artifact viewing fail.

- `tests/ace/tui/actions/test_agent_artifact_image_actions.py`
  - Successful single-artifact and multi-artifact tmux launches install decoration after the pane id is tracked.
  - Explicit close, stale-pane cleanup, signal-driven close, and quit restore decoration exactly once.

- `tests/ace/tui/artifact_viewer/test_loops.py`
  - The artifact viewer prompt includes the clearer `<tab>` return-focus wording when a return pane is available.

- `tests/test_keybinding_footer_agent.py`
  - Active artifact viewer bindings advertise `focus artifact pane` and `close artifact pane`.

After implementation, run the narrow test set above first, then `just install` if needed and `just check` before final
response.

## Rollout Risks

- Some users may already customize tmux pane border status/format heavily. Saving and restoring window-scoped options
  limits the blast radius, but a crash could still leave temporary options behind until the user resets the window.
- Older tmux versions may reject some style or format options. The helper should treat those as best-effort and still
  open the artifact viewer.
- Footer text must stay compact enough for narrow terminals; the tmux border indicator should carry the primary focus
  signal.
