---
create_time: 2026-06-18 07:41:10
status: done
prompt: sdd/prompts/202606/prompt_search_escape_clear.md
---
# Prompt Search Escape Clear Plan

## Context

Prompt input Vim search is implemented in `PromptTextArea` through:

- `src/sase/ace/tui/widgets/_prompt_search.py` for active `/` and `?` command-line state, confirmed search state, and
  `n`/`N` repeat search.
- `src/sase/ace/tui/widgets/_search_highlight.py` for retained match spans and overlay refresh.
- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` and `src/sase/ace/tui/widgets/_vim_normal.py` for Escape
  dispatch and normal-mode command handling.

The current dispatch already keeps Escape from canceling the prompt: insert-mode Escape enters normal mode, and
normal-mode Escape clears pending Vim state. Active search command-line Escape is handled earlier by
`_handle_prompt_search_key`, where it cancels the in-progress search, restores the origin cursor, clears highlights, and
hides the search panel.

The search model keeps visible highlights separate from `_last_search`, so visible highlights can be cleared without
losing `n`/`N` repeat behavior.

## Goal

When the prompt text area is already in Vim normal mode, pressing Escape should disable any visible prompt search
highlights. This should behave like clearing the retained overlay from a confirmed `/` or `?` search or an `n`/`N`
repeat, not like canceling the prompt or deleting the last search record.

## Proposed Changes

1. Update the normal-mode Escape path in `_vim_normal.py`.
   - Keep the existing clearing of pending keys, counts, operators, surround state, and count display.
   - Also clear prompt search highlights via the existing prompt search/highlight cleanup API.
   - Preserve `_last_search` so `n`/`N` can recreate highlights and continue navigating after Escape.
   - Do not change active search command-line Escape behavior, because `_prompt_text_area_key_handling.py` routes that
     before normal-mode handling.

2. Keep the behavior prompt-local and pane-local.
   - Search state already lives on each `PromptTextArea`; clearing highlights through the active text area should not
     affect inactive prompt panes beyond the existing stack focus cleanup paths.

3. Avoid new expensive work.
   - The change should only clear in-memory search span state and use the existing overlay refresh path.
   - No disk I/O, subprocess work, or async task scheduling is needed in key handlers.

4. Add focused regression coverage.
   - Add a test in `tests/ace/tui/widgets/test_prompt_search_interactive.py` that confirms a search, verifies highlights
     exist, presses Escape while still in normal mode, and verifies highlights are cleared while `_last_search` remains.
   - Extend that test to press `n` afterward, proving repeat search still works and highlights can be rebuilt from
     `_last_search`.
   - Keep relying on existing active-search cancel coverage for Escape during `/...` entry.
   - Keep relying on existing prompt Escape tests to prove double Escape does not emit `PromptInputBar.Cancelled`;
     update or add a small assertion only if the normal-mode Escape change touches that behavior.

## Verification

Run targeted tests:

```bash
pytest tests/ace/tui/widgets/test_prompt_search_interactive.py \
  tests/ace/tui/widgets/test_prompt_escape_cancel.py \
  tests/ace/tui/widgets/test_prompt_search_highlight.py
```

If the targeted tests pass quickly, optionally run the broader prompt Vim subset:

```bash
pytest tests/test_prompt_normal_mode_*.py tests/ace/tui/widgets/test_prompt_search_interactive.py
```

## Risks

- Clearing highlights on every normal-mode Escape may also clear highlights while canceling a pending operator/count.
  That matches the requested "already in normal mode" Escape behavior and should be acceptable because the visible
  overlay is transient while `_last_search` remains available.
- If a test expects search highlights to persist through an unrelated Escape, it should be updated to the new product
  behavior rather than worked around.
