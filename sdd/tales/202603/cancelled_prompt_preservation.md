---
create_time: 2026-03-25 18:39:06
status: done
prompt: sdd/prompts/202603/cancelled_prompt_preservation.md
---

# Plan: Make Cancelled Prompt Preservation Bulletproof

## Problem

Multiple code paths unmount the prompt input bar **without saving its text to history**. The only path that currently
saves cancelled text is the explicit Esc/Ctrl+C cancel handler. All other dismissal paths silently discard whatever the
user typed.

## Identified Loss Scenarios

All of these currently lose the user's typed prompt text:

| #   | Scenario                   | Code path                                                                                  | Why text is lost                                                                                                          |
| --- | -------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Editor cancel**          | User types text → Ctrl+G → editor opens → user closes editor without saving                | `on_prompt_input_bar_editor_requested` unmounts bar without saving the original bar text                                  |
| 2   | **Workflow editor cancel** | User types text → Ctrl+Y → workflow editor returns None                                    | `on_prompt_input_bar_workflow_editor_requested` unmounts bar without saving                                               |
| 3   | **Bar re-mount**           | New prompt bar replaces existing one (e.g., user selects a different CL while bar is open) | `_show_prompt_input_bar` / `_show_prompt_input_bar_for_home` call `_unmount_prompt_bar()` directly                        |
| 4   | **History modal cancel**   | Trigger "." → history modal → cancel → bar unmounted                                       | `on_prompt_input_bar_history_requested` callback unmounts bar (text is just "." so low impact, but the pattern is unsafe) |
| 5   | **History→edit→cancel**    | Pick from history → edit first → close editor empty → bar unmounted                        | Editor cancel path unmounts bar (selected text IS in history already, but any edits in the editor are lost)               |

### What already works

- **Esc / Ctrl+C cancel**: `on_prompt_input_bar_cancelled` correctly saves text with `cancelled=True` ✓
- **Successful submit**: `_finish_agent_launch` saves prompt with `cancelled=False` before unmounting ✓

## Solution: Save text inside `_unmount_prompt_bar` itself

### Core insight

`_unmount_prompt_bar()` is the **single choke point** through which every dismissal path flows. If we save the bar's
text to history here, no code path can ever lose a prompt — regardless of how or why the bar was removed.

### Safety properties (why this is safe)

- `add_or_update_prompt(cancelled=True)` **never downgrades** existing non-cancelled entries (by design in the existing
  code). So if `_finish_agent_launch` already saved the prompt as non-cancelled, the redundant cancelled save in
  `_unmount_prompt_bar` just updates `last_used`.
- Empty text is skipped (no junk entries).
- Trigger patterns like `.` / `.x` are filtered out (not real prompts).

## Implementation

### Phase 1: Make `_unmount_prompt_bar` save text (core fix)

**File: `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`**

#### 1a. Add save-before-unmount logic to `_unmount_prompt_bar`

```python
def _unmount_prompt_bar(self) -> None:
    """Unmount the prompt input bar if present, saving any unsaved text."""
    from ...widgets import PromptInputBar

    try:
        bar = self.query_one("#prompt-input-bar", PromptInputBar)
    except Exception:
        return  # Bar not present

    # Save any non-trivial text as cancelled before removing the bar.
    # This is the safety net — every code path that dismisses the bar
    # flows through here, so no prompt text can ever be silently lost.
    self._save_bar_text_as_cancelled(bar)

    # Synchronously detach (existing logic)
    parent = bar._parent
    if parent is not None:
        parent._nodes._remove(bar)
    bar.remove()
```

#### 1b. Add `_save_bar_text_as_cancelled` helper

```python
_TRIVIAL_PROMPT_PATTERNS = frozenset({".", ".x"})

def _save_bar_text_as_cancelled(self, bar: object) -> None:
    """Extract text from bar and save to history as cancelled.

    Skips empty text and trivial trigger patterns (`.`, `.x`, VCS dot-prompts).
    Safe to call even if the prompt was already saved — add_or_update_prompt
    never downgrades a non-cancelled entry to cancelled.
    """
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

    try:
        text_area = bar.query_one("#prompt-input", PromptTextArea)
        text = text_area.text.strip()
    except Exception:
        return

    if not text:
        return

    # Skip trigger patterns that aren't real prompts
    if text in self._TRIVIAL_PROMPT_PATTERNS:
        return
    # Skip VCS dot-prompts like "#gh:sase ." or "#gh:sase .x"
    if text.endswith((" .", " .x")) and text.startswith("#"):
        return

    ctx = self._prompt_context
    if ctx:
        from sase.history.prompt import add_or_update_prompt
        add_or_update_prompt(
            text,
            project_name=ctx.project_name,
            branch_or_workspace=ctx.history_sort_key,
            cancelled=True,
        )
    else:
        # No context available (rare edge case) — save with auto-detection
        from sase.history.prompt import add_or_update_prompt
        add_or_update_prompt(text, cancelled=True)
```

#### 1c. Remove the now-redundant save in `on_prompt_input_bar_cancelled`

The cancel handler's explicit save is now handled by `_unmount_prompt_bar`. Simplify it to:

```python
def on_prompt_input_bar_cancelled(self, event: object) -> None:
    """Handle cancellation from the input bar."""
    from ...widgets import PromptInputBar

    if not isinstance(event, PromptInputBar.Cancelled):
        return

    self.notify("Prompt input cancelled")
    self._unmount_prompt_bar()  # ← saves text automatically now
    self._prompt_context = None
```

### Phase 2: Fix context ordering in re-mount paths

When a new prompt bar replaces an existing one, `_prompt_context` is currently overwritten **before**
`_unmount_prompt_bar()` is called. This means the old bar's text would be saved with the new context's project/branch.
Fix by calling unmount **before** setting the new context.

**File: `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`**

#### 2a. `_show_prompt_input_bar` — reorder unmount before context assignment

Current:

```python
self._prompt_context = PromptContext(...)  # ← new context
self._unmount_prompt_bar()                # ← old bar saved with WRONG context
self.mount(PromptInputBar(...))
```

Fixed:

```python
self._unmount_prompt_bar()                # ← old bar saved with OLD context ✓
self._prompt_context = PromptContext(...)
self.mount(PromptInputBar(...))
```

#### 2b. `_show_prompt_input_bar_for_home` — same reorder

Current:

```python
self._setup_home_prompt_context(...)
self._unmount_prompt_bar()
self.mount(PromptInputBar(...))
```

Fixed:

```python
self._unmount_prompt_bar()
self._setup_home_prompt_context(...)
self.mount(PromptInputBar(...))
```

### Phase 3: Handle editor cancel paths explicitly (belt + suspenders)

Even though `_unmount_prompt_bar` now covers these, we can also save the bar text at the point where the editor returns
empty, so the intent is clear in the code.

**File: `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`**

#### 3a. `on_prompt_input_bar_editor_requested` — save on editor cancel

The current code passes `event.current_text` to the editor. If the editor returns empty, that text is lost. Since
`_unmount_prompt_bar` will now save whatever's in the bar (which still has the original text since the editor opened in
a separate process), this is already covered. But we can add a comment noting this is handled by `_unmount_prompt_bar`
for clarity.

#### 3b. `on_prompt_input_bar_workflow_editor_requested` — same

Already covered by `_unmount_prompt_bar`. Add comment for clarity.

#### 3c. `_select_and_open_editor_for_home` — save on editor cancel

This path doesn't use the prompt bar (editor opens directly), but `initial_text` is passed. If the editor returns empty
and `initial_text` was non-empty, save it:

```python
if not prompt:
    if initial_text.strip():
        from sase.history.prompt import add_or_update_prompt
        add_or_update_prompt(initial_text.strip(), cancelled=True)
    self.notify("No prompt from editor - cancelled", severity="warning")
    self._prompt_context = None
```

## Testing

1. **Unit test**: `_save_bar_text_as_cancelled` correctly filters trivial patterns
2. **Unit test**: `_save_bar_text_as_cancelled` skips empty text
3. **Manual test**: Type text → Esc → verify in history with `.x`
4. **Manual test**: Type text → Ctrl+G → close editor → verify in history with `.x`
5. **Manual test**: Type text → Ctrl+Y → cancel workflow editor → verify in history with `.x`

## Files to modify

1. `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py` — all changes
