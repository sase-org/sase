---
create_time: 2026-06-17 16:11:30
status: done
prompt: sdd/prompts/202606/prompt_g_enter_submit.md
---
# Plan: Move Current Prompt Submit From Ctrl+Shift+S To g<enter>

## Context

The current direct "submit only the current prompt pane" accelerator is handled in
`PromptTextAreaKeyHandlingMixin._on_key` as `ctrl+shift+s`. It only fires for multi-pane prompt stacks and then reuses
the existing selected-pane submit path through `PromptTextArea.action_submit_prompt()` and
`PromptInputBar._handle_text_submission()`.

That submit path is the behavior to preserve: it launches the active pane as a single agent, re-attaches prompt-level
frontmatter, removes the launched pane while keeping the bar mounted when other panes remain, drops an empty selected
pane without launching, and falls back to the normal single-pane submit path when only one pane remains.

Prompt-local `g` keymaps are already driven by a declarative table in `PromptInputBarStackActionsMixin`; the same table
feeds both dispatch and the which-key style hint panel shown after pressing `g` in prompt NORMAL mode. This is the right
home for `g<enter>`, but `Enter` is currently intercepted before normal-mode pending-key dispatch, so the implementation
needs to handle that ordering explicitly.

## Implementation Plan

1. Add a prompt `g` prefix binding for `enter`.
   - Add an `enter` continuation to the prompt `g` prefix binding table.
   - Route it to a small prompt-bar action that reuses the existing current-pane submit path instead of creating a
     second launch path.
   - Keep the action prompt-mode scoped and normal-mode-only through the existing `g` prefix dispatch.

2. Make `g<enter>` win over bare `Enter` while a `g` prefix is pending.
   - Adjust prompt text-area key handling so `g` followed by `Enter` reaches normal pending-key dispatch.
   - Preserve current bare `Enter` behavior: single-pane submit, multi-pane submit chooser, and file-completion
     acceptance.
   - Preserve existing Vim `g` fallthrough commands such as `gg`, `ge`, `gU`, and unknown `gX` cleanup.

3. Render and advertise the new key cleanly.
   - Extend prompt `g` hint rendering so the continuation displays as `g<enter>` rather than `genter`.
   - Add the `g<enter>` entry to the transient hint panel shown after pressing `g` in prompt NORMAL mode.
   - Update prompt input subtitles, help modal prompt-input bindings, and docs to stop advertising `Ctrl+Shift+S` and
     point users at `g<enter>` for the direct current-pane launch.

4. Retire the unreliable `Ctrl+Shift+S` prompt-input accelerator.
   - Remove the prompt text-area direct `ctrl+shift+s` branch.
   - Remove the hidden `ctrl+shift+s` shortcut from the submit-choice modal and keep `c` as the modal's explicit
     "current pane" choice.
   - Update nearby comments/docstrings so they describe `g<enter>` and the chooser-current path accurately.

5. Update regression coverage.
   - Update current-pane submit tests to drive `Esc`, `g`, `Enter` instead of `ctrl+shift+s`.
   - Add or update tests proving `g<enter>` submits the active pane, preserves frontmatter behavior, drains prompt
     stacks one pane at a time, and leaves bare `Enter` unchanged.
   - Update `g` prefix hint tests so `g<enter>` appears in the available hints and dispatch table.
   - Update help-modal tests and intentional visual snapshots affected by the new hint row or modal footer copy.

6. Validate.
   - Run the focused prompt-widget and help tests first.
   - Run the affected visual snapshot tests, updating goldens only for the intentional UI text/layout changes.
   - Run `just install` first if the workspace environment needs it, then run `just check` before finishing because
     implementation files will change.

## Non-Goals

- No Rust core or backend launch behavior changes are needed; this is a TUI key dispatch, hint, documentation, and test
  update.
- No default configurable app keymap changes are expected, because this prompt text-area accelerator is not currently
  sourced from `default_config.yml`.
