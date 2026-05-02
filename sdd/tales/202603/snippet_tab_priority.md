---
create_time: 2026-03-28 13:36:47
status: done
prompt: sdd/prompts/202603/snippet_tab_priority.md
---

# Fix: Snippet Expansion Takes Priority Over Tabstop Advance

## Problem

When `<tab>` is pressed in INSERT mode, the current priority is:

1. `_try_advance_tabstop()` — jump to next `$N` from a previously expanded snippet
2. `_try_expand_snippet()` — expand a trigger word to the left of the cursor

This means: expand snippet A (which has `$0`), type snippet trigger B, press tab → jumps to A's `$0` instead of
expanding B. The user's intent is clearly to expand B since they just typed it.

## Fix

Swap the two calls in `_on_key()` at line 489-496 of `prompt_text_area.py`:

```python
# Tab in INSERT mode: expand snippet or advance tabstop (never insert literal tab)
if event.key == "tab":
    event.stop()
    event.prevent_default()
    if self._try_expand_snippet():
        return
    self._try_advance_tabstop()
    return
```

`_try_expand_snippet()` already returns `False` when there's no trigger word before the cursor, so the tabstop fallback
still fires in that case.

## Test

Add a test in `test_prompt_snippet_expansion.py` that:

1. Expands a snippet with `$1` and `$0` tabstops
2. Types a second snippet trigger word at `$1`
3. Asserts that `_try_expand_snippet()` succeeds (returns `True`) — confirming expansion takes priority
4. Asserts that the old tabstops are replaced by the new snippet's tabstops

## Files

| File                                                     | Change                                                  |
| -------------------------------------------------------- | ------------------------------------------------------- |
| `src/sase/ace/tui/widgets/prompt_text_area.py`           | Swap priority: snippet expansion before tabstop advance |
| `tests/ace/tui/widgets/test_prompt_snippet_expansion.py` | Add priority test                                       |
