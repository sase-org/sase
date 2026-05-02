---
create_time: 2026-04-14 12:54:02
status: wip
prompt: sdd/prompts/202604/fix_hint_input_bar_duplicate_ids.md
---

# Fix HintInputBar DuplicateIds TUI Crash

## Problem

The TUI crashes with `DuplicateIds: Tried to insert a widget with ID 'hint-input-bar'` when the user triggers a hint
mode (e.g., accept proposal) while a previous `HintInputBar` still exists in the DOM.

The root cause: Textual's `.remove()` is **async** — it schedules removal but doesn't free the widget ID immediately. If
a new `HintInputBar` is mounted before the async removal completes, Textual finds two widgets with the same ID and
raises `DuplicateIds`.

## The Correct Pattern Already Exists

`_prompt_bar.py::_unmount_prompt_bar()` solves this exact problem for `PromptInputBar`:

```python
parent = bar._parent
if parent is not None:
    parent._nodes._remove(bar)  # Synchronous ID release
bar.remove()
```

It also calls `_unmount_prompt_bar()` **before** every mount, not just on submit/cancel.

## Fix

**Update `_remove_hint_input_bar()` in `_processing.py`** to use the same synchronous removal pattern, then **call it
before every `HintInputBar` mount** across all 8 mounting sites.

### Phase 1: Fix `_remove_hint_input_bar()` — synchronous removal

In `_processing.py`, change the removal from:

```python
hint_bar = self.query_one("#hint-input-bar", HintInputBar)
hint_bar.remove()
```

to:

```python
hint_bar = self.query_one("#hint-input-bar", HintInputBar)
parent = hint_bar._parent
if parent is not None:
    parent._nodes._remove(hint_bar)
hint_bar.remove()
```

### Phase 2: Guard every mount site

Add `self._remove_hint_input_bar()` before the `.mount()` call in each of these 8 locations:

1. `proposal_rebase.py::action_accept_proposal()` — line 369
2. `hints/_files.py::action_view_files()` — line 57
3. `hints/_files.py::_view_agent_files()` — line 85
4. `hints/_hooks.py::action_edit_hooks()` — line 51
5. `hints/_hooks.py::action_hooks_from_failed()` — line 100
6. `hints/_mentors.py::action_kill_mentors()` — line 57
7. `hints/_rewind.py::action_start_rewind()` — line 54
8. `hints/_processing.py::_show_hook_history_modal()` callback — line 214

Each site already has the `is_attached` guard on the container. The new call goes right before that guard (or right
before mount), e.g.:

```python
self._remove_hint_input_bar()
detail_container = self.query_one("#detail-container")
if not detail_container.is_attached:
    return
hint_bar = HintInputBar(mode="...", id="hint-input-bar")
detail_container.mount(hint_bar)
```

## Files Changed

- `src/sase/ace/tui/actions/hints/_processing.py`
- `src/sase/ace/tui/actions/hints/_files.py`
- `src/sase/ace/tui/actions/hints/_hooks.py`
- `src/sase/ace/tui/actions/hints/_mentors.py`
- `src/sase/ace/tui/actions/hints/_rewind.py`
- `src/sase/ace/tui/actions/proposal_rebase.py`
