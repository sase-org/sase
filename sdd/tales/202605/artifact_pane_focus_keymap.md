---
create_time: 2026-05-09 03:44:45
status: done
prompt: sdd/prompts/202605/artifact_pane_focus_keymap.md
---
# Artifact Pane Focus Keymap Plan

## Goal

Add a two-way focus toggle between the Ace TUI pane and the tmux artifact viewer pane:

- In the Ace TUI, `l` should switch focus to the tracked artifact tmux pane, but only while that pane is live.
- Inside the artifact viewer pane, `h` should switch focus back to the originating Ace TUI pane.
- Existing `l` behavior should continue to work everywhere else, because `l` is already the default `expand_or_layout`
  key.

## Current Context

The previous artifact viewer change already gives us the key pieces to build on:

- `AgentPanelsMixin` tracks the artifact pane id in `_artifact_tmux_pane_id`.
- `_artifact_tmux_pane_visible()` checks tmux state, clears stale pane ids, and syncs the collapsed Agents layout.
- `A` toggles the tracked artifact pane: live pane means close it, stale pane means clear state, otherwise open artifact
  selection.
- The artifact viewer launches through `view_artifact_files_in_tmux_pane()`, using
  `tmux split-window -h -P -F "#{pane_id}" ...`.
- The standalone artifact viewer key loop currently handles `j/k/n/p/r/q`, and `h` is unused there.

Important constraint: `l` already maps to `expand_or_layout` in `src/sase/default_config.yml` and the keymap type
metadata. Adding a second app binding on `l` would be fragile. The cleaner design is to make the existing `l` action
context-sensitive while the artifact pane is visible.

## Design

### 1. Add tmux pane selection helpers

In `src/sase/ace/tui/graphics/_viewer_launch.py`, add a small helper that focuses a tmux pane:

- `select_tmux_pane(pane_id: str) -> ArtifactViewerResult`
- Validate the same conditions as the close helper where appropriate: non-empty pane id, tmux session, tmux executable.
- Run `tmux select-pane -t <pane_id>`.
- Return `ArtifactViewerResult(True)` on success or a warning result with a stable code such as `tmux_select_failed` on
  failure.

Also add a helper or local launch logic to capture the originating pane id:

- Prefer `os.environ["TMUX_PANE"]` when present.
- When launching the split artifact pane, pass that origin id into the new pane environment with tmux
  `split-window -e SASE_ARTIFACT_RETURN_PANE_ID=<origin-pane>`.
- Keep the existing viewer CLI unchanged; this avoids adding user-facing flags and preserves direct `python -m ...`
  behavior.

Export the new selection helper through `graphics/viewer.py` and `graphics/__init__.py` for the TUI action and tests.

### 2. Route Ace TUI `l` to the artifact pane only when live

In `AgentPanelsMixin`, add a focused helper such as:

- `_focus_tracked_artifact_tmux_pane() -> bool`

Behavior:

- Return `False` if the current tab is not `agents` or if `_artifact_tmux_pane_visible()` is false.
- If visible, call the new tmux selection helper with `_artifact_tmux_pane_id`.
- On success, return `True` without additional UI churn.
- On failure, notify with the warning text, resync/clear stale layout state where appropriate, and still return `True`
  because `l` was consumed by the artifact-focus affordance.

Then update `AgentFoldingMixin.action_expand_or_layout()`:

- On the Agents tab, first ask `_focus_tracked_artifact_tmux_pane()` whether it handled the key.
- If handled, return.
- Otherwise, keep the existing `_expand_fold()` behavior.
- Leave ChangeSpecs and Axe behavior unchanged.

This preserves all existing keymap configuration while making `l` artifact-focus-specific exactly when the artifact pane
is visible.

### 3. Surface the conditional `l` affordance in the footer

The footer is intended for conditional and transient actions, so the artifact-pane `l` affordance should appear there
only while active.

Update the Agents footer path:

- Add an `artifact_viewer_active: bool = False` parameter to `KeybindingFooter.update_agent_bindings()` and
  `_compute_agent_bindings()`.
- Pass that value from the Agents display refresh using the existing pane visibility helper.
- When true, append `(self._kd("expand_or_layout"), "artifact pane")` or similar.

This does not require changing `default_config.yml` because the action/key already exists there. It only changes when
the footer advertises the transient behavior.

### 4. Add `h` in the artifact viewer loop

In `src/sase/ace/tui/graphics/_viewer_loop.py`:

- Add optional `return_pane_id: str | None = None` support to the sequence/page loop functions or to the shared key
  helpers.
- Make `page_loop_available_keys(..., return_pane_available=True)` include `h`.
- Add `h: tui` or `h: Ace` to `print_page_prompt()` when the return pane is available.
- When the user presses `h`, call `select_tmux_pane(return_pane_id)` and continue showing the same artifact/page. Do not
  quit or close the artifact pane.
- If selection fails, keep the viewer running; the failure can be silent in the pane or printed minimally because the
  user is still in the viewer.

In `view_artifact_files()`, read `SASE_ARTIFACT_RETURN_PANE_ID` from the environment and pass it to the loop. Direct
non-tmux viewer usage will have no return pane, so `h` will not appear and will not be accepted.

### 5. Tests

Add focused tests without broad integration churn:

- `tests/ace/tui/artifact_viewer/test_tmux.py`
  - `view_artifact_file_in_tmux_pane()` passes `-e SASE_ARTIFACT_RETURN_PANE_ID=<origin>` when `TMUX_PANE` is set.
  - `select_tmux_pane()` invokes `tmux select-pane -t <pane>` and surfaces failures.

- `tests/ace/tui/actions/test_agent_artifact_image_actions.py` or a small folding/action test
  - With `_artifact_tmux_pane_id` live and tmux mocks returning success, `action_expand_or_layout()` /
    `_focus_tracked_artifact_tmux_pane()` focuses `%7` and does not call fold expansion.
  - With no live pane, existing `l` expansion behavior remains unchanged.
  - Stale pane ids clear layout and do not select a pane.

- `tests/ace/tui/artifact_viewer/test_loops.py`
  - `page_loop_available_keys(..., return_pane_available=True)` includes `h`.
  - The prompt includes the reverse-focus label only when applicable.
  - Pressing `h` calls the injected/select helper and keeps the same page/artifact active before later quitting.

- Footer tests if existing coverage is nearby:
  - Agent footer includes the `l artifact pane` affordance only when `artifact_viewer_active=True`.

## Verification

After implementation:

1. Run focused tests:

   ```bash
   just test tests/ace/tui/artifact_viewer/test_tmux.py tests/ace/tui/artifact_viewer/test_loops.py tests/ace/tui/actions/test_agent_artifact_image_actions.py
   ```

2. Run `just lint`.

3. Because this repo requires it after code changes, run `just check` before the final response.

If `just check` still hits unrelated full-suite failures from the current baseline, report the exact failing area and
confirm the focused tests plus lint status.
