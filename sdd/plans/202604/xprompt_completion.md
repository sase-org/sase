---
create_time: 2026-04-14 17:44:33
status: done
prompt: sdd/prompts/202604/xprompt_completion.md
---

# Plan: xprompt Completion via ctrl+t

## Context

The prompt input widget's `ctrl+t` keybinding currently triggers file path completion when the cursor is on a path-like
token (e.g. `./`, `~/`, contains `/`). The user wants this same keybinding to also trigger xprompt name completion when
the cursor is on a token that starts with `#` (the xprompt reference prefix).

## Key Design Insight

`#` is **not** in `_TOKEN_DELIMITERS` (`file_completion.py:22`), so `extract_token_around_cursor()` already includes `#`
in the extracted token. For input `#fo|` (cursor at `|`), the token is `#fo`. This means we can detect xprompt context
by checking `token.startswith("#")` — no changes to token extraction needed.

## Architecture

Extend the existing completion infrastructure rather than creating a parallel system. The `CompletionCandidate`
dataclass, navigation, acceptance, and dropdown UI are all reusable. The key additions are:

1. A new xprompt candidate builder (mirrors `build_completion_candidates`)
2. A `_completion_kind` state flag so the mixin knows which builder to call during refresh
3. Kind-aware display rendering in the dropdown panel

## Plan

### Phase 1: xprompt candidate builder

Create `src/sase/ace/tui/widgets/xprompt_completion.py` with:

```python
def is_xprompt_like_token(token: str) -> bool
```

Returns `True` when token starts with `#` and contains no whitespace.

```python
def build_xprompt_completion_candidates(token: str) -> tuple[list[CompletionCandidate], str]
```

- Strips leading `#` to get the partial name
- Calls `get_all_prompts()` to get both xprompts and workflows
- Filters names by case-insensitive prefix match on the partial
- Sorts alphabetically
- Returns `CompletionCandidate` objects where:
  - `display` = name (without `#`)
  - `insertion` = `#name` (full reference)
  - `is_dir` = `False`
  - `name` = the xprompt name
- Computes `shared_extension` (common prefix beyond partial) just like file completion does

### Phase 2: Completion kind tracking

In `_file_completion.py` mixin, add `_completion_kind: str` state (values: `"file"` or `"xprompt"`). Initialize to
`"file"` in `PromptTextArea.__init__`. Reset in `_clear_file_completion()`.

Add `_get_xprompt_token_context()` method parallel to `_get_path_token_context()` — extracts token, checks
`is_xprompt_like_token()`, returns `(row, start, end, token)`.

### Phase 3: Dispatch in `_try_file_completion_tab()`

Modify `_try_file_completion_tab()` to try xprompt context first, then fall back to file context:

1. Extract token via `_extract_token_around_cursor()`
2. If token starts with `#`: set `_completion_kind = "xprompt"`, call `build_xprompt_completion_candidates(token)`
3. Else if path-like: set `_completion_kind = "file"`, call `build_completion_candidates(token)` (existing behavior)
4. Else: clear and return

The rest of the method (single candidate auto-insert, shared extension, activate dropdown) stays the same.

### Phase 4: Kind-aware refresh and accept

- `_refresh_file_completion_from_cursor()`: check `_completion_kind` to call the right token context getter and
  candidate builder
- `_accept_file_completion()`: skip directory drill-down when `_completion_kind == "xprompt"` (just clear completion
  after acceptance)

### Phase 5: xprompt-specific display styling

Update `show_file_completions()` in `prompt_input_bar.py` to accept an optional `completion_kind` parameter. When
`kind == "xprompt"`:

- Use `#` icon/prefix instead of 📁/📄
- Use a different border title (e.g. "xprompts" instead of the directory path)
- Style entries in magenta/green instead of cyan (to visually distinguish from file completion)

Pass `_completion_kind` through from `_update_file_completion_panel()`.

## Files Changed

| File                                             | Change                                                                                                                         |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `src/sase/ace/tui/widgets/xprompt_completion.py` | **New** — `is_xprompt_like_token()` and `build_xprompt_completion_candidates()`                                                |
| `src/sase/ace/tui/widgets/_file_completion.py`   | Add `_completion_kind` state, `_get_xprompt_token_context()`, modify `_try_file_completion_tab()` / `_refresh_*` / `_accept_*` |
| `src/sase/ace/tui/widgets/prompt_text_area.py`   | Initialize `_completion_kind` in `__init__`                                                                                    |
| `src/sase/ace/tui/widgets/prompt_input_bar.py`   | Update `show_file_completions()` to render xprompt entries differently                                                         |
| `src/sase/ace/tui/widgets/file_completion.py`    | No changes (token extraction and `CompletionCandidate` reused as-is)                                                           |
