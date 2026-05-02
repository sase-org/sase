---
create_time: 2026-04-02 15:07:25
status: done
prompt: sdd/prompts/202604/approve_options_prompt_delegate.md
---

# Plan: Delegate ApproveOptionsModal prompt editing to PromptInputBar

## Problem

The `ApproveOptionsModal` embeds a `_PromptTextArea` for entering an additional coder prompt. Despite multiple hardening
attempts (event barriers, printable char filtering), text input doesn't work reliably in the real AceApp environment due
to Textual's event propagation model conflicting with the modal's `on_key` handler.

## Solution

Replace the broken TextArea with a **display Static + `p` key binding** that delegates prompt editing to the existing
`PromptInputBar` widget, which is proven to work for text input (already used for feedback mode and regular prompts).

## User-facing flow

1. User presses `A` in PlanApprovalModal → ApproveOptionsModal opens
2. Modal shows: two toggle switches + a read-only display of the current prompt (initially "none") + `p` key to edit
3. User presses `p` → modal chain dismisses, PromptInputBar mounts at screen bottom
4. User types prompt in PromptInputBar (full editing capabilities: vim keys, tab completion, Ctrl+G editor, etc.)
5. User presses Enter → PromptInputBar submits, PlanApprovalModal re-opens, auto-pushes ApproveOptionsModal with the
   captured prompt + preserved switch state
6. User sees their prompt displayed in the modal, adjusts switches if needed, presses Enter → approval fires

On cancel (Esc in PromptInputBar): same re-push but with unchanged prompt text.

## Architecture

### Data flow

```
ApproveOptionsModal --dismiss(EditPrompt)--> PlanApprovalModal
PlanApprovalModal --dismiss(approve_prompt_edit)--> handle_plan_approval on_dismiss
on_dismiss --> stores ApprovePromptContext, mounts PromptInputBar(mode="approve_prompt")
PromptInputBar.Submitted --> PromptBarMixin.on_prompt_input_bar_submitted
  --> re-pushes PlanApprovalModal(pending_approve_state=...) which auto-pushes ApproveOptionsModal
```

This follows the exact same pattern as the existing feedback mode:

- `PlanFeedbackContext` → `ApprovePromptContext`
- `mode="feedback"` → `mode="approve_prompt"`
- `_handle_plan_feedback_submitted` → `_handle_approve_prompt_submitted`

### New types

**`ApproveOptionsEditPrompt`** (in `approve_options_modal.py`): Sentinel result from ApproveOptionsModal indicating the
user wants to edit the prompt. Carries current switch state and prompt text so the round-trip preserves all state.

**`ApprovePromptContext`** (in `_types.py`): Context stored on the app while PromptInputBar is active for approve-prompt
editing. Carries notification metadata (to re-push PlanApprovalModal) + switch state + current prompt.

**`PendingApproveState`** (in `plan_approval_modal.py`): Optional init param for PlanApprovalModal that triggers
auto-push of ApproveOptionsModal on mount.

## Changes by file

### `src/sase/ace/tui/modals/approve_options_modal.py`

- Remove `_PromptTextArea` class entirely
- Add `ApproveOptionsEditPrompt` dataclass
- `ApproveOptionsModal.__init__`: accept `commit_plan`, `run_coder`, `coder_prompt` keyword args for state restoration
- `compose()`: replace TextArea with a Static displaying the current prompt (truncated if long, "none" if empty)
- Add `p` key binding → `action_edit_prompt()` which dismisses with `ApproveOptionsEditPrompt`
- Simplify `on_key`: remove printable char filtering (no more TextArea to worry about), keep enter/escape/ctrl+n/ctrl+p
- Update footer hints to show `p` key
- Modal type param changes to `ModalScreen[ApproveOptionsResult | ApproveOptionsEditPrompt | None]`

### `src/sase/ace/tui/modals/plan_approval_modal.py`

- Add `PendingApproveState` dataclass (or just a dict) with `commit_plan`, `run_coder`, `coder_prompt` fields
- `PlanApprovalModal.__init__`: accept optional `pending_approve_state` param
- `on_mount`: if `pending_approve_state` is set, auto-call `_push_approve_options()` with the state
- Refactor `action_approve_options`: extract `_push_approve_options(commit_plan, run_coder, coder_prompt)` method
- In the options dismiss callback, handle `ApproveOptionsEditPrompt`: dismiss PlanApprovalModal with a new
  `PlanApprovalResult(action="approve_prompt_edit", commit_plan=..., run_coder=..., coder_prompt=...)`

### `src/sase/ace/tui/actions/agents/_types.py`

- Add `ApprovePromptContext` dataclass mirroring `PlanFeedbackContext` but with additional fields: `commit_plan: bool`,
  `run_coder: bool`, `current_prompt: str`

### `src/sase/ace/tui/actions/agents/_notification_modals.py`

- In `handle_plan_approval`'s `on_dismiss`: add handler for `action="approve_prompt_edit"`
  - Create `ApprovePromptContext` from the result + notification metadata
  - Store as `app._approve_prompt_context`
  - Mount `PromptInputBar(initial_value=current_prompt, mode="approve_prompt", id="prompt-input-bar")`

### `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`

- Add `_approve_prompt_context` to `PromptBarMixin` class attributes
- In `on_prompt_input_bar_submitted`: add `mode == "approve_prompt"` branch
  - Call `_handle_approve_prompt_submitted(event.value)`
- In `on_prompt_input_bar_cancelled`: add `mode == "approve_prompt"` branch
  - Call `_handle_approve_prompt_cancelled()`
- `_handle_approve_prompt_submitted(prompt)`:
  - Read context, unmount bar
  - Re-push `PlanApprovalModal(plan_file, pending_approve_state=PendingApproveState(commit, coder, prompt))`
- `_handle_approve_prompt_cancelled()`:
  - Read context, unmount bar
  - Re-push `PlanApprovalModal(plan_file, pending_approve_state=PendingApproveState(commit, coder, original_prompt))`
  - (preserves original prompt on cancel)

### `src/sase/ace/tui/styles.tcss`

- Remove `#coder-prompt-input` styles
- Add styles for the new prompt display Static (e.g., `#coder-prompt-display`)

### `tests/test_approve_options_modal.py`

- Remove tests for TextArea typing (no longer applicable)
- Remove `_PromptTextArea` tests
- Add tests for `p` key triggering `ApproveOptionsEditPrompt` dismiss
- Update constraint tests (prompt area disabled/enabled → prompt button disabled/enabled)
- Add test for initial state restoration via constructor params
- Keep switch toggle and enter/escape tests (still valid)

## Edge cases

- **Coder OFF**: The `p` key and prompt display should be disabled/hidden when coder switch is OFF (prompt is irrelevant
  without a coder agent). The `_sync_constraints` method handles this.
- **Empty prompt**: Display "none" in the Static. On submit with empty PromptInputBar, treat as no prompt (same as
  current behavior).
- **Long prompt**: Truncate display in the Static with "..." - the full text is preserved in state.
