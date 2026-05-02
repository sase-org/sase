---
create_time: 2026-04-04 15:55:40
status: done
prompt: sdd/prompts/202604/fix_jump_modal_number_keys.md
---

# Fix: Jump-to-entry modal numeric hints intercepted by saved query bindings

## Problem

When the `JumpAllModal` (backtick) is open and the user presses a number key (e.g., `8`), the saved search query binding
fires instead of (or in addition to) the jump hint action. The user sees "No query saved in slot 8" rather than jumping
to the entry.

## Root Cause Analysis

Traced through Textual 8.0.0's key event processing:

1. `App.on_event()` checks **priority bindings** first (using `_check_bindings(key, priority=True)` with the full
   `_binding_chain`). The saved query bindings are non-priority, so they don't match here.

2. The event is forwarded to the focused widget and **bubbles up** through the DOM: focused_widget -> containers ->
   `JumpAllModal` -> `App`.

3. `JumpAllModal.on_key()` fires during bubbling. It calls `event.prevent_default()` and `self.dismiss(None)`.

4. **Critical**: The modal does **NOT** call `event.stop()`! So the event continues bubbling to the `App`.

5. `App._on_key()` fires:

   ```python
   async def _on_key(self, event: events.Key) -> None:
       if not (await self._check_bindings(event.key)):
           await dispatch_key(self, event)
   ```

   This calls `_check_bindings(event.key)` (priority=False), which uses `self.screen._modal_binding_chain`. **It does
   not check `event.is_prevented`** -- it just receives the key string, not the event object.

6. If `dismiss()` has already changed `self.screen` from the modal back to the main screen, `_modal_binding_chain` finds
   no modal in the chain and returns the **full chain including app-level bindings**. The saved query binding for "8" is
   found and executed.

By contrast, the single-tab jump mode in `EventHandlersMixin.on_key()` correctly calls **both**
`event.prevent_default()` and `event.stop()`:

```python
if self._entry_jump_mode_active:
    if self._handle_entry_jump_key(event.key):
        event.prevent_default()
        event.stop()           # <- prevents bubbling to App
```

## Fix

In `JumpAllModal.on_key()`, add `event.stop()` alongside `event.prevent_default()` in all three branches (escape,
matched hint, unmatched key). This prevents the event from bubbling to the App, which prevents `App._on_key` from
running the binding check against the (now non-modal) screen's binding chain.

### File: `src/sase/ace/tui/modals/jump_all_modal.py`

In `on_key()`, add `event.stop()` after every `event.prevent_default()` call.

## Testing

Test with `sase ace --agent`:

```bash
# Open jump modal (backtick), then press a number key
sase ace --agent --keys grave_accent 8
```

Verify no "No query saved in slot N" notification appears and the modal properly handles the key.
