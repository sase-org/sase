---
create_time: 2026-05-07 00:42:51
status: done
prompt: sdd/prompts/202605/prompt_virtual_wrap.md
---
# Plan: Prompt Input Virtual Wrapping

## Goal

Stop using Prettier to reformat the prompt input widget while the user types. The prompt buffer should preserve exactly
what the user typed, while long logical lines wrap visually inside the input bar. The result should feel calmer and more
polished: no subprocess latency, no cursor jumps, no whitespace normalization, no inserted hard line breaks, and no
formatting flicker.

## Current Behavior

- `PromptTextArea` mixes in `TextFormattingMixin`, which schedules `_format_with_prettier()` after printable non-space
  input.
- `_format_with_prettier()` runs `prettier --parser markdown --prose-wrap always`, rewrites the full prompt, then maps
  the cursor back into the rewritten text.
- If Prettier is unavailable or fails, `_auto_wrap_line()` inserts hard newlines.
- `_edit_and_relaunch_agent()` also formats an existing raw prompt with Prettier before mounting `PromptInputBar`.
- `PromptInputBar` already tries to account for soft-wrapped visual lines, but it estimates wrapping manually instead of
  relying on Textual's actual wrapped document.

## Product Design

- Treat prompt input as an editor surface, not a formatter. The typed prompt is source text and should not be rewritten
  unless the user explicitly edits it.
- Use Textual's virtual wrapping (`soft_wrap=True`) as the single wrapping mechanism.
- Keep explicit user newlines meaningful: line numbers continue to appear only when the logical document has multiple
  lines, not merely because one long line wrapped.
- Keep the prompt bar visually stable and elegant:
  - the bar grows to fit visual wraps up to the available screen height;
  - wrapped text stays inside the existing bordered input surface;
  - completion popups continue to reserve height cleanly;
  - resize handling recomputes height from the same wrapping model Textual renders.

## Technical Plan

1. Replace the Prettier formatting mixin with a virtual-wrap-focused helper.
   - Remove async scheduler state, subprocess invocation, cursor remapping, and fallback hard-wrap insertion from the
     prompt widget path.
   - Keep any small helper only if it improves height/viewport behavior; otherwise delete the mixin entirely.
   - Rename files/tests away from "prettier" where they still describe prompt input behavior.

2. Make virtual wrapping explicit in `PromptInputBar`.
   - Pass `soft_wrap=True` when constructing `PromptTextArea` so the behavior is intentional instead of relying on a
     default.
   - Preserve `language="markdown"` for syntax highlighting.
   - Avoid changing submitted text; `_handle_text_submission()` should continue to trim only at submission boundaries.

3. Use Textual's real wrapped document for height.
   - Replace `PromptInputBar._get_visual_line_count()`'s manual width math with `text_area.wrapped_document.height` when
     available.
   - Recompute after text changes and resize, and keep the existing completion-panel height contribution.
   - Clamp height to screen height as it does today, but base the row count on rendered visual lines so long lines,
     gutters, scrollbars, and terminal width all agree with Textual.

4. Remove Prettier usage from relaunch prompt loading.
   - Delete `_format_prompt_with_prettier()`.
   - Mount the relaunch prompt using the raw prompt text. Long lines will wrap virtually in the input bar.
   - Update nearby docstrings/comments so they describe virtual wrapping, not formatting.

5. Tests.
   - Remove or rewrite scheduler/cursor-remap tests that only exist for Prettier mutation.
   - Add focused tests that:
     - typing beyond a narrow input width does not insert newlines;
     - pasted/initial long prompts remain byte-for-byte unchanged while the bar grows based on visual wrap height;
     - relaunch prompt mounting no longer calls Prettier and preserves raw text;
     - normal-mode edit operations still do not trigger background formatting.
   - Run a targeted pytest subset for prompt input, then `just install` followed by `just check` because this repo's
     memory requires it after non-bead file changes.

## Likely Files

- `src/sase/ace/tui/widgets/prompt_text_area.py`
- `src/sase/ace/tui/widgets/_text_formatting.py` or its replacement/removal
- `src/sase/ace/tui/widgets/prompt_input_bar.py`
- `src/sase/ace/tui/actions/agent_workflow/_entry_points.py`
- `tests/test_prompt_prettier_scheduler.py`
- `tests/test_prompt_format_cursor_restore.py`
- prompt/input focused tests under `tests/` and `tests/ace/tui/widgets/`

## Risks And Checks

- Textual wrapping internals may not update synchronously after every edit. If tests show stale height, schedule
  `_update_height()` with `call_after_refresh` or force a wrapped-document refresh through public widget APIs.
- `wrapped_document.height` is closer to rendered truth than manual width math, but it should be guarded so tests or
  older widget states fall back to logical line count.
- Long unbroken tokens will still hard-wrap visually. That is expected and preferable to mutating the prompt.
- The implementation should not remove other Prettier integrations elsewhere in the project, such as generated skill or
  markdown formatting workflows. This change is scoped to prompt input formatting while typing and relaunch loading.
