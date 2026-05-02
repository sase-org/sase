---
create_time: 2026-04-27 09:22:48
status: done
prompt: sdd/prompts/202604/g_keymap_restore.md
---
# Restore `g` to "scroll to top" on the Agents tab; move grouping-mode cycle to a new key

## Problem

A recent change (commit `2fb1d770`, "feat: cycle Agents-tab grouping mode with `g`") bound `g` to `cycle_grouping_mode`
on the Agents tab. The original behavior of `g` on every tab was `scroll_to_top` ("jump to top of agent info / detail
panel"), and `g` is the conventional vim-style mnemonic for that action (`scroll_to_bottom` is `G`).

The implementation works around the conflict with a dispatcher inside `action_cycle_grouping_mode` that delegates to
`action_scroll_to_top` on non-Agents tabs — but on the Agents tab itself, `g` no longer scrolls to top at all. This
breaks the prior muscle memory and is inconsistent with `G` = scroll to bottom right next to it.

The user wants:

1. `g` restored to its original `scroll_to_top` behavior **on every tab**, including the Agents tab.
2. The grouping-mode cycle moved to a different key — preferably a **lowercase letter that is not already bound on the
   Agents tab**.

## Investigation

### Files involved

- `src/sase/default_config.yml` — single source of truth for default keybindings (lines 13 and 75 bind
  `scroll_to_top: g` and `cycle_grouping_mode: g` respectively).
- `src/sase/ace/tui/bindings.py` — fallback `Binding` list (line 84: `Binding("g", "scroll_to_top", ...)`). Note: there
  is no fallback binding for `cycle_grouping_mode` here; it lives only in `default_config.yml` and `keymaps/types.py`.
- `src/sase/ace/tui/keymaps/types.py` — `_BINDING_META` controls the binding list order (line 85 `cycle_grouping_mode`
  BEFORE line 86 `scroll_to_top`); `AppKeymaps` dataclass field for `cycle_grouping_mode`.
- `src/sase/ace/tui/actions/agents/_grouping.py` — implements the dispatch: on non-agents tabs,
  `action_cycle_grouping_mode` falls through to `action_scroll_to_top`. Once the keys are independent, this fallthrough
  becomes dead code and can be removed.
- `src/sase/ace/tui/modals/help_modal/bindings.py` line 425 — references `d(a.cycle_grouping_mode)`, which auto-renders
  whatever key is bound, so no manual edit is needed beyond the config change.
- `tests/ace/tui/test_agent_grouping_cycle.py` — exercises `action_cycle_grouping_mode()` directly (not through key
  dispatch), so it is unaffected by the rebinding.

### Lowercase keymap census on the Agents tab

The Explore subagent walked every active app-level binding and confirmed the following lowercase letters are bound on
the Agents tab today:

```
a accept_proposal       n rename_cl
b rebase                p toggle_layout
c start_checkout_mode   q quit
d show_diff             r run_workflow
e edit_spec             s change_status
g cycle_grouping_mode   t start_tmux_mode
h hooks_or_collapse     u clear_marks
i show_notifications    v view_files
j next_changespec       w reword
k prev_changespec       x kill_agent
l expand_or_layout      y refresh
m toggle_mark           z start_fold_mode
```

**Free lowercase letters: `f` and `o`.** All others are taken.

### Replacement key choice

Both free letters work mechanically. Mnemonic considerations:

- **`f`** — common vim "find" key; in this codebase the query filter is bound to `/` (`slash` → `edit_query`), so
  binding `f` to a _grouping_ action would invite confusion with filtering.
- **`o`** — unbound and unburdened. Reads naturally as "organize" / "order" and is adjacent to grouping semantics. No
  collision with any planned key that I can see.

**Recommendation: `o`.** (We can fall back to `f` if `o` is reserved for something the user has in mind — please flag
during plan review.)

## Plan

Each step is small and independent enough to verify in isolation.

### Step 1 — Rebind in `default_config.yml`

Change line 75 of `src/sase/default_config.yml`:

```yaml
# Grouping mode cycle (agents tab)
cycle_grouping_mode: "o"
```

`scroll_to_top: "g"` on line 13 stays exactly as-is; that single change already restores `g` everywhere because the
dispatch in `_grouping.py` (next step) no longer steals the key.

### Step 2 — Simplify `action_cycle_grouping_mode`

In `src/sase/ace/tui/actions/agents/_grouping.py`:

- Remove the `if self.current_tab != "agents": self.action_scroll_to_top()` fall-through (lines 76-78). With an
  independent key, the action is only ever invoked when the user wants to cycle grouping; calling it on a non-Agents tab
  can become a silent no-op (or a small toast — see open question below).
- Update the module docstring to drop the "On non-agents tabs the action defers to `action_scroll_to_top`" paragraph.
- Update `action_cycle_grouping_mode`'s docstring similarly.

### Step 3 — Reorder `_BINDING_META` (cosmetic)

In `src/sase/ace/tui/keymaps/types.py`, the `cycle_grouping_mode` entry was deliberately placed BEFORE `scroll_to_top`
(lines 85-86) so its action would win when both bound to `g`. With distinct keys this priority no longer matters. Move
the entry to a more natural position (e.g. group it with the other Agents-tab-specific bindings near
`focus_next_agent_panel`). Purely cosmetic — keeps future readers from puzzling over the ordering.

### Step 4 — Verify help-modal text auto-updates

`src/sase/ace/tui/modals/help_modal/bindings.py:425` renders the bound key via `d(a.cycle_grouping_mode)`. After Step 1,
the help popup will display `o` automatically. **No edit required** — just confirm visually after the change.

### Step 5 — Tests

- Run `just test` to confirm no behavioral regressions.
- The existing `tests/ace/tui/test_agent_grouping_cycle.py` calls `action_cycle_grouping_mode()` directly, so it remains
  valid.
- Add a small assertion in an existing keymap test (or write a one-liner test) that `default_config.yml` binds
  `cycle_grouping_mode` to `o` and `scroll_to_top` to `g` — guards against an accidental future re-introduction of the
  conflict.

### Step 6 — `just check`

Run `just check` from the workspace before reporting back to the user, per the repo's CLAUDE.md instructions.

## Out of scope

- Renaming `cycle_grouping_mode` or restructuring the grouping mixin.
- Touching `G` (`scroll_to_bottom`) — it remains as-is.
- Updating user-side keymap overrides — users who customized `cycle_grouping_mode` keep their override; the change only
  affects the default.
- Documentation outside the help modal (no README/AGENTS.md mention of the `g` keymap exists today).

## Open questions for the user

1. **Letter choice — `o` vs `f`?** Plan defaults to `o` for the mnemonic reasons above; happy to switch to `f` if
   preferred.
2. **Behavior on non-Agents tabs** when `o` is pressed: silent no-op (simplest), small toast ("Grouping cycle is
   Agents-tab only"), or wire it to do something else? Plan currently assumes silent no-op.
