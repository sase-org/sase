---
create_time: 2026-06-05 10:37:27
status: done
prompt: sdd/prompts/202606/prompt_ctrl_l_completion.md
---
# Prompt Ctrl+L Completion Plan

## Diagnosis

The prompt input's `<ctrl+l>` path only accepts an already-cached soft completion:

- `PromptTextArea._on_key()` calls `_accept_soft_completion()` for `ctrl+l`.
- `_accept_soft_completion()` returns `False` when `_soft_completion` is `None` or stale.
- The live suggestion is populated asynchronously by a debounced timer (`debounce_ms`, default 90ms).
- If the user types an xprompt fragment and immediately presses `<ctrl+l>`, there may be no cached suggestion yet. The
  keypress falls through to app-level bindings, and the debounce timer may render the suggestion after the attempted
  accept, making the key appear ignored.

This reproduces without file changes by seeding warm xprompt entries, typing a long wrapped line ending in `#r`, and
pressing `<ctrl+l>` before waiting for debounce. The prompt remains unchanged, then the soft suggestion appears shortly
afterward. Waiting for the debounce first makes the same long-line completion work, so token extraction and wrapped-line
offset math are not the primary failure.

The long-line symptom is plausible because wrapped prompt input triggers additional cursor/height refresh churn and a
user is likely to hit `<ctrl+l>` immediately after typing the final xprompt characters at the bottom of the prompt bar.

## Fix Strategy

Make `<ctrl+l>` an explicit accept-or-compute action:

1. Keep the existing fast path: accept the cached soft completion when it is current.
2. If the cached suggestion is missing or stale, synchronously build a fresh soft completion from the current
   `text`/cursor state using the same `build_prompt_soft_completion()` logic.
3. Use warm xprompt entries when available; for an explicit user keypress, fall back to the same synchronous xprompt
   assist entry build path already allowed by manual `Ctrl+T` completion when needed.
4. If a fresh suggestion is found, accept it immediately with the existing xprompt skeleton / argument hint behavior.
5. If no suggestion is possible, preserve the current behavior and let the key fall through to app-level
   `dismiss_toasts`.

This keeps automatic completion non-blocking while making the explicit key deterministic.

## Implementation Steps

1. Add a helper on `PromptSoftCompletionMixin`, likely `_build_current_soft_completion()`, that computes the best
   current suggestion from `self.text` and `self.cursor_location`.
2. Add `_accept_or_build_soft_completion()` that tries `_accept_soft_completion()` first, then computes and accepts a
   fresh suggestion if soft completion is not blocked.
3. Update `PromptTextArea._on_key()` to use `_accept_or_build_soft_completion()` for `ctrl+l`.
4. Keep timer cancellation and stale-suggestion clearing behavior centralized through the existing accept/clear helpers.

## Tests

1. Add a focused widget regression in `tests/ace/tui/widgets/test_prompt_live_completion.py`:
   - Seed xprompt entries.
   - Load or type a long single physical line ending in `#r`.
   - Trigger the completion context change but do not wait for debounce.
   - Press `<ctrl+l>`.
   - Assert the prompt immediately changes to the canonical xprompt insertion.
2. Keep existing tests for `Enter` submitting with a visible soft suggestion, `Ctrl+T` panel behavior, directives, and
   xprompt argument completion unchanged.

## Validation

Run focused prompt completion tests first:

```bash
.venv/bin/pytest tests/ace/tui/widgets/test_prompt_live_completion.py tests/ace/tui/widgets/test_xprompt_completion.py
```

Because this is a source change in the sase repo, run `just install` if needed and then `just check` before reporting
completion.
