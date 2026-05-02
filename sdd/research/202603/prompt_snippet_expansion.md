# Prompt Input Snippet Expansion - Research

## Goal

Add snippet expansion to the prompt input widget: type a trigger word (e.g. `foobar`), press `<Tab>`, and have it expand
to a template string with the cursor placed at a designated position.

Example: `foobar<Tab>` → `A lot of foo with a <cursor> of bar.`

## Current Architecture

### Prompt Input Widget Stack

- **PromptInputBar** (`src/sase/ace/tui/widgets/prompt_input_bar.py`) - Container widget, handles message dispatch
  (Submitted, Cancelled, SnippetRequested, etc.)
- **PromptTextArea** (`src/sase/ace/tui/widgets/prompt_text_area.py`) - Subclass of Textual's `TextArea`, mixes in
  `VimNormalModeMixin` and `LineRenderingMixin`

### How Key Events Flow (INSERT Mode)

1. `_on_key()` intercepts keys before TextArea's default handler
2. Special keys handled: `enter` (submit), `escape` (→ NORMAL), `@` after `#` (snippet modal)
3. Everything else falls through to `super()._on_key(event)` which inserts the character
4. After insertion, `_format_with_prettier()` runs for auto-wrapping

### Tab Key - Current State

Tab is **not intercepted** in `PromptTextArea._on_key()`. At the **app level**, it is bound to `next_tab` (switch
between CL/Agent/AXE tabs). This means:

- In INSERT mode, Tab currently does nothing useful in the prompt (it might insert a tab character or get eaten by the
  app-level binding depending on focus)
- `shift+tab` is bound to `prev_tab` at the app level

### Text Manipulation API

The key method is `_replace_via_keyboard(text, start, end)` (inherited from Textual's TextArea):

- Deletes text between `start` and `end` positions (both are `(row, col)` tuples)
- Inserts `text` at `start`
- Cursor automatically moves to end of inserted text

Cursor can be manually repositioned via `self.cursor_location = (row, col)`.

### Existing Expansion Systems

**`#@` snippet trigger** (xprompt insertion):

- User types `#@` → detected in `_on_key()` → posts `SnippetRequested` message → opens `XPromptSelectModal`
- After selection, `insert_snippet(name)` on `PromptInputBar` inserts the xprompt name at cursor
- This inserts a _reference_ (`#name`) that gets expanded later at submission time

**XPrompt expansion** (at submission):

- `#name` references are expanded by `process_xprompt_references()` in `src/sase/xprompt/processor.py`
- This is batch processing, not inline - happens in the preprocessing pipeline

**XPrompt aliases** (`xprompt_aliases` in sase.yml):

- Simple text substitution: `#alias` → `#real_name`
- Applied before the main expansion loop

## Design Considerations

### 1. Trigger Mechanism

**Option A: `<word><Tab>` in INSERT mode**

- Detect Tab in `_on_key()`, extract the word before the cursor, look it up in snippet registry
- If no match, fall through to default behavior (or do nothing)
- Pro: Familiar (like shell completion, IDE snippets)
- Con: Tab is currently used for app-level tab switching; needs careful focus/mode handling. Also, only works on exact
  word match — no fuzzy/prefix completion

**Option B: Dedicated key combo (e.g. `Ctrl+Space`)**

- Avoids Tab conflict entirely
- Less discoverable but unambiguous

**Option C: Suffix trigger (e.g. `foobar;` or `foobar!`)**

- No key conflict, detected inline during character insertion
- Could collide with normal typing

**Recommendation**: Option A (`<Tab>`) makes the most sense. The Tab key conflict can be resolved by intercepting Tab in
`PromptTextArea._on_key()` _before_ it bubbles up to the app. When the prompt has focus and is in INSERT mode, Tab
should attempt snippet expansion first; if no snippet matches the word before cursor, let it fall through. The app-level
`next_tab` binding would only fire when the prompt doesn't have focus (or in NORMAL mode).

### 2. Snippet Definition Storage

**Option A: `ace.snippets` section in sase.yml / default_config.yml**

```yaml
ace:
  snippets:
    foobar: "A lot of foo with a $0 of bar."
    fixbug: "Fix the bug in $1 where $0"
    review: "Please review the changes in $1.\n\nFocus on $0"
```

- Pro: Simple, familiar YAML config. Follows existing config patterns.
- Con: Multi-line templates are awkward in YAML

**Option B: Dedicated snippet files (e.g. `.snippets/` directory or `snippets/` alongside `xprompts/`)**

- Markdown or YAML files with frontmatter
- Pro: Better for complex, multi-line snippets
- Con: More filesystem overhead for what might be simple one-liners

**Option C: Extend xprompt system with a `snippet_trigger` field**

```yaml
---
name: foobar
snippet_trigger: foobar
---
A lot of foo with a $0 of bar.
```

- Pro: Reuses existing xprompt infrastructure (loading, namespacing, plugins)
- Con: Conflates two different concepts (prompt expansion vs inline snippet expansion)

**Recommendation**: Option A for simplicity. Snippets are short text expansions — keeping them in sase.yml config is the
most pragmatic starting point. Can always add file-based snippets later.

### 3. Cursor Placeholder Syntax

Standard snippet placeholder conventions:

- `$0` — final cursor position after expansion
- `$1`, `$2`, ... — tabstop positions (for multi-field snippets, future enhancement)
- `${1:default}` — tabstop with default text (future enhancement)

For a minimal first version, supporting just `$0` (cursor position) is sufficient.

### 4. Expansion Algorithm

When Tab is pressed in INSERT mode:

1. Get cursor position `(row, col)`
2. Get text of current line up to cursor
3. Extract the word immediately before cursor (scan backwards for word boundary)
4. Look up word in snippet registry
5. If found:
   - Calculate the replacement range: `(row, col - len(trigger_word))` to `(row, col)`
   - Find `$0` position in template, remove the `$0` marker
   - Call `_replace_via_keyboard(expanded_text, start, end)`
   - Reposition cursor to where `$0` was in the expanded text
   - `event.stop()` + `event.prevent_default()`
6. If not found:
   - Let the event propagate normally

### 5. Multi-line Snippet Handling

Snippets may contain newlines. The cursor positioning logic needs to handle this:

- If `$0` is on line N of the template, the final cursor row = `start_row + N`
- The column depends on whether `$0` is on the first line (adjust for trigger word removal) or a subsequent line

The `_replace_via_keyboard` method handles multi-line insertion correctly. The main complexity is computing the final
`(row, col)` for the `$0` position after the text has been inserted.

## Implementation Plan

### Phase 1: Minimal viable snippet expansion

**Files to modify:**

1. **`src/sase/default_config.yml`** — Add `ace.snippets: {}` section
2. **`src/sase/ace/tui/widgets/prompt_text_area.py`** — Intercept Tab in `_on_key()`, implement expansion logic
3. **`src/sase/ace/tui/widgets/prompt_input_bar.py`** — Load snippets from config, expose to PromptTextArea
4. **Config loading** — Ensure `ace.snippets` is loaded and accessible from the TUI app

**Key changes to `prompt_text_area.py`:**

```python
async def _on_key(self, event: Key) -> None:
    # ... existing enter/normal/escape handling ...

    # Tab in INSERT mode: attempt snippet expansion
    if event.key == "tab" and self._vim_mode == "insert":
        if self._try_expand_snippet():
            event.stop()
            event.prevent_default()
            return

    # ... existing #@ detection ...
```

**New method on PromptTextArea:**

```python
def _try_expand_snippet(self) -> bool:
    """Try to expand a snippet trigger word at the cursor. Returns True if expanded."""
    row, col = self.cursor_location
    line = self.document.get_line(row)

    # Extract word before cursor
    word_start = col
    while word_start > 0 and line[word_start - 1].isalnum() or line[word_start - 1] == '_':
        word_start -= 1

    if word_start == col:
        return False  # No word before cursor

    trigger = line[word_start:col]
    snippets = self._get_snippets()  # Access snippet registry

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

    # Position cursor at $0 location
    if cursor_offset >= 0:
        # Calculate row/col from character offset in expanded text
        text_before_cursor = expanded[:cursor_offset]
        lines = text_before_cursor.split("\n")
        cursor_row = row + len(lines) - 1
        cursor_col = len(lines[-1]) if len(lines) > 1 else word_start + len(lines[-1])
        self.cursor_location = (cursor_row, cursor_col)

    return True
```

### Phase 2: Enhancements (future)

- **Tabstops** (`$1`, `$2`, ...) — Tab cycles through placeholders
- **Default values** (`${1:default}`) — Pre-filled tabstop text that gets selected
- **Snippet completion popup** — Show matching snippets as you type (like autocomplete)
- **File-based snippets** — Load from `.snippets/` directories alongside xprompts
- **Dynamic snippets** — Templates with shell command substitution or Jinja2

## Risk Assessment

| Risk                                            | Severity | Mitigation                                                                                |
| ----------------------------------------------- | -------- | ----------------------------------------------------------------------------------------- |
| Tab key conflict with app-level `next_tab`      | Medium   | Intercept in widget `_on_key()` before bubbling; only consume when a snippet matches      |
| Accidental expansion of normal words            | Low      | Snippet triggers are user-defined; unlikely to collide with normal prose                  |
| Multi-line expansion breaks prettier formatting | Low      | Run `_format_with_prettier()` after expansion (already runs after every character insert) |
| Config schema changes                           | Low      | `ace.snippets` is a new, additive key — no backwards compatibility concern                |

## Key Files Reference

| File                                           | Role                                                                     |
| ---------------------------------------------- | ------------------------------------------------------------------------ |
| `src/sase/ace/tui/widgets/prompt_text_area.py` | Primary change: Tab interception + expansion logic                       |
| `src/sase/ace/tui/widgets/prompt_input_bar.py` | Snippet registry access, `insert_snippet()` pattern                      |
| `src/sase/default_config.yml`                  | Add `ace.snippets` config section                                        |
| `src/sase/ace/tui/keymaps/types.py`            | Reference for how keymaps are structured (no changes needed for phase 1) |
| `src/sase/xprompt/processor.py`                | Reference for expansion patterns (iterative, protection, tracing)        |
| `src/sase/ace/tui/widgets/_vim_normal_ops.py`  | Reference for `_replace_via_keyboard` usage patterns                     |
