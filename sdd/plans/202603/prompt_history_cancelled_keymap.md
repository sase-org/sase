---
create_time: 2026-03-29 14:29:12
status: done
prompt: sdd/prompts/202603/prompt_history_cancelled_keymap.md
---

# Plan: Add `,>` keymap for prompt history with cancelled prompts visible

## Goal

Add a new `,>` leader mode keymap that behaves identically to `,.` (prompt history) except the `PromptHistoryModal`
opens with cancelled prompts shown by default (`show_cancelled=True`).

## Context

- `,.` opens `PromptHistoryModal` via `_start_prompt_history_from_last_selection()` with cancelled prompts hidden. Users
  can toggle them with Ctrl+X inside the modal, but there's no quick way to open the modal with cancelled prompts
  already visible.
- The `PromptHistoryModal` already accepts a `show_cancelled` constructor parameter — no modal changes needed.
- `>` maps to key name `"greater_than_sign"` in the existing key name registry.

## Changes

### 1. Config & types — register the new key

- **`src/sase/default_config.yml`** — Add `prompt_history_cancelled: "greater_than_sign"` under `leader_mode.keys`,
  right after `prompt_history`.
- **`src/sase/ace/tui/keymaps/types.py`** — Add `"prompt_history_cancelled": "greater_than_sign"` to
  `LeaderModeKeymaps.keys` default dict, keeping it next to `prompt_history`.

### 2. Entry point — parameterize `show_cancelled`

- **`src/sase/ace/tui/actions/agent_workflow/_entry_points.py`** — Add a `show_cancelled: bool = False` parameter to
  `_start_prompt_history_from_last_selection()` and forward it to
  `PromptHistoryModal(show_cancelled=show_cancelled, ...)`.

### 3. Leader mode handler — dispatch the new key

- **`src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`** — Add a handler block after the existing
  `prompt_history` block:
  ```python
  if key == leader_keys["prompt_history_cancelled"]:
      self._start_prompt_history_from_last_selection(show_cancelled=True)
      self._refresh_current_tab()
      return True
  ```

### 4. UI — help modal and footer

- **`src/sase/ace/tui/modals/help_modal/bindings.py`** — Add a new entry next to each of the 3 existing `prompt_history`
  entries showing `",>"` → `"Prompt history (+cancelled)"`.
- **`src/sase/ace/tui/widgets/keybinding_footer.py`** — Add `(k("prompt_history_cancelled"), "history (+cancelled)")`
  right after the `prompt_history` line.
