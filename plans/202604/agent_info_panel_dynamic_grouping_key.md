---
create_time: 2026-04-27 09:48:31
status: done
---
# Render the Agents-tab grouping badge's key hint dynamically (kill the hardcoded "(g)")

## Problem

Commit `31c10fc3` rebound `cycle_grouping_mode` from `g` to `o` (and restored `g` to `scroll_to_top`). However, the
Agents-tab info-panel badge still advertises the old key:

```
[group: default (g)]
```

The string `(g)` is hardcoded at `src/sase/ace/tui/widgets/agent_info_panel.py:128`:

```python
text.append(" (g)", style="dim")
```

so the badge lies about which key cycles grouping mode. Pressing `g` now scrolls to top instead, which makes the hint
actively misleading rather than merely stale.

The accompanying widget tests at `tests/ace/tui/widgets/test_agent_info_panel.py:24,33,42` assert `(g)` as a literal, so
they kept passing through the regression. The deeper miss is that the test pinned the symptom (a literal key) rather
than the contract (whatever key the registry binds to `cycle_grouping_mode`).

## Existing pattern

Two sibling widgets already render keys dynamically by accepting a `KeymapRegistry` at mount time:

- `src/sase/ace/tui/widgets/tab_bar.py` (lines 10, 26, 49, 215-217) — imports
  `KeymapRegistry, key_display_name, load_keymap_registry`; default-initializes
  `self._registry = load_keymap_registry({})` in `__init__`; exposes `set_keymap_registry(registry)`; calls
  `key_display_name(self._registry.app.<action>)` at render time.
- `src/sase/ace/tui/widgets/keybinding_footer.py` (lines 31, 53, 103-109) — same shape, uses `footer_key_display`.

Both are wired up in `src/sase/ace/tui/actions/startup.py:399-402`:

```python
footer = self.query_one("#keybinding-footer", KeybindingFooter)
footer.set_keymap_registry(self._keymap_registry)
tab_bar = self.query_one("#tab-bar", TabBar)
tab_bar.set_keymap_registry(self._keymap_registry)
```

`AgentInfoPanel` is mounted at `src/sase/ace/tui/app.py:239` (`yield AgentInfoPanel(id="agent-info-panel")`) but never
receives the registry today.

## Plan

### Step 1 — Make `AgentInfoPanel` keymap-aware

In `src/sase/ace/tui/widgets/agent_info_panel.py`:

1. Add the import:
   ```python
   from ..keymaps import KeymapRegistry, key_display_name, load_keymap_registry
   ```
2. In `__init__`, initialize a default registry so the badge renders sensibly before/without wiring:
   ```python
   self._registry = load_keymap_registry({})
   ```
   This mirrors `TabBar.__init__` (`tab_bar.py:26`) and `KeybindingFooter.__init__` (`keybinding_footer.py:53`).
3. Add a setter:
   ```python
   def set_keymap_registry(self, registry: KeymapRegistry) -> None:
       """Override the keymap registry and refresh display."""
       self._registry = registry
       self._update_display()
   ```
4. Replace line 128:
   ```python
   text.append(" (g)", style="dim")
   ```
   with:
   ```python
   key = key_display_name(self._registry.app.cycle_grouping_mode)
   text.append(f" ({key})", style="dim")
   ```

### Step 2 — Wire it up at startup

In `src/sase/ace/tui/actions/startup.py` around lines 390-402:

1. Add `AgentInfoPanel` to the existing `from ..widgets import (...)` block (currently imports
   `InactiveIndicator, KeybindingFooter, TabBar`).
2. Right after `tab_bar.set_keymap_registry(self._keymap_registry)`, add:
   ```python
   info_panel = self.query_one("#agent-info-panel", AgentInfoPanel)  # type: ignore[attr-defined]
   info_panel.set_keymap_registry(self._keymap_registry)
   ```

### Step 3 — Update the panel tests so they can't lie again

In `tests/ace/tui/widgets/test_agent_info_panel.py`:

The three assertions on lines 24, 33, 42 hardcode `(g)`. The fix is two-part:

1. Replace the literal `(g)` with `(o)` so the tests pass against the current default keymap.
2. **More importantly**, derive the expected key from the registry rather than hardcoding it, so a future rebinding of
   `cycle_grouping_mode` cannot produce a passing-but-wrong test the way it did this time. Concretely, add a
   module-level helper:

   ```python
   from sase.ace.tui.keymaps import key_display_name, load_keymap_registry

   _DEFAULT_GROUPING_KEY = key_display_name(
       load_keymap_registry({}).app.cycle_grouping_mode
   )
   ```

   and rewrite the assertions as e.g.:

   ```python
   assert f"[group: default ({_DEFAULT_GROUPING_KEY})]" in plain
   ```

This is the lesson from the original miss: the test pinned the wrong invariant.

### Step 4 — Audit for other stale `(g)` references

`Grep` for the literal `"(g)"` in `src/`. Current hits:

- `src/sase/ace/tui/widgets/agent_info_panel.py:128` — the bug; fixed in Step 1.
- `src/sase/ace/tui/actions/startup.py:213` — a stale code comment ("cycling modes (g) doesn't lose collapse intent").
  Update it to drop or rephrase the `(g)` reference (e.g. "cycling grouping mode") so future readers aren't misled.

No other code paths surface this hint.

### Step 5 — Verify

Run `just check` from the workspace per `CLAUDE.md`. Manually launch `sase ace`, switch to the Agents tab, and confirm
the badge reads `[group: default (o)]` (or whatever key the user has bound). Press `o` and confirm the cycle still
works.

## Out of scope

- Generalizing the badge to render hints for the view mode or filter — only the grouping hint exists today, and adding
  more is a UX change, not a bug fix.
- Touching the help modal — it already auto-renders via `d(a.cycle_grouping_mode)` and was visually verified in commit
  `31c10fc3`.
- Adding a defensive fallback if `_keymap_registry` is somehow unset on the app — the wiring in `startup.py` is
  unconditional, mirroring `tab_bar`/`footer`, and the `__init__` default keeps standalone widget instantiation
  (including the panel tests) working.

## Open question

**Should the test refactor (derive the expected key from the registry) be part of this change, or kept minimal (literal
`(o)`)?** Recommendation: derive it. The absence of that decoupling is exactly what allowed the regression to ship under
green tests. Happy to drop to a literal `(o)` if the user prefers the smaller diff.
