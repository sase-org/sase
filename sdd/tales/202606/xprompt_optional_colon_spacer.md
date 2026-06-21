---
create_time: 2026-06-21 18:56:45
status: done
prompt: sdd/prompts/202606/xprompt_optional_colon_spacer.md
---
# Auto-delete Optional XPrompt Spacer Before Colon

## Goal

When an xprompt completion inserts a deliberate trailing spacer for an xprompt that has user-facing optional inputs but
no required inputs, typing `:` immediately afterward should replace that spacer with the colon. The common flow should
become:

```text
#foobar |   -> user types ":" ->   #foobar:|
```

This should remove the current need to type `<backspace>:` after accepting the xprompt, while preserving the spacer for
the normal no-argument case.

## Current Behavior

The ACE prompt input and the xprompt LSP both build completion skeletons from required inputs only:

- One required path/word/line input: `#name:`
- One required text input: `#name::`
- Multiple required inputs: `#name($0)`
- No required inputs: `#name `

That last branch currently covers both true no-input xprompts and optional-only xprompts. The requested behavior should
target optional-only xprompts, not every completion that happens to end in a space.

Neovim has two relevant paths:

- Native/LSP completion comes from `sase-core` and receives the same `#optional ` snippet text.
- The legacy picker / `#@` path in `sase-nvim` uses picker catalog insertion. During implementation, verify whether it
  already inserts the optional spacer in the running path; only attach the colon cleanup to picker insertions that
  actually create that spacer.

## Behavioral Contract

1. If an accepted xprompt has at least one user-facing input and all of those inputs are optional, and the accept path
   inserts a single trailing space after the reference, then the next typed `:` replaces that space.
2. True no-input xprompts keep their existing behavior. Typing `:` after `#plain ` should not be rewritten solely
   because the text matches a reference.
3. Required-input xprompts are unchanged because their completion already inserts `:`, `::`, or `(...)`.
4. Slash-skill references are unchanged unless a future path explicitly starts inserting an optional xprompt spacer for
   them.
5. The rewrite is ephemeral. If the user types any other character, moves away, edits the prompt, or the text no longer
   matches the accepted completion span, the pending spacer state is cleared.

## Design

Keep the existing skeletons. The trailing spacer is useful when the user does not want to provide optional inputs, so
the fix should be a narrow edit-layer convenience rather than changing completion output globally.

Introduce a small "pending optional xprompt spacer" concept in each editing frontend:

- It records the reference insertion, the absolute position of the inserted spacer, and enough target identity to
  validate that the cursor is still immediately after that spacer.
- It is set only by completion accept paths that have the selected xprompt metadata.
- It is consumed only when the next printable character is `:`.

The predicate should be shared or mirrored consistently:

```text
optional-only = entry.inputs is non-empty AND no entry.inputs are required
```

## ACE Prompt Input

Implement the ACE side in the `sase` repo.

1. Add a focused helper near the existing xprompt assist/skeleton helpers:
   - `has_only_optional_inputs(entry)` or equivalent.
   - A helper to determine whether a skeleton insertion ended with an optional spacer.
2. Add prompt-text-area state for the pending spacer. A small dataclass is preferable to loose offsets.
3. Set pending spacer state after smart xprompt skeleton insertion succeeds in all existing accept paths:
   - `Ctrl+T` single-candidate accept and panel accept through `_accept_xprompt_completion_candidate`.
   - Soft completion accept through `_accept_soft_completion`.
   - `#@` / selector insertion through `_insert_xprompt_smart_snippet`.
4. Intercept `:` early in insert-mode key handling, before TextArea default insertion:
   - Validate pending state against current text and cursor.
   - Replace the single space range with `:`.
   - Clear pending state.
   - Refresh xprompt arg completion/hint state from the new cursor position.
5. Clear pending state on any non-matching keypress or completion-state reset.

Focused ACE tests:

- Optional-only `Ctrl+T` single-candidate completion followed by `:` becomes `#optional:`.
- Optional-only panel accept followed by `:` becomes `#optional:`.
- Optional-only soft completion followed by `:` becomes `#optional:`.
- Optional-only `#@`/selector smart insertion followed by `:` becomes `#optional:`.
- True no-input xprompt followed by `:` does not use the optional-only rewrite.
- Typing another character before `:` clears the pending state.

## Neovim

Implement Neovim-facing behavior in `sase-nvim`, with LSP support from `sase-core` only where needed.

1. Add a small `sase-nvim` spacer helper module, installed during `require("sase").setup(...)` or from the existing
   plugin load path, that owns:
   - Buffer-local pending spacer state.
   - An `InsertCharPre` handler for `:`.
   - Optional-only lookup from the xprompt catalog cache for fallback validation.
2. For legacy picker / `#@` insertion:
   - If the picker insertion path inserts an optional-only trailing spacer, set buffer-local pending spacer state with
     the exact row/column after insertion.
   - If the path currently inserts only raw `#name`, do not add unrelated skeleton parity in this change unless the
     implementation confirms that parity is expected.
3. For native LSP completion:
   - Prefer exact metadata if Neovim exposes it on completion-done events. Add lightweight `CompletionItem.data` in
     `sase-core` for optional-only xprompt spacer items if that makes the Neovim side exact.
   - If exact completion-done metadata is not available, use a conservative fallback: on `:` only, check whether the
     cursor is immediately after `#name ` / `#!name ` and `name` is known in the cached catalog as optional-only. If the
     catalog is cold, do nothing rather than guessing.
4. The Neovim handler should swallow the typed colon, replace the previous space with `:`, and leave the cursor after
   the colon. It should not alter ordinary spaces after unknown references or no-input xprompts.

Focused Neovim tests:

- Lua helper tests for optional-only detection, no-input detection, and reference-before-cursor detection.
- Headless Neovim test for `InsertCharPre`: `#optional |` plus typed `:` becomes `#optional:|`.
- Negative tests for no-input, unknown reference, and a non-colon next character.
- If `CompletionItem.data` is added in `sase-core`, Rust LSP unit tests assert the metadata appears only on
  optional-only spacer items.

## Validation

After implementation:

- In `sase`: run `just install` if needed, then targeted pytest for prompt completion/arg-hint tests, then `just check`.
- In `sase-core`: run the targeted xprompt LSP tests, then the repo's Rust check command if LSP code changed.
- In `sase-nvim`: run the existing headless Lua tests plus the new spacer test.

Manual smoke checks:

- ACE prompt input: accept an optional-only xprompt via `#@`, `Ctrl+T`, and soft completion; type `:` and confirm the
  prompt becomes `#name:`.
- Neovim prompt buffer: accept an optional-only xprompt through native completion and through the picker path that
  inserts a spacer; type `:` and confirm the spacer is replaced.
- Confirm `#plain ` followed by `:` is left alone when `plain` has no inputs.

## Risks

- Neovim native completion may not expose enough completion-done metadata to track only accepted LSP items. The fallback
  should stay conservative and catalog-backed rather than rewriting every `#name :` shape.
- ACE undo grouping should be checked manually. Replacing the spacer with `:` should be one normal typed edit, not a
  destructive multi-step operation.
- Optional-only xprompts do not currently show the same argument hint panel as required-input xprompts. This plan does
  not change that behavior; it only makes entering colon syntax less awkward.
