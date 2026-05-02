---
create_time: 2026-03-30 12:17:57
status: done
---

# Plan: Add `zC`, `zH`, `zM`, `zT` per-section toggle keymaps

## Context

The CLs tab fold mode currently has two tiers of keymaps:

- **Cycle** (`zc`, `zh`, `zm`, `zt`): cycle a single section through COLLAPSED → EXPANDED → FULLY_EXPANDED → COLLAPSED
- **All** (`zz`, `zZ`): cycle or toggle _all_ sections at once

There is no way to instantly toggle a _single_ section between COLLAPSED and FULLY_EXPANDED (skipping the intermediate
EXPANDED state). The new `zC`, `zH`, `zM`, `zT` keymaps fill this gap — each one toggles its respective section the same
way `zZ` toggles all sections: collapsed → fully expanded, or anything else → collapsed.

## Changes

### 1. Config — `src/sase/default_config.yml`

Add four new keys under `modes.fold_mode.keys`:

```yaml
toggle_commits: "C"
toggle_hooks: "H"
toggle_mentors: "M"
toggle_timestamps: "T"
```

### 2. Keymap types — `src/sase/ace/tui/keymaps/types.py`

Add the same four entries to the `FoldModeKeymaps.keys` default factory dict.

### 3. Fold action handler — `src/sase/ace/tui/actions/navigation/_advanced.py`

In `_handle_fold_key()`, add four new `elif` branches (between the cycle branches and the `cycle_all` branch) that
implement the binary toggle:

```python
elif key == fold_keys["toggle_commits"]:
    self.commits_collapsed = (
        FoldLevel.FULLY_EXPANDED if self.commits_collapsed == FoldLevel.COLLAPSED
        else FoldLevel.COLLAPSED
    )
```

(Same pattern for hooks, mentors, timestamps.)

### 4. Footer — `src/sase/ace/tui/widgets/keybinding_footer.py`

Add the four new toggles to `update_fold_bindings()` so the footer bar shows them when fold mode is active.

### 5. Help modal — `src/sase/ace/tui/modals/help_modal/bindings.py`

Add entries for each new toggle in the Fold Mode section (e.g., "Toggle commits collapsed/expanded").
