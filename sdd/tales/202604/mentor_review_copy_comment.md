---
create_time: 2026-04-19 17:00:10
status: done
prompt: sdd/prompts/202604/mentor_review_copy_comment.md
---

# Plan: Add `y` Copy-Comment Keymap to Mentor Review Modal

## Problem

When reviewing mentor comments in the Mentor Review modal, there's no ergonomic way to copy the currently selected
comment. Users who want to quote the comment in a follow-up agent prompt, paste it into a ChangeSpec description, or
share it in Slack must manually select the text in the terminal (which is fiddly in a TUI modal) or retype it. A
Vim-style `y` (yank) keymap that copies the selected comment to the system clipboard closes this gap.

## Design

Add a `y` keymap to `MentorReviewModal` that copies the currently selected mentor comment's contents to the system
clipboard using the existing `copy_to_system_clipboard()` helper. No persistence or state change — purely ephemeral,
with a toast notification for feedback.

### Key choice: `y`

Consistent with Vim's yank convention. Currently unused in the modal's BINDINGS. Follows the precedent set by
`prompt_history_modal.py` (which uses `ctrl+y`) and the Vim normal-mode ops in `_vim_normal_ops.py` — `y` is the
established "copy" verb in this codebase.

### Copy format (design decision — please confirm)

A mentor comment dict has five fields: `focus_name`, `file_path`, `line_number`, `description`, `severity`. The useful
minimum for pasting into another context is `file:line` + `description`, so the user retains location context with the
text:

```
<file_path>:<line_number>
<description>
```

This mirrors how the main panel presents the comment (minus severity/focus chrome and the code snippet). Alternatives to
consider:

- **Description only** — smallest, but loses file location and becomes ambiguous if multiple mentors comment on similar
  things.
- **Full metadata block** — includes focus/severity as well. More complete but noisier; most downstream uses won't want
  severity labels inline.

Recommendation: the `file:line` + description format. If later use cases demand richer output, we can add a `Y`
(shift-y) variant for a verbose dump without breaking the default.

### Edge cases

- **No mentors / no comments for current mentor**: action is a silent no-op (guard matches the pattern in
  `action_toggle_accept`, `action_next_comment`, etc.). The `y` binding appears regardless, but pressing it on a mentor
  with no comments does nothing — consistent with how `<space>` behaves.
- **Clipboard tool missing** (`xclip` not installed on Linux, unsupported OS): `copy_to_system_clipboard()` returns
  `False`; show `"Failed to copy to clipboard"` notification with `severity="error"`, matching the
  `prompt_history_modal` pattern.
- **Success**: show `"Copied comment to clipboard"` notification.

### No persistence, no refresh

Copy is a pure side-effect on the system clipboard. No acceptance state change, no read-state change, no UI redraw
needed. Do **not** call `self._refresh_all()` — that would needlessly re-render and mark the comment as read again
(already marked on initial display).

## Changes

**`src/sase/ace/tui/modals/mentor_review_modal.py`**

1. **BINDINGS** (lines 43–59) — Add one tuple. Natural placement is after the acceptance block (`space`, `a`, `A`) and
   before the mentor-profile actions (`r`, `K`), grouping it with "actions that operate on the current comment":

   ```python
   ("y", "copy_comment", "Copy comment"),
   ```

2. **New action handler `action_copy_comment`** — Follows the guard pattern from `action_toggle_accept`:
   - Fetch `self._current_mentor()`; bail silently if `None` or `mentor.comments` is empty.
   - Index into `mentor.comments[self._comment_idx]`.
   - Format the content as `f"{comment['file_path']}:{comment['line_number']}\n{comment['description']}"`.
   - Lazy-import `copy_to_system_clipboard` from `sase.ace.tui.actions.clipboard` (matches `prompt_history_modal` style
     — avoids paying the import cost at module load for every TUI session).
   - Call `self.app.notify(...)` with success or error message based on the return value.

3. **Footer bindings list** (lines 358–368) — Add `("y", "copy")` so users discover the feature. Natural placement is
   after the apply actions but before `K`/`r`/`q`:

   ```python
   ("y", "copy"),
   ```

**`tests/test_mentor_review_modal.py`**

Add tests following the direct-action-invocation pattern used throughout the file (e.g. `test_modal_toggle_accept`):

- **`test_copy_comment_copies_current`** — patches `copy_to_system_clipboard`, calls `action_copy_comment`, asserts the
  patched function received text containing the current comment's `file_path`, `line_number`, and `description`.
- **`test_copy_comment_no_op_when_mentor_has_no_comments`** — sets up a modal with an empty-comments mentor, patches the
  clipboard helper, asserts it was **not** called and no exception raised.
- **`test_copy_comment_notifies_on_failure`** — patches `copy_to_system_clipboard` to return `False`, verifies
  error-severity notification path (may require mocking `self.app.notify` via a simple spy; check
  `test_modal_toggle_accept` for whether `modal.app` is already wired in tests, and if not, follow whatever pattern the
  existing `action_apply_commit` tests use for notification-dependent actions).

## Files that deliberately do NOT change

- **`src/sase/default_config.yml`** — Mentor Review modal keymaps are hardcoded in the modal's `BINDINGS` class
  variable, not driven by config. The memory note "update `default_config.yml` when changing keymaps" applies only to
  configurable keymaps (leader-mode entries, main TUI bindings), not modal-local ones. Grep for `mentor` in
  `default_config.yml` confirms only the leader-mode launcher (`review_mentors: "m"`) lives there — the modal's internal
  `n`/`p`/`j`/`k`/`space`/etc. are all in `BINDINGS`.
- **`src/sase/ace/tui/modals/help_modal/bindings.py`** — Only documents leader-mode launchers and global actions, not
  modal-internal bindings. The mentor review modal's own footer (updated above) is what users see while the modal is
  open.

## Out of scope

- A richer `Y` (verbose) copy variant — defer until there's a concrete need.
- Copying the code snippet along with the comment — the snippet comes from the working tree / file snapshots, not the
  comment itself, and bundling it would blur the "copy the comment" semantics. Users who want the code can copy from
  their editor.
- Copying all accepted comments in one go — a plausible future extension (`ctrl+y` or similar), but out of scope here.
