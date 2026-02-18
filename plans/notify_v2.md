---
bead_id: sase-em8
---

# Notification System Improvements

## Context

The `sase ace` TUI has a notification system that currently uses a small modal (80 chars wide) with a separate nested
file browser modal. The user wants three improvements: (1) a nearly full-screen split-pane notification popup, (2) a
persistent notification count indicator, and (3) better file inclusion from agent senders. These three phases are fully
parallelizable.

---

## Phase A: Notification Popup Redesign

**Goal**: Transform the `N` keymap modal from a small centered popup into a near-full-screen split-pane layout.

### Changes

**1. Remove ctrl+n/ctrl+p from `OptionListNavigationMixin`** (`src/sase/ace/tui/modals/base.py`)

- Remove lines 67-68 (`ctrl+n` and `ctrl+p` bindings) from `NAVIGATION_BINDINGS`
- j/k/up/down already cover navigation in all modals

**2. Rewrite `NotificationModal`** (`src/sase/ace/tui/modals/notification_modal.py`)

- New layout: `Horizontal` split with notification list on LEFT (~40%) and file content viewer on RIGHT (~60%)
- Remove `f` binding (show files) and `action_show_files()` method
- Add `ctrl+n`/`ctrl+p` bindings for cycling through files of the highlighted notification
- Track `_current_file_index: int` as instance state
- On `on_option_list_option_highlighted`: reset file index to 0, display first file
- File display: reuse `_EXTENSION_TO_LEXER` from `src/sase/ace/tui/widgets/file_panel.py` for syntax highlighting (same
  pattern as existing `NotificationFileBrowser._show_file_content()`)
- Show file title as `"File 1/3: ~/.sase/chats/foo.md"` above content
- When no files: show "No files attached" in right pane
- Update hints label: `"Enter: select  d: dismiss  C-n/C-p: next/prev file  R: read all  q: close"`

**3. Update TCSS** (`src/sase/ace/tui/styles.tcss`, lines 961-1038)

- Replace existing `NotificationModal` and `NotificationFileBrowser` style blocks
- New modal: `width: 95%; height: 90%` (nearly full screen)
- Left pane (`#notification-left`): `width: 40%; height: 100%`
- Right pane (`#notification-right`): `width: 60%; height: 100%` with left border
- File content area: scrollable with `height: 1fr`

**4. Delete `NotificationFileBrowser`**

- Delete `src/sase/ace/tui/modals/notification_file_browser.py`
- Remove import from `notification_modal.py` (line 20)
- Note: `NotificationFileBrowser` is NOT exported from `modals/__init__.py`, so no change needed there

**5. Update help modal** (`src/sase/ace/tui/modals/help_modal.py`)

- Per `src/sase/ace/CLAUDE.md` requirement: update `?` help popup to reflect new N modal keybindings

### Key files

- `src/sase/ace/tui/modals/notification_modal.py` (rewrite)
- `src/sase/ace/tui/modals/base.py` (remove 2 bindings)
- `src/sase/ace/tui/styles.tcss` (lines 961-1038)
- `src/sase/ace/tui/modals/notification_file_browser.py` (delete)
- `src/sase/ace/tui/modals/help_modal.py` (update hints)
- Reuse: `src/sase/ace/tui/widgets/file_panel.py` → `_EXTENSION_TO_LEXER` dict

---

## Phase B: Persistent Notification Indicator

**Goal**: Add an always-visible unread notification count in the top-right of the TUI.

### Changes

**1. Create `NotificationIndicator` widget** (`src/sase/ace/tui/widgets/notification_indicator.py`)

- New `Static` subclass with `set_count(count: int)` method
- When count > 0: bold gold background badge (e.g., `" \u2709 3 "` styled `"bold black on #FFD700"`)
- When count == 0: dim styled (e.g., `" \u2709 0 "` styled `"dim"`)
- `_refresh_display()` called on mount and count change

**2. Export from `widgets/__init__.py`**

- Add `NotificationIndicator` to imports and `__all__`

**3. Modify `app.py` compose()** (line 313-314)

- Wrap `TabBar` and new `NotificationIndicator` in a `Horizontal(id="top-bar")`:
  ```python
  yield Header()
  with Horizontal(id="top-bar"):
      yield TabBar(id="tab-bar")
      yield NotificationIndicator(id="notification-indicator")
  ```

**4. Add TCSS styles** (`src/sase/ace/tui/styles.tcss`)

- Add new section (after TabBar styles, before notification modal styles):
  ```tcss
  #top-bar { height: auto; max-height: 1; }
  #notification-indicator { width: auto; content-align: right middle; }
  ```
- Adjust `#tab-bar` to `width: 1fr` so indicator is right-aligned

**5. Update polling** (`src/sase/ace/tui/actions/agents/_notifications.py`)

- In `_poll_agent_completions()`: after computing `unread_count`, call `indicator.set_count(unread_count)` on the
  `#notification-indicator` widget
- In `action_show_notifications()` `_on_dismiss` callback: update indicator after marking read

**6. Initialize on mount** (`src/sase/ace/tui/app.py`)

- In `on_mount()` or `_initialize_agent_tracking()`: seed indicator with initial unread count

### Key files

- `src/sase/ace/tui/widgets/notification_indicator.py` (new)
- `src/sase/ace/tui/widgets/__init__.py` (export)
- `src/sase/ace/tui/app.py` (compose + mount)
- `src/sase/ace/tui/styles.tcss` (new section)
- `src/sase/ace/tui/actions/agents/_notifications.py` (polling updates)

---

## Phase C: Include Chat and Diff Files in Notifications

**Goal**: Ensure notifications include the agent's chat history file and any diff file produced.

### Changes

**1. Update `notify_workflow_complete()` signature** (`src/sase/notifications/senders.py`)

- Add `extra_files: list[str] | None = None` parameter
- Prepend `extra_files` to the `files` list (before `project_file`)

**2. Update `axe_run_agent_runner.py`** (line 332-340)

- `saved_path` (chat history) and `diff_path` are already available at this point
- Build `extra_files` list from these and pass to `notify_workflow_complete()`

**3. Update `axe_crs_runner.py`** (line 128-141)

- Chat is saved inside `invoke_agent()` → `postprocessing._save_chat_and_log()` chain
- After `invoke_agent()` returns, use `list_chat_histories()` from `sase.chat_history` to find the most recent chat file
  matching the changespec name
- Pass as `extra_files`

**4. Update `axe_fix_hook_runner.py`** (line 240-253)

- Same pattern as CRS: find most recent chat file after `invoke_agent()` completes
- Pass as `extra_files`

**5. Update `axe_run_workflow_runner.py`** (line 202-210)

- After workflow execution, find recent chat file(s) via `list_chat_histories()`
- Extract `diff_path` from workflow state (use `_extract_step_output_and_diff_path()` pattern from agent runner, or read
  `workflow_state.json` directly)
- Pass as `extra_files`

### Key files

- `src/sase/notifications/senders.py` (add `extra_files` param)
- `src/sase/axe_run_agent_runner.py` (pass `saved_path` + `diff_path`)
- `src/sase/axe_crs_runner.py` (find chat file after invoke_agent)
- `src/sase/axe_fix_hook_runner.py` (find chat file after invoke_agent)
- `src/sase/axe_run_workflow_runner.py` (find chat + diff files)
- Reuse: `sase.chat_history.list_chat_histories()` for discovering recent chats

---

## Phase Dependencies

All three phases are **fully parallelizable**. The only shared file is `styles.tcss`, where Phase A and B modify
different sections (Phase A: lines 961-1038; Phase B: new section near TabBar styles).

## Verification

For each phase, run `just check` (fmt + lint + mypy + test). Then manually test with `sase ace`:

- **Phase A**: Press `N`, verify near-full-screen split-pane. Highlight notifications with j/k, verify right pane shows
  first file. Press Ctrl+N/Ctrl+P to cycle files. Confirm `f` key no longer works. Verify j/k still works in other
  modals.
- **Phase B**: Verify indicator visible in top-right corner at startup (showing 0). Trigger a notification (run an
  agent), verify count updates and bell rings. Switch tabs — indicator should remain visible.
- **Phase C**: Run an agent, then press `N` to view its notification. Verify chat `.md` file and diff file appear in the
  file list.
