---
status: done
bead_id: sase-gjad
prompt: sdd/prompts/202603/custom_keymaps.md
---

# Plan: Configurable Keymaps for sase ace TUI

## Context

All keymaps in the `sase ace` TUI are currently hardcoded across multiple files (67 app-level bindings + ~25 mode
sub-keys). Users cannot customize them. This plan makes ALL keymaps configurable via `ace.keymaps` in the deep-merge
config system (`default_config.yml` → plugins → `sase.yml` → overlays).

Key requirements:

- The `x` and `.` characters in tab titles like `Agents (3x2.5)` correspond to the `kill_agent` and
  `toggle_hide_reverted` keymaps respectively, and must update when those keymaps are reconfigured.
- Groups like leader, copy mode, fold mode, and bang should be configurable. The user should not only be able to
  configure the prefix key that triggers the mode but should also be able to add new custom modes.

## Config Structure

```yaml
ace:
  keymaps:
    app: # Textual BINDINGS (action_name → key) — 67 total
      # Navigation
      next_changespec: "j"
      prev_changespec: "k"
      scroll_to_top: "g"
      scroll_to_bottom: "G"
      scroll_detail_down: "ctrl+d"
      scroll_detail_up: "ctrl+u"
      scroll_prompt_down: "ctrl+f"
      scroll_prompt_up: "ctrl+b"
      prev_changespec_history: "ctrl+o"
      next_changespec_history: "ctrl+k"
      next_agent_file: "ctrl+n"
      prev_agent_file: "ctrl+p"
      # Tab switching
      next_tab: "tab" # priority=True
      prev_tab: "shift+tab" # priority=True
      # CL actions
      quit: "q"
      change_status: "s"
      run_workflow: "r"
      mail: "M"
      show_diff: "d"
      reword: "w"
      add_tag: "W"
      view_files: "v"
      edit_spec: "e"
      rename_cl: "n"
      # Proposals & sync
      accept_proposal: "a"
      rebase: "b"
      start_rewind: "R"
      sync: "Y"
      # Fold / collapse
      hooks_or_collapse: "h"
      hooks_or_collapse_all: "H"
      expand_or_layout: "l"
      expand_all_folds: "L"
      toggle_layout: "p"
      # Marking
      toggle_mark: "m"
      clear_marks: "u"
      bulk_change_status: "S"
      mark_inactive: "i"
      # Agent / axe
      kill_agent: "x"
      toggle_axe: "X"
      stop_axe_and_quit: "Q"
      start_custom_agent: "at"
      start_agent_from_changespec: "space"
      jump_to_agent_changespec: "enter"
      edit_panel: "E"
      # Thinking panel
      toggle_thinking: "right_square_bracket"
      toggle_thinking_reverse: "left_square_bracket"
      # File trim
      reset_file_trim: "minus"
      show_all_file_lines: "equals_sign"
      # Queries
      edit_query: "slash"
      prev_query: "circumflex_accent"
      next_query: "underscore"
      # Display / misc
      toggle_hide_reverted: "full_stop"
      show_notifications: "N"
      show_help: "question_mark"
      browse_xprompts: "number_sign"
      refresh: "y"
      # Workspace mode prefixes (sub-keys are positional digits, not configurable)
      checkout: "C"
      start_checkout_mode: "c"
      open_tmux: "T"
      start_tmux_mode: "t"
      # Tree navigation prefixes (sub-keys depend on tree structure, not configurable)
      start_ancestor_mode: "less_than_sign"
      start_child_mode: "greater_than_sign"
      start_sibling_mode: "tilde"
      # Mode activation prefixes (must stay in sync with modes.*.prefix below)
      start_fold_mode: "z"
      start_leader_mode: "comma"
      start_bang_mode: "exclamation_mark"
      copy_tab_content: "percent_sign"
    modes: # Prefix-key modes — built-in modes can be reconfigured, new ones can be added
      fold_mode:
        prefix: "z" # The key that activates this mode
        keys: # Sub-keys within the mode
          cycle_commits: "c"
          cycle_hooks: "h"
          cycle_mentors: "m"
          cycle_all: "z"
      copy_mode:
        prefix: "percent_sign"
        keys: # Per-tab sub-keys
          changespecs:
            raw: "percent_sign"
            with_snapshot: "exclamation_mark"
            bug: "b"
            cl_number: "c"
            name: "n"
            spec: "p"
            snapshot: "s"
          agents:
            chat: "c"
            file_path: "E"
            snapshot: "s"
          axe:
            visible: "o"
            full: "O"
            snapshot: "s"
      leader_mode:
        prefix: "comma"
        keys:
          run_cmd: "exclamation_mark"
          runners: "r"
          kill_mentors: "m"
          agent_home: "h"
          agent_from_cl: "space"
      bang_mode:
        prefix: "exclamation_mark"
        keys:
          run_cmd: "exclamation_mark"
          toggle_axe: "x"
      # Users can add custom modes:
      # my_mode:
      #   prefix: "semicolon"
      #   keys:
      #     do_thing: "t"
      #     do_other: "o"
```

Users override individual keys or add custom modes via deep-merge:

```yaml
# ~/.config/sase/sase.yml
ace:
  keymaps:
    app:
      next_changespec: "n" # remap j→n, everything else stays default
    modes:
      leader_mode:
        prefix: "space" # change leader prefix from comma to space
      my_custom_mode: # define an entirely new mode
        prefix: "semicolon"
        keys:
          open_dashboard: "d"
          run_sync: "s"
```

**Excluded from config** (inherently non-configurable):

- Saved query digit keys (0-9) — positional by definition
- Checkout/tmux workspace digits (1-9) — positional by definition (prefix keys `c`/`t`/`C`/`T` ARE configurable via
  `app`)
- Ancestry mode sub-keys (`<`, `>`, `~` sub-keys) — dynamically assigned from tree structure (prefix keys ARE
  configurable via `app`)
- Modal chrome keys (escape/enter in modals, q/escape/? to close help modal) — standard UI, not "keymaps"
- Widget input bindings (ctrl+f, ctrl+b, ctrl+g, ctrl+y, ctrl+u, ctrl+e inside `_PromptInput` / `_HintInput`) — editor
  keybindings within focused input widgets, not app-level keymaps

**Dual-registered keys** (must stay in sync):

- Each mode's `prefix` key appears in both `app` (for Textual binding dispatch) and `modes.<name>.prefix` (for
  mode-handler lookups). `load_keymap_registry` enforces sync — changing `modes.fold_mode.prefix` automatically updates
  the corresponding `app.start_fold_mode` binding and vice versa.
- Help modal passthrough bindings (saved query digits 0-9, `prev_query`, `next_query`) duplicate the app-level bindings
  with identical keys so they work when the modal is focused. Phase 3 must update these to read from the registry.

---

## Phase 1: Foundation — Keymap Registry + Default Config

**Goal**: Create the data model, config loader, and store registry on AceApp. No behavioral changes yet — registry is
populated but not consumed.

### New file: `src/sase/ace/tui/keymaps.py`

1. **Dataclasses** (one per section):
   - `AppKeymaps` — one field per app-level action, default = current hardcoded key
   - `ModeKeymaps` — generic container for any prefix-key mode, holding `prefix: str` and `keys: dict[str, str | dict]`
   - `FoldModeKeymaps`, `CopyModeKeymaps`, `LeaderModeKeymaps`, `BangModeKeymaps` — typed subclasses of `ModeKeymaps`
     with known fields for built-in modes (for type-safe access in built-in handlers)
   - `KeymapRegistry` — top-level container holding `app: AppKeymaps` and `modes: dict[str, ModeKeymaps]`

2. **`load_keymap_registry(ace_cfg: dict) -> KeymapRegistry`** — reads `ace_cfg["keymaps"]`, instantiates `AppKeymaps`
   and iterates over `ace_cfg["keymaps"]["modes"]` to build the modes dict. Known built-in modes are instantiated as
   their typed subclasses; unknown mode names produce generic `ModeKeymaps` instances. Each mode's `prefix` key is
   registered as an app-level binding that activates the mode.

3. **`build_app_bindings(app_km: AppKeymaps) -> list[Binding]`** — generates the Textual Binding list from the dataclass
   fields (same action names/descriptions as current, keys from config).

4. **`key_display_name(textual_key: str) -> str`** — converts Textual key names to human-readable display strings
   (`"full_stop"` → `"."`, `"exclamation_mark"` → `"!"`, `"right_square_bracket"` → `"]"`, `"ctrl+d"` → `"Ctrl+D"`,
   single chars pass through).

### Modify: `src/sase/default_config.yml`

Add `ace.keymaps` section with all defaults matching current hardcoded values (copy the complete structure from the
Config Structure section above).

### Modify: `src/sase/ace/tui/app.py`

In `AceApp.__init__`, after loading `ace_cfg`:

```python
from .keymaps import load_keymap_registry
self._keymap_registry = load_keymap_registry(ace_cfg)
```

No other behavioral changes in this phase.

### New file: `tests/test_keymaps.py`

- Test loading with empty config returns all defaults
- Test loading with partial overrides merges correctly
- Test `build_app_bindings` produces correct Binding count and keys
- Test `key_display_name` for all special key name mappings

### Verification

```bash
just test -k test_keymaps
just lint
```

---

## Phase 2: Wire App Bindings + Mode Handlers

**Goal**: Replace all hardcoded key lookups with registry reads. After this phase, remapping a key in config actually
changes TUI behavior.

### Modify: `src/sase/ace/tui/app.py`

Replace the hardcoded `BINDINGS = [...]` class variable:

1. Keep `BINDINGS` with hardcoded defaults at class level (Textual needs it at class definition time).
2. In `__init__`, after loading the registry, rebuild `self._bindings` from
   `build_app_bindings(self._keymap_registry.app)` to pick up any user overrides. Use Textual's `_Bindings` /
   `BindingsMap` API to replace the instance-level binding map.
3. `build_app_bindings` must preserve `priority=True` for `next_tab` / `prev_tab`.

### Modify mode handlers (replace hardcoded key comparisons with registry lookups):

Add `_keymap_registry: KeymapRegistry` type hint to each mixin.

1. **`src/sase/ace/tui/actions/navigation/_advanced.py`** (`_handle_fold_key`):
   - `key == "c"` → `key == self._keymap_registry.modes["fold_mode"].keys["cycle_commits"]`
   - Same for `"h"`, `"m"`, `"z"`

2. **`src/sase/ace/tui/actions/clipboard.py`** (`_handle_copy_key` and sub-functions):
   - All `key == "percent_sign"` etc. → `self._keymap_registry.modes["copy_mode"].keys["changespecs"]["raw"]`
   - Same for agents and axe sub-handlers

3. **`src/sase/ace/tui/actions/agent_workflow/_entry_points.py`** (`_handle_leader_key`):
   - All key checks → `self._keymap_registry.modes["leader_mode"].keys[...]`

4. **`src/sase/ace/tui/actions/axe.py`** (`_handle_bang_key`):
   - All key checks → `self._keymap_registry.modes["bang_mode"].keys[...]`

### Modify: `src/sase/ace/tui/modals/base.py` (`CopyModeForwardingMixin`)

The `CopyModeForwardingMixin` hardcodes `percent_sign` in both its `BINDINGS` and `on_key()` check. Update it to read
the copy mode prefix from the registry (`self.app._keymap_registry.modes["copy_mode"].prefix`) so that changing the copy
mode prefix also works when a modal is open.

### Modify mode activation (prefix keys from config):

Replace hardcoded prefix key checks with registry-driven dispatch:

1. **`src/sase/ace/tui/app.py`** (or wherever mode activation lives):
   - Instead of checking `key == "z"` to enter fold mode, iterate `self._keymap_registry.modes` and match `key` against
     each mode's `prefix` to determine which mode to activate.
   - Built-in modes dispatch to their existing handler functions.
   - Custom (user-defined) modes dispatch to a generic handler (see Phase 5).

### Verification

```bash
just test
just lint
.venv/bin/sase ace --agent --keys j j  # verify navigation still works
```

---

## Phase 3: Propagate to UI Display Elements

**Goal**: Footer, help modal, and tab bar display configured keys instead of hardcoded strings.

### Modify: `src/sase/ace/tui/widgets/keybinding_footer.py`

1. Add `set_keymap_registry(registry: KeymapRegistry)` method.
2. Store `self._registry`. Use it in:
   - `_compute_available_bindings` — replace `("a", "accept")` with
     `(key_display_name(self._registry.app.accept_proposal), "accept")` etc.
   - `_compute_agent_bindings` — same pattern for all hardcoded keys
   - `_compute_axe_bindings` — replace `("x", label)`
   - `update_leader_bindings` — use `self._registry.leader_mode.*` display names
   - `update_bang_bindings` — use `self._registry.bang_mode.*` display names
   - `update_copy_bindings` — use `self._registry.copy_mode.*` display names
   - `show_empty` — replace hardcoded `"/"` with configured `edit_query` key

3. In `AceApp.compose()` or `on_mount()`, call `footer.set_keymap_registry(self._keymap_registry)`.

### Modify: `src/sase/ace/tui/modals/help_modal/bindings.py`

Convert `CLS_BINDINGS`, `AGENTS_BINDINGS`, `AXE_BINDINGS` from module-level constants to **functions** that accept
`KeymapRegistry` and return the same structure, building display strings via `key_display_name()`:

```python
def cls_bindings(km: KeymapRegistry) -> list[tuple[str, list[tuple[str, str]]]]:
    d = key_display_name
    return [
        ("Navigation", [
            (f"{d(km.app.next_changespec)} / {d(km.app.prev_changespec)}", "Move to next / previous CL"),
            # ...
        ]),
        # ...
    ]
```

Update `help_modal/modal.py` to get registry from `self.app._keymap_registry` and call the function forms.

### Modify: `src/sase/ace/tui/modals/help_modal/modal.py` (own BINDINGS)

The `HelpModal` class has its own `BINDINGS` that duplicate app-level keys for passthrough while the modal is focused:
`circumflex_accent` → `prev_query`, `underscore` → `next_query`, `1-9/0` → saved queries. These must be rebuilt from the
registry in `__init__` so they track the user's configured keys. Chrome keys (`escape`, `q`, `?`, `ctrl+d/u`) stay
hardcoded.

### Modify: `src/sase/ace/tui/widgets/tab_bar.py`

1. Add `set_keymap_registry(registry: KeymapRegistry)` method.
2. In `_build_content()`:
   - Replace literal `f"x{self._agents_done_count}"` with `f"{dismiss_key}{self._agents_done_count}"` where
     `dismiss_key` comes from `key_display_name(registry.app.kill_agent)`
   - Replace literal `f".{h}"` with `f"{hide_key}{h}"` where `hide_key` comes from
     `key_display_name(registry.app.toggle_hide_reverted)`
   - Same for the axe tab (lines 180-185)
   - For CLs tab (line 141): the `.` separator in `CLs (M.H)` also corresponds to `toggle_hide_reverted`
3. In `AceApp.compose()` or `on_mount()`, pass registry to tab bar.

### Modify: `src/sase/ace/tui/actions/clipboard.py` (error messages)

Update the "Unknown copy key" error notifications to list configured keys instead of hardcoded ones:

```python
# Before: "Unknown copy key (CLs: %, !, b, c, n, p, s)"
# After: build from registry
```

### Update existing tests

- `tests/test_keybinding_footer_core.py` — add test with non-default registry
- `tests/test_keybinding_footer_agent.py` — verify configured keys appear in output

### Verification

```bash
just test
just lint
.venv/bin/sase ace --agent  # verify footer/tabs render correctly
.venv/bin/sase ace --agent --keys question_mark  # verify help modal shows correct keys
```

---

## Phase 4: Validation, Edge Cases, and Final Polish

**Goal**: Add validation, handle edge cases, and ensure completeness.

### Modify: `src/sase/ace/tui/keymaps.py`

Add validation in `load_keymap_registry`:

1. **Duplicate key detection**: If two app-level actions map to the same key, log a warning and fall back to default for
   the conflicting key.
2. **Invalid key validation**: Check that key strings are valid Textual identifiers.

### New file: `tests/test_keymaps_validation.py`

- Test duplicate key detection warns and falls back
- Test invalid key name detection

### End-to-end test: `tests/test_keymaps_e2e.py`

Test with `sase ace --agent` using a config overlay that remaps a key, verify navigation works with the new key.

### Review pass

- Verify ALL hardcoded key strings have been replaced (grep for remaining `key ==` patterns)
- Verify help modal content is complete and matches actual bindings
- Ensure `default_config.yml` keymaps section exactly matches the pre-change behavior

### Verification

```bash
just check  # full fmt-check + lint + test
.venv/bin/sase ace --agent --keys j j  # default keys still work
```

---

## Phase 5: Custom Mode Support

**Goal**: Allow users to define entirely new prefix-key modes via config, with sub-keys that trigger configurable shell
commands or built-in actions.

### Modify: `src/sase/ace/tui/keymaps.py`

1. **`CustomModeKeymaps`** — subclass of `ModeKeymaps` for user-defined modes. Each sub-key maps to an action spec:
   - `shell: "command"` — run a shell command (with `{entry}` placeholder for current entry context)
   - `action: "action_name"` — trigger an existing Textual action by name
   - `notify: "message"` — show a notification

2. In `load_keymap_registry`, any mode name not in the built-in set (`fold_mode`, `copy_mode`, `leader_mode`,
   `bang_mode`) is instantiated as `CustomModeKeymaps`.

### Modify: `src/sase/ace/tui/app.py`

1. **`_handle_custom_mode_key(mode_name: str, key: str)`** — generic handler for custom mode sub-keys:
   - Look up the action spec from `self._keymap_registry.modes[mode_name].keys[key]`
   - Dispatch based on action type (shell/action/notify)

2. **Mode activation dispatch** — when a pressed key matches a custom mode's prefix, enter a generic "custom mode" state
   that routes sub-keys to `_handle_custom_mode_key`.

**Design note**: Built-in modes use simple `key_name: "key"` mappings in `keys` because their handler logic is fixed in
code. Custom modes use action spec objects because their behavior must be defined entirely in config.

### Config example (custom mode with action specs):

```yaml
ace:
  keymaps:
    modes:
      git_mode:
        prefix: "semicolon"
        keys:
          status:
            action: "shell"
            command: "git status"
          diff:
            action: "shell"
            command: "git diff {entry}"
          log:
            action: "shell"
            command: "git log --oneline -20"
```

`load_keymap_registry` distinguishes the two by mode name: names in the built-in set (`fold_mode`, `copy_mode`,
`leader_mode`, `bang_mode`) parse `keys` as `str` values; all others parse `keys` as action spec dicts.

### Modify: `src/sase/ace/tui/widgets/keybinding_footer.py`

- When a custom mode is activated, display its sub-keys in the footer (same pattern as built-in modes).

### Modify: `src/sase/ace/tui/modals/help_modal/bindings.py`

- Generate help sections for custom modes dynamically from the registry.

### Tests: `tests/test_custom_modes.py`

- Test that custom modes are loaded from config
- Test prefix key activates custom mode
- Test sub-key dispatch for shell/action/notify types
- Test footer displays custom mode keys
- Test help modal includes custom mode section

### Verification

```bash
just check
.venv/bin/sase ace --agent --keys semicolon  # verify custom mode activates (if configured)
```

---

## Critical Files Summary

| File                                                       | Phase   | Change                                            |
| ---------------------------------------------------------- | ------- | ------------------------------------------------- |
| `src/sase/ace/tui/keymaps.py` (new)                        | 1, 4, 5 | Registry dataclasses, loader, helpers, validation |
| `src/sase/default_config.yml`                              | 1       | Add `ace.keymaps` section                         |
| `src/sase/ace/tui/app.py`                                  | 1, 2, 5 | Store registry, replace BINDINGS, custom modes    |
| `src/sase/ace/tui/actions/navigation/_advanced.py`         | 2       | Fold mode sub-keys                                |
| `src/sase/ace/tui/actions/clipboard.py`                    | 2, 3    | Copy mode sub-keys + error msgs                   |
| `src/sase/ace/tui/actions/agent_workflow/_entry_points.py` | 2       | Leader mode sub-keys                              |
| `src/sase/ace/tui/actions/axe.py`                          | 2       | Bang mode sub-keys                                |
| `src/sase/ace/tui/modals/base.py`                          | 2       | CopyModeForwardingMixin prefix from registry      |
| `src/sase/ace/tui/widgets/keybinding_footer.py`            | 3, 5    | Display configured keys + custom modes            |
| `src/sase/ace/tui/modals/help_modal/bindings.py`           | 3, 5    | Convert to functions + custom mode sections       |
| `src/sase/ace/tui/modals/help_modal/modal.py`              | 3       | Pass registry                                     |
| `src/sase/ace/tui/widgets/tab_bar.py`                      | 3       | `x` and `.` from config                           |

## Reusable Existing Code

- `src/sase/config.py` — `load_merged_config()` for loading, `_deep_merge()` handles partial overrides
- `src/sase/ace/tui/app.py:362` — existing pattern for `ace_cfg = merged.get("ace", {})`
- `src/sase/axe/config.py` — existing pattern for parsing config into dataclasses
