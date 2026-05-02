---
create_time: 2026-04-27 09:26:22
status: done
prompt: sdd/prompts/202604/copy_agent_name_key.md
---
# Plan: Copy Agent Name to Clipboard from Agents Tab Copy Mode

## Goal

In `sase ace`'s **Agents** tab, while in copy mode (entered with `%`), pressing a new key should copy the currently
selected agent's name to the system clipboard, with a toast notification confirming what was copied.

## Product Context

The Agents tab already supports copy mode via `%` followed by:

| key | action                              |
| --- | ----------------------------------- |
| `c` | copy chat file path                 |
| `p` | copy agent prompt                   |
| `s` | copy `sase ace` snapshot            |
| `E` | copy file path (when file panel up) |

The ChangeSpecs tab already binds `%n` → "copy CL name" (`_copy_cl_name`). Mirroring that key on the Agents tab is the
most discoverable choice — `%n` consistently means "name" across both tabs.

## Open Design Question — Which "Name"?

The `Agent` dataclass (`src/sase/ace/tui/models/agent.py:232`) exposes three name-like fields:

1. **`agent_name`** (line 333) — explicitly user-assigned via the `%name` xprompt directive or manual TUI naming. **May
   be `None`.** This is the canonical "agent name" — it's what `#agent_name:foo` directives reference.
2. **`display_name`** (line 472) — workflow name for top-level workflow rows; otherwise falls back to `cl_name`. This is
   **what the user sees in the list**.
3. **`cl_name`** — the underlying ChangeSpec name; always present.

**Recommendation:** copy **`agent_name` if set, else `display_name`** (which itself falls back to `cl_name`). Rationale:

- Users who explicitly named an agent want that name back — it's the one that wires up cross-agent references (`%wait`,
  `#agent_name:`, etc.).
- For unnamed agents (the common case), users naturally think of the row by what they see, which is `display_name`.
- The toast should distinguish: `Copied: Agent Name (foo)` vs. `Copied: Agent Display Name (bar)` so the user knows
  which they got.

If the user prefers a single-source rule (always `display_name`, or always `agent_name` with a warning if `None`), the
implementation collapses trivially — only the helper method body and notification text change.

## Implementation Outline

### 1. Keymap registration

- **`src/sase/ace/tui/keymaps/types.py`** — `CopyModeKeymaps.keys["agents"]` (lines 322–327): add `"name": "n"` so the
  typed default mirrors the YAML.
- **`src/sase/default_config.yml`** — under `ace.keymaps.modes.copy_mode.keys.agents` (lines 128–132): add `name: "n"`.

### 2. Copy action handler

- **`src/sase/ace/tui/actions/clipboard.py`**:
  - Add `_copy_agent_name(self) -> None` modeled on `_copy_chat_path` (lines 288–310) and `_copy_cl_name` (lines
    250–258). Use `self._get_selected_agent()`, handle the `None` case with a `"No agent selected"` warning, then
    resolve `agent.agent_name or agent.display_name` and call `copy_to_system_clipboard(...)`.
  - Wire it into `_handle_agents_copy_key` (lines 133–159): add an `elif key == ag_keys["name"]:` branch ahead of the
    unknown-key fallback. The fallback's `key_list` already enumerates `ag_keys.values()`, so it picks up the new entry
    automatically.

### 3. Footer (transient copy-mode display)

- **`src/sase/ace/tui/widgets/keybinding_footer.py`** — `update_copy_bindings` (lines 465–472): add
  `(k("name"), "name")` to the agents-tab bindings list. The footer's alphabetical ordering rules from
  `src/sase/ace/AGENTS.md` apply (already handled by `_format_bindings`).

### 4. Help modal

- **`src/sase/ace/tui/modals/help_modal/bindings.py`** (lines 384–391): add a new entry in the Agents-tab Copy Mode
  section — `(f"{d(cm.prefix)}{d(ag_copy['name'])}", "Copy agent name")`. Per `src/sase/ace/AGENTS.md`, keep the
  description ≤ 32 characters.

### 5. Tests

- **`tests/test_keymaps.py`** — update `test_copy_mode_nested_defaults` (lines 99–105) to expect the new `"name"` key
  under `agents`.
- New unit test alongside the existing clipboard tests (find with `grep -r _copy_chat_path tests/`) covering:
  - `agent_name` set → notification reads "Agent Name (...)"; clipboard receives that value.
  - `agent_name` None, `display_name` set → notification reads "Agent Display Name (...)"; clipboard receives
    `display_name`.
  - No agent selected → warning notification, no clipboard write.
  - `copy_to_system_clipboard` returning `False` → error notification. Mock `copy_to_system_clipboard` the way existing
    tests do (the function is module-level in `clipboard.py`, so patch it on that module).

### 6. Documentation surface

- The help modal change (step 4) is the user-facing doc. No README/CHANGELOG edits are warranted for a single-key
  addition.

## Files Touched (Summary)

| file                                                      | reason                              |
| --------------------------------------------------------- | ----------------------------------- |
| `src/sase/ace/tui/keymaps/types.py`                       | typed default for the new key       |
| `src/sase/default_config.yml`                             | YAML default for the new key        |
| `src/sase/ace/tui/actions/clipboard.py`                   | `_copy_agent_name` + dispatcher arm |
| `src/sase/ace/tui/widgets/keybinding_footer.py`           | footer entry for copy mode          |
| `src/sase/ace/tui/modals/help_modal/bindings.py`          | help-modal entry                    |
| `tests/test_keymaps.py`                                   | updated default-keys assertion      |
| `tests/ace/tui/...` (new file or existing clipboard test) | behavior tests for the new action   |

## Out of Scope

- Changing how `agent_name` is set (already handled by `%name` directive / TUI naming).
- Adding additional copy targets on the Agents tab beyond the requested name.
- Changing copy-mode UX on other tabs.
- Reworking the `display_name` fallback chain.

## Verification

- `just check` (lint + mypy + tests) per `memory/short/build_and_run.md`.
- Manual smoke test in `sase ace`: launch, switch to Agents tab (`2` or whatever the configured key), highlight a row,
  press `%n`, confirm a toast appears and the system clipboard contains the expected name. Repeat for an
  explicitly-named agent vs. a workflow row vs. a plain ChangeSpec row.
