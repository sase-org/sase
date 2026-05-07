---
create_time: 2026-05-07 10:44:54
status: done
prompt: sdd/prompts/202605/space_keymap_error_toast.md
---
# Plan: Convert Space Keymap VCS Detection Crash Into TUI Error Toast

## Problem

Pressing the `<space>` keymap in `sase ace` repeats the last `@`/`<space>` agent selection. If that saved selection
points at a project file whose workflow type cannot be detected by any installed workspace plugin,
`sase.workspace_provider.detect_workflow_type()` raises `ValueError`. The exception currently escapes the Textual action
path and crashes the TUI.

The traceback shows the failure in:

- `EntryPointsMixin.action_start_agent_from_changespec()`
- `EntryPointsMixin._start_custom_agent_from_selection()`
- `_vcs_prompt_prefix()`
- `workspace_provider.detect_workflow_type()`

## Goal

When the repeat-last `<space>` action cannot build a VCS prompt prefix because workflow detection fails, the TUI should
stay running and show an error toast explaining why the agent launch could not start.

## Scope

Primary scope is `src/sase/ace/tui/actions/agent_workflow/_entry_points.py`, where the prompt prefix is resolved for TUI
agent-start entry points.

This is presentation-layer behavior, so it belongs in the Python TUI action layer rather than in the Rust core boundary.
No workspace plugin behavior should be changed.

## Design

1. Add a small TUI-facing helper around `_vcs_prompt_prefix()` that catches `ValueError`, calls
   `self.notify(..., severity="error")`, and returns `None`.
2. Update the TUI agent-start entry points that synchronously build a VCS prefix to use the helper and return early when
   prefix resolution fails:
   - repeat-last selection via `<space>`
   - quick current-ChangeSpec launch
   - quick selected-agent launch
   - prompt-history lookup for last selection, which uses the same persisted selection mechanism
3. Keep `_vcs_prompt_prefix()` itself raising. It is a pure helper and existing non-TUI callers/tests can continue to
   see hard failures if they call it directly.
4. Catch only `ValueError`, because that is the documented “no plugin claims this project” behavior from
   `detect_workflow_type()`. Unexpected programming errors should remain visible.
5. Use an error message that includes enough context for the user to fix the environment, such as:
   `Cannot start agent for <name>: No workspace plugin detected ...`

## Tests

Add focused unit tests around `EntryPointsMixin` with a tiny fake app:

- when repeat-last `<space>` resolves a saved selection and `_vcs_prompt_prefix()` raises `ValueError`, the action
  should emit an error notification and not call the prompt bar/editor launch path
- when quick current-ChangeSpec launch hits the same error, it should emit an error notification and not save or mount
  prompt input

Existing repeat-launch tests are unrelated to prefix resolution and should remain unchanged.

## Verification

Run targeted pytest for the new tests first, then run `just install` if needed followed by `just check` before
finishing, per repo memory.
