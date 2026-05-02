---
name: Reverse-cycle grouping keymap (`O`)
description: Add a shift+O keymap that cycles the Agents/CLs grouping strategy in
  reverse (mirror of existing `o`).
create_time: 2026-04-28 19:21:55
status: done
prompt: sdd/prompts/202604/reverse_grouping_keymap.md
---

# Reverse-cycle grouping keymap (`O`)

## Goal

Add an `O` (shift+o) keymap to the Agents and CLs tabs that mirrors the existing `o` keymap exactly, except it advances
the grouping/sorting cycle in the **reverse** direction. The `o` key is unchanged.

Concretely:

- **Agents tab cycle**: `STANDARD → BY_DATE → BY_STATUS → STANDARD` (forward, `o`). Reverse (`O`):
  `STANDARD → BY_STATUS → BY_DATE → STANDARD`.
- **CLs tab cycle**: `BY_PROJECT → BY_DATE → BY_STATUS → BY_PROJECT` (forward, `o`). Reverse (`O`):
  `BY_PROJECT → BY_STATUS → BY_DATE → BY_PROJECT`.
- AXE tab: silent no-op (same as forward `o`).

The reverse direction is the natural analog to the existing `toggle_thinking` (`]`) / `toggle_thinking_reverse` (`[`)
pair, which is the closest precedent in the codebase.

## Why

The user already cycles grouping modes frequently. Round-tripping forward through a 3-element cycle to step back one
position is mildly annoying. A capital-letter inverse follows the established `]`/`[` precedent and reuses the same
mental model.

## Scope of changes

### 1. `src/sase/default_config.yml`

Add a new key under `ace.keymaps.app`, next to the existing `cycle_grouping_mode`:

```yaml
# Grouping mode cycle (agents tab)
cycle_grouping_mode: "o"
cycle_grouping_mode_reverse: "O"
```

### 2. `src/sase/ace/tui/keymaps/types.py`

Two parallel additions, both required by the module-level consistency check at the bottom of the file:

- Add `("cycle_grouping_mode_reverse", "Cycle Grouping Rev", False)` to `_BINDING_META` (around line 110, immediately
  after the existing `cycle_grouping_mode` entry).
- Add `cycle_grouping_mode_reverse: str` field to `AppKeymaps` (around line 249, immediately after
  `cycle_grouping_mode`).

### 3. `src/sase/ace/tui/bindings.py`

`cycle_grouping_mode` does **not** appear in the `DEFAULT_BINDINGS` list (only `_BINDING_META` and the keymap registry
drive it). Therefore `cycle_grouping_mode_reverse` does **not** need a `Binding(...)` entry here either — keep the two
actions symmetric.

### 4. `src/sase/ace/tui/actions/agents/_grouping.py`

Refactor the existing forward-only helpers to take a `reverse: bool = False` keyword, and add a new public action
method.

- `_next_grouping_mode(self, *, reverse: bool = False)`: change the modulo step from `(idx + 1) % len(order)` to
  `(idx + (-1 if reverse else 1)) % len(order)`.
- `_next_changespec_grouping_mode(self, *, reverse: bool = False)`: same change.
- `_cycle_agents_grouping_mode(self, *, reverse: bool = False)`: pass `reverse` through to `_next_grouping_mode`.
- `_cycle_changespec_grouping_mode(self, *, reverse: bool = False)`: pass `reverse` through to
  `_next_changespec_grouping_mode`.
- Add new public action `action_cycle_grouping_mode_reverse(self) -> None` that mirrors `action_cycle_grouping_mode` but
  invokes the helpers with `reverse=True`. AXE remains a silent no-op.

This mirrors the `_cycle_panel_mode(*, reverse: bool = False)` pattern in `src/sase/ace/tui/actions/agents/_panels.py`
(the precedent established for `toggle_thinking_reverse`).

The toast text emitted on each step does **not** need to change — the user sees the _destination_ mode regardless of
direction, so `Grouping: by status` etc. is still correct.

The fold-registry-swap, banner-key reset, and `save_grouping_mode(...)` / `save_changespec_grouping_mode(...)`
persistence calls all run unchanged; the only thing that differs is which mode is "next."

### 5. `src/sase/ace/tui/modals/help_modal/bindings.py`

Two locations need updates so the help modal stays in sync (see `src/sase/ace/AGENTS.md` — "Help Popup Maintenance"):

- **CLs section** (~line 213): change the existing single entry `(d(a.cycle_grouping_mode), "Cycle: proj→date→status")`
  to a combined entry like
  `(f"{d(a.cycle_grouping_mode)} / {d(a.cycle_grouping_mode_reverse)}", "Cycle: proj→date→status (rev opp)")`. Mirrors
  the existing `Thinking` row format. Keep the description ≤ 32 chars per the AGENTS rule.
- **Agents section** (~line 443): same edit, with the agents-flavored description (`default → date → status`).

If width pressure forces a shorter description, prefer trimming the description over splitting into two rows — both help
modals already use the combined `forward / reverse` style for `Thinking`.

### 6. Info panels (`agent_info_panel.py`, `changespec_info_panel.py`)

These panels show a hint like `[group: by date (o)]`. Decision: leave them alone — they advertise the _primary_
(forward) keybinding, and adding a second key would clutter the status line. This matches the precedent for
`toggle_thinking`, where the thinking-panel header shows only `]`, not `]` / `[`.

### 7. Tests

Mirror the existing forward-cycle tests with reverse-direction equivalents. The two existing test files are the natural
homes:

- `tests/ace/tui/test_agent_grouping_cycle.py`: add
  - `test_reverse_cycle_advances_standard_to_by_status`
  - `test_reverse_cycle_advances_by_status_to_by_date`
  - `test_reverse_cycle_wraps_back_to_standard`
  - `test_three_reverse_cycles_returns_to_standard`
  - `test_forward_then_reverse_returns_to_standard` (round-trip / inverse property)
- `tests/ace/tui/test_changespec_grouping_cycle.py`: same five with CLs cycle order
  (`BY_PROJECT → BY_STATUS → BY_DATE → BY_PROJECT`).
- `tests/test_keymaps.py`: extend the existing assertion (line ~58) with
  `assert reg.app.cycle_grouping_mode_reverse == "O"` to lock in the default.

Per-mode fold-registry preservation already has coverage; no new fold tests are needed since the registry-swap path is
identical.

## Out of scope

- Renaming, deprecating, or moving the existing `o` binding.
- Any change to AXE-tab grouping (there is none).
- Changing the _displayed_ shortcut in info panels (decision §6).
- Plugin-level / chezmoi keymap config — the keymap is a default in `default_config.yml`; users override via their own
  YAML the same way they would for any other action.

## Risks & mitigations

- **Module-level consistency check** (`types.py` lines 401-409) will refuse to import if `_BINDING_META` and
  `AppKeymaps` are not updated together. This is a feature, not a risk — it guarantees we don't ship one without the
  other.
- **Help-modal width**: the `Cycle: proj→date→status` description is already 24 chars; adding `(rev opp)` would push it
  to 33 — over the 32-char ceiling. Pick a tighter description (e.g. just `Cycle grouping (fwd/rev)`) if needed. Verify
  by reading `help_modal.py`'s width constants before finalizing the string.
- **Discoverability**: most users won't notice `O` exists. Help modal disclosure (§5) is the main remediation; no other
  surfacing needed.

## Verification plan

1. `just install` then `just check` (lint + type + tests) in the ephemeral workspace — must pass.
2. Inspect: `default_config.yml` change, `types.py` consistency check passes at import (covered by any test run).
3. New unit tests cover both directions and wrap behavior on both tabs.
4. Manual TUI smoke test (if launched): verify on Agents and CLs that `o` advances forward and `O` advances backward,
   that triple-`O` returns to start, and that `o` then `O` returns to start. AXE: both keys silent no-op.
