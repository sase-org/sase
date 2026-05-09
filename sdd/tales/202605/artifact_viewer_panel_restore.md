---
create_time: 2026-05-09 03:58:48
status: done
prompt: sdd/prompts/202605/artifact_viewer_panel_restore.md
---
# Plan: Restore Agents Side Panel When Artifact Viewer Pane Closes

## Problem

When an artifact is opened from the Agents tab inside tmux, Ace tracks the new artifact-viewer pane id and adds the
`-artifact-viewer-active` class to collapse the Agents side panel. The class is cleared only when Ace later checks
whether the tracked pane still exists, such as on refresh, navigation, or pressing the artifact action again. If the
user closes the tmux pane directly, no event is delivered to Ace, so the side panel remains hidden until some later
incidental sync.

## Constraints

- The side panel should reappear immediately when the viewer pane closes.
- The fix must not add short-interval polling or extra work on normal navigation.
- The behavior should remain scoped to the tmux artifact viewer path.
- Existing non-tmux artifact viewing should stay unchanged.

## Approach

Use a one-shot event from the artifact viewer process back to the Ace process:

1. When Ace opens an artifact viewer in tmux, install a lightweight `SIGUSR1` handler if supported, then temporarily
   expose Ace's PID to the tmux launch helper through an environment variable.
2. The tmux launch helper passes that PID into the new pane with `tmux split-window -e SASE_ARTIFACT_NOTIFY_PID=<pid>`.
3. The artifact viewer process sends `SIGUSR1` to that PID in a `finally` block when the viewer loop exits normally.
4. The viewer process also installs `SIGHUP` and `SIGTERM` handlers that exit through the same cleanup path. This covers
   direct tmux pane closure, which sends `SIGHUP` to the pane process.
5. Ace's `SIGUSR1` handler schedules an idempotent UI update that clears the tracked pane id and removes
   `-artifact-viewer-active` immediately. It does not run tmux subprocess checks, so the signal path is cheap and avoids
   a race where the pane still technically exists while the viewer process is exiting.
6. On Ace unmount/quit, restore the previous `SIGUSR1` handler.

This is event-driven: no additional timers, no polling loop, and no extra work unless an artifact pane is opened or
closed.

## Files To Change

- `src/sase/ace/tui/actions/agents/_panels.py`
  - Add signal handler install/restore helpers.
  - Set the notification PID environment only around tmux artifact viewer launches.
  - Clear the artifact layout directly when the close signal arrives.

- `src/sase/ace/tui/graphics/_viewer_launch.py`
  - Add the notification environment variable to tmux split-window launches.
  - Notify the parent PID on viewer process exit.
  - Convert `SIGHUP`/`SIGTERM` in the viewer process into normal cleanup exits.

- `src/sase/ace/tui/actions/lifecycle.py`
  - Restore the previous signal handler on unmount/quit.

- Tests under `tests/ace/tui/actions/` and `tests/ace/tui/artifact_viewer/`
  - Cover immediate layout clearing from the signal path.
  - Cover passing the notification PID into tmux.
  - Cover parent notification on viewer process exit.

## Verification

Run focused tests first:

- `pytest tests/ace/tui/actions/test_agent_artifact_image_actions.py`
- `pytest tests/ace/tui/artifact_viewer/test_tmux.py`

Then run the required repo check after code changes:

- `just install`
- `just check`
