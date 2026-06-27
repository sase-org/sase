---
create_time: 2026-06-27 13:24:59
status: done
prompt: sdd/prompts/202606/ctrl_g_ctrl_c_cancel_all.md
---
# Plan: Ctrl+G Ctrl+C Cancel All Prompt Panes

## Goal

Add a prompt-local `<ctrl+g><ctrl+c>` keymap that cancels the entire prompt stack instead of only the selected prompt
pane. The canceled history entry should be one combined prompt containing every non-empty pane in launch order, with
shared xprompt/frontmatter properties preserved when present.

Existing `<ctrl+c>` behavior must remain unchanged: in a multi-pane prompt stack it cancels only the selected pane and
keeps the prompt bar mounted; in single-pane prompt, feedback, and approve-prompt modes it cancels the whole bar through
the existing path.

## Current Behavior and Relevant Ownership

- `PromptTextArea._on_key()` handles bare `<ctrl+c>` and calls `PromptInputBar.action_cancel()`.
- `PromptInputBar.action_cancel()` removes only the selected pane when the bar is in prompt mode with more than one
  pane, then emits `PromptInputBar.Cancelled(..., keep_bar=True)`.
- The app handler records `keep_bar=True` cancellations through `_save_text_as_cancelled()` without unmounting the
  prompt bar.
- Whole-bar cancellation goes through `_unmount_prompt_bar()`, whose safety net calls `bar.current_prompt_text()`. That
  already uses `PromptStackState.join()` and therefore reattaches shared frontmatter/xprompt properties.
- The prompt-local `<ctrl+g>` prefix is table-driven in `_prompt_input_bar_g_prefix_actions.py` and is dispatched before
  the bare `<ctrl+c>` branch. As a result, `<ctrl+g><ctrl+c>` is currently an unused prompt-prefix continuation.
- Prompt history currently expands multi-prompts into both the combined prompt and individual segment entries. The new
  all-pane cancel needs an explicit "record only the combined prompt" path to satisfy the "single canceled prompt"
  requirement.

## User-Facing Semantics

- In prompt mode, `<ctrl+g><ctrl+c>` cancels all panes in the active prompt bar and dismisses the bar.
- The history text is the same canonical joined text used for whole-stack launch: non-empty panes joined with `\n---\n`,
  with shared YAML frontmatter prepended when present.
- Frontmatter-only drafts are still captured as the canceled prompt text if they pass the existing recordability rules.
- The action records file references from the combined prompt once, using the existing cancellation save path.
- If the combined prompt is empty or below the normal prompt-history threshold, the bar still cancels, but no
  saved-history toast is shown, matching existing cancellation behavior.
- `<ctrl+c>` keeps its current selected-pane behavior.
- `<ctrl+g><ctrl+c>` should work from INSERT and NORMAL prompt text-area modes. If focus is inside the frontmatter panel
  rows view, support the same chord by forwarding it to the host prompt bar; do not intercept ordinary editing keys in
  inline/raw frontmatter editing modes beyond this explicit prefix.

## Implementation Plan

1. Add a targeted prompt-history storage option.
   - Extend `sase.history.prompt_store.add_or_update_prompt()` with a keyword such as `record_segments: bool = True`.
   - Keep the default behavior unchanged for submitted multi-prompts, ordinary canceled prompts, and failed launches.
   - When `record_segments=False`, write or update only the exact prompt text passed by the caller, even if it contains
     multi-prompt separators.
   - Add history tests proving default multi-prompt behavior still records combined plus segments, while
     `record_segments=False` with `cancelled=True` records exactly one canceled entry.

2. Add an all-pane cancel event shape.
   - Extend `PromptInputBar.Cancelled` with a small flag such as `single_history_entry` or `record_segments`.
   - Default the flag so existing callers and tests keep current behavior.
   - Add `PromptInputBar.action_cancel_all()` that syncs live pane text, clears transient active-pane completion state,
     captures `current_prompt_text()`, and emits
     `Cancelled(cancelled_text=..., keep_bar=False, single_history_entry=True)`.
   - Do not remove individual panes in the widget before emitting the event; the app-level whole-bar path owns
     unmounting.

3. Wire the keymap through the existing prompt prefix table.
   - Add a Ctrl-G-only binding for key `"ctrl+c"` in `_PROMPT_G_PREFIX_BINDINGS`.
   - Point it at `action_cancel_all()`.
   - Add an availability method scoped to prompt mode. It can be always available in prompt mode because cancellation is
     useful even when no history record will be written.
   - Add a concise hint label such as `cancel all panes`.
   - Teach the prefix hint renderer to display `"ctrl+c"` as `^C`, so the hint reads as `^G^C`.

4. Handle the app-side save without double-writing.
   - In `PromptBarSubmitMixin.on_prompt_input_bar_cancelled()`, branch on the new all-pane/single-history flag before
     the existing whole-bar cancellation path.
   - Save `event.cancelled_text` through `_save_text_as_cancelled(..., record_segments=False)`.
   - Detach/unmount the prompt bar without invoking the cancellation safety net a second time.
   - Clear `_prompt_context` and reuse the existing whole-bar cancellation toast style when a record was actually
     written.
   - Keep the existing `keep_bar=True` per-pane path and ordinary whole-bar safety-net path unchanged.

5. Preserve xprompt/frontmatter properties.
   - Rely on `PromptInputBar.current_prompt_text()` / `PromptStackState.join(include_frontmatter=True)` for the
     canonical text.
   - Add a widget test with shared frontmatter, including an `xprompts:` property, to verify the emitted canceled text
     contains the frontmatter block followed by every pane.

6. Add focused tests.
   - Widget tests in the prompt-stack keymap/cancel area:
     - `<ctrl+g><ctrl+c>` from INSERT emits one non-`keep_bar` cancellation with all panes joined.
     - `<esc><ctrl+g><ctrl+c>` from NORMAL does the same.
     - The same action includes shared frontmatter/xprompt properties.
     - Existing bare `<ctrl+c>` selected-pane cancellation remains unchanged.
   - Prefix hint tests:
     - Ctrl-G hint entries include `("ctrl+c", "cancel all panes")` in prompt mode.
     - Rendered hints display `^G^C`.
     - The binding remains Ctrl-G-only and does not claim bare vim `g` continuations.
   - App-handler tests:
     - The all-pane cancellation flag saves with segment recording disabled, detaches the bar once, clears context, and
       avoids the safety-net double save.
     - Existing per-pane and ordinary whole-bar cancellation tests still pass.
   - Frontmatter-panel focus test if the forwarding path is implemented.

## Validation

Before implementation, run `just install` if the workspace environment has not already been prepared. After
implementation, run targeted tests for prompt history, prompt-stack cancellation, prompt-prefix hints, and prompt-bar
submit/cancel handlers, then run `just check`.

The implementation should avoid adding per-pane history writes or other loops on the TUI event path. The new all-pane
cancel should perform one combined history mutation, matching both the requested behavior and the existing TUI
responsiveness guidance.
