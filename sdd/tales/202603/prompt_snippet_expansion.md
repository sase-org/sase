---
create_time: 2026-03-22 20:22:57
status: done
prompt: sdd/prompts/202603/prompt_snippet_expansion.md
---

# Plan: Prompt Input Snippet Expansion

## Goal

Add inline snippet expansion to the prompt input widget: type a trigger word (e.g. `foobar`) and press `<Tab>` in INSERT
mode to expand it to a template string with cursor placed at the `$0` marker position.

## Research

See `sdd/research/202603/prompt_snippet_expansion.md` for the full design exploration.

## Files to Modify

| File                                                     | Change                                         |
| -------------------------------------------------------- | ---------------------------------------------- |
| `src/sase/default_config.yml`                            | Add `ace.snippets: {}` config key              |
| `src/sase/ace/tui/app.py`                                | Store `_snippets` dict from config on `AceApp` |
| `src/sase/ace/tui/widgets/prompt_text_area.py`           | Tab interception + expansion logic             |
| `tests/ace/tui/widgets/test_prompt_snippet_expansion.py` | Unit tests                                     |

## Implementation Steps

### Step 1: Add `snippets` config key to default config

**File**: `src/sase/default_config.yml`

Add `snippets: {}` under the `ace:` section (after `inactive_seconds`). This establishes the config schema. Users define
snippets in their `sase.yml`:

```yaml
ace:
  snippets:
    foobar: "A lot of foo with a $0 of bar."
    fixbug: "Fix the bug in $1 where $0"
```

### Step 2: Store snippets on AceApp

**File**: `src/sase/ace/tui/app.py`

In `__init__`, after loading `ace_cfg` (line ~288) and storing `_inactive_seconds` (line ~291), add:

```python
self._snippets: dict[str, str] = (
    ace_cfg.get("snippets", {}) if isinstance(ace_cfg, dict) else {}
)
```

This makes snippets accessible from widgets via `self._ace_app._snippets`.

### Step 3: Implement snippet expansion in PromptTextArea

**File**: `src/sase/ace/tui/widgets/prompt_text_area.py`

#### 3a: Add `_get_snippets()` method

```python
def _get_snippets(self) -> dict[str, str]:
    """Get the snippet registry from the app config."""
    return self._ace_app._snippets
```

#### 3b: Add `_try_expand_snippet()` method

This is the core expansion logic:

```python
def _try_expand_snippet(self) -> bool:
    """Try to expand a snippet trigger word at the cursor.

    Extracts the word immediately before the cursor, looks it up in the
    snippet registry, and replaces it with the expanded template. The
    cursor is positioned at the ``$0`` marker if present, otherwise at
    the end of the expanded text.

    Returns True if a snippet was expanded.
    """
    row, col = self.cursor_location
    line = self.document.get_line(row)

    # Extract word before cursor (alphanumeric + underscore)
    word_start = col
    while word_start > 0 and (line[word_start - 1].isalnum() or line[word_start - 1] == "_"):
        word_start -= 1

    if word_start == col:
        return False  # No word before cursor

    trigger = line[word_start:col]
    snippets = self._get_snippets()

    if trigger not in snippets:
        return False

    template = snippets[trigger]
    cursor_marker = "$0"
    cursor_offset = template.find(cursor_marker)
    expanded = template.replace(cursor_marker, "", 1)

    # Replace trigger word with expanded text
    start = (row, word_start)
    end = (row, col)
    self._replace_via_keyboard(expanded, start, end)

    # Position cursor at $0 location (if present)
    if cursor_offset >= 0:
        text_before_cursor = expanded[:cursor_offset]
        lines = text_before_cursor.split("\n")
        if len(lines) > 1:
            cursor_row = row + len(lines) - 1
            cursor_col = len(lines[-1])
        else:
            cursor_row = row
            cursor_col = word_start + len(lines[-1])
        self.cursor_location = (cursor_row, cursor_col)

    return True
```

Key design decisions:

- Word boundary: alphanumeric + underscore (matches identifier-like triggers)
- `$0` is removed from expanded text and cursor is placed there
- If no `$0`, cursor stays at end of expansion (default `_replace_via_keyboard` behavior)
- Multi-line expansions correctly calculate cursor row/col

#### 3c: Intercept Tab in `_on_key()`

In the INSERT mode section of `_on_key()`, add Tab handling before the `#@` detection block (around line 305):

```python
# Tab in INSERT mode: attempt snippet expansion
if event.key == "tab":
    if self._try_expand_snippet():
        event.stop()
        event.prevent_default()
        return
```

If no snippet matches, the event propagates normally (to app-level `next_tab`).

### Step 4: Unit tests

**File**: `tests/ace/tui/widgets/test_prompt_snippet_expansion.py`

Test the expansion logic by constructing a PromptTextArea, setting up text + cursor position, and calling
`_try_expand_snippet()` directly.

Test cases:

1. **Basic expansion**: trigger word expands, cursor at `$0`
2. **Cursor at end when no `$0`**: template without `$0` leaves cursor at end
3. **No match**: returns False, text unchanged
4. **No word before cursor**: returns False (cursor at start of line or after space)
5. **Trigger in middle of line**: text before and after trigger is preserved
6. **Multi-line expansion**: `$0` on second line computes correct row/col
7. **Underscore in trigger**: `my_snippet` is treated as one word

## Risk Assessment

| Risk                                   | Severity | Mitigation                                                  |
| -------------------------------------- | -------- | ----------------------------------------------------------- |
| Tab conflict with app-level `next_tab` | Medium   | Only consumed when snippet matches; falls through otherwise |
| Accidental expansion                   | Low      | Triggers are user-defined; no defaults ship                 |
| Multi-line cursor math                 | Low      | Thorough unit tests for the offset calculation              |

## Not in scope (future work)

- Tabstops (`$1`, `$2`) with Tab cycling
- Default values (`${1:default}`)
- Snippet completion popup
- File-based snippet definitions
