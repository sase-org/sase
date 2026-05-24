---
title: Replace CL History Keymaps With Jump-Stack Forward Navigation
create_time: 2026-05-24 10:27:27
status: done
prompt: sdd/prompts/202605/jump_stack_keymaps.md
---

# Plan: Replace CL History Keymaps With Jump-Stack Forward Navigation

## Goal

Remove the obsolete CLs-tab `<ctrl+r>` / `<ctrl+k>` ChangeSpec-history keymaps and reuse `<ctrl+k>` as the forward
counterpart to the existing `<ctrl+o>` jump-stack navigation.

The intended user model should match editor jumplist behavior:

- `<ctrl+o>` walks backward through jump points, or jumps to the first visible entry when no jump-back point exists.
- `<ctrl+k>` walks forward through jump points that were created by walking backward with `<ctrl+o>` / `''`.
- A new explicit jump branches the stack and clears forward history.

## Current Findings

- Defaults live in `src/sase/default_config.yml`; the keymap loader treats this file as the source of truth for every
  `AppKeymaps` field.
- The obsolete CL history keymaps are represented in all app-level keymap surfaces: `prev_changespec_history`,
  `next_changespec_history`, default fallback bindings, command palette metadata, and the CLs help modal.
- The newer jump-stack behavior is implemented in `src/sase/ace/tui/actions/navigation/_entry_jump.py`.
  `action_jump_to_entry_fast()` is bound to `<ctrl+o>` and internally behaves like `''`: pop a back stack when present,
  otherwise dispatch hint `1`.
- CLs/AXE currently store jump-back points as row indexes. Agents use richer anchors because banner focus and panel
  focus both matter.
- CLs grouped mode also has selectable collapsed banners, so the forward direction must preserve banner anchors instead
  of only preserving integer row indexes.

## Design

### 1. Replace the public keymap surface

- Remove `prev_changespec_history` and `next_changespec_history` from:
  - `src/sase/default_config.yml`
  - `AppKeymaps`
  - `_BINDING_META`
  - fallback `DEFAULT_BINDINGS`
  - command catalog metadata
  - CLs help modal navigation rows
- Add a new app action named `jump_to_entry_forward` with default key `<ctrl+k>`.
- Add `jump_to_entry_forward` to the same keymap surfaces as `jump_to_entry_fast`: default config, `AppKeymaps`,
  `_BINDING_META`, fallback bindings, command catalog, and help modal content.

### 2. Add forward jump-stack state

- Add a forward stack for non-Agents tabs.
- Add a forward anchor stack for the Agents tab.
- Keep the existing back-stack naming where possible to minimize churn, but broaden non-Agents entries from plain row
  indexes to anchors:
  - row anchor: `int`
  - CL banner anchor: `("changespec_banner", group_key)`
- Validate stale anchors before restoring:
  - row indexes must still be in range for their tab.
  - CL banner anchors must still appear in the current CL navigation stops.
  - Agent anchors should reuse the existing agent-anchor validation path.

### 3. Make `<ctrl+o>` and `''` populate forward history

- When restoring a back-stack anchor, snapshot the current jump anchor and push it onto the corresponding forward stack
  before moving.
- Preserve the current no-history behavior for `<ctrl+o>` / `''`: dispatch hint `1`.
- When dispatching a normal hint jump, push the origin to the back stack and clear the current tab's forward stack,
  because the user has branched from the previous jump path.

### 4. Implement `<ctrl+k>` as the opposite direction

- Add `action_jump_to_entry_forward()`.
- On non-Agents tabs, pop the latest valid forward anchor, push the current anchor onto the back stack, restore the
  forward anchor, and refresh the affected tab.
- On Agents, do the same with agent anchors, preserving panel focus and banner focus.
- If no valid forward anchor exists, leave selection unchanged and show a low-severity "No next jump point" message.
- Do not fall back to hint `1`; only `<ctrl+o>` keeps that first-entry shortcut.

### 5. Update documentation and command discovery

- CLs help should no longer mention the old ChangeSpec-history row.
- CLs, Agents, and AXE help should describe `<ctrl+o> / <ctrl+k>` as back / forward jump-stack traversal.
- Command palette metadata should expose the new action with aliases such as `jump`, `forward`, and `ctrl+k`.

### 6. Tests

- Update keymap tests for the removed history actions and the new `jump_to_entry_forward` default.
- Update binding-count expectations after removing two app actions and adding one.
- Update command catalog tests so `Ctrl+O` remains fast/back jump and `Ctrl+K` is jump-stack forward, not CL history.
- Add focused jump-stack tests:
  - CL row jump, `<ctrl+o>` back, `<ctrl+k>` forward.
  - New hint jump clears forward history.
  - Stale forward anchors are discarded.
  - CL collapsed-banner forward restoration works.
  - Agents forward restoration preserves agent/banner anchors and focused panel.

## Validation

Run:

```bash
just install
pytest tests/test_keymaps.py tests/test_command_catalog.py tests/ace/tui/test_jump_to_entry_hints.py tests/ace/tui/test_jump_hints_for_folded_banners.py
just check
```

`just check` is required for this repo after code changes.
