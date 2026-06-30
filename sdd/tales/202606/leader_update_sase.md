---
create_time: 2026-06-30 09:29:54
status: done
---
# Plan: Add a `,U` leader keymap to update sase, core, and all plugins

## Goal

Add a new leader-mode keymap `,U` (capital `U`) to the `sase ace` TUI that is a global shortcut for "update sase +
sase-core + all plugins". Pressing `,U` must present the **exact same y/n confirmation prompt** the user gets today by
opening the Admin Center, switching to the **Updates** tab, and pressing `u`. After the user confirms, the update runs
exactly as it does today; after a confirmed update the Admin Center closes itself (existing behavior). If the user
cancels the prompt, they are left on the Updates tab (same as having navigated there manually).

This is the user-requested behavior: _"After triggering this keymap the user should be using the same y/n prompt that we
use if the user goes to the Updates tab in the sase Admin Center and presses `u`."_

## Why `,U`

- `,u` (lowercase) is already taken by `mark_all_unread_done_agents_read`.
- `,U` (capital) is currently free among leader subkeys (capitals in use: `R M C I J A B T`; no `U`).
- Capital-letter leader subkeys already work in this codebase (`,R`, `,M`, `,A`, `,B`, …), so `event.key` for a shifted
  letter is the capital character — no special-casing needed.

## Design summary (reuse the existing flow, do not duplicate it)

The update flow already lives entirely in the **Updates** tab pane (`PluginsBrowserPane`) via
`SaseUpdateActionsMixin.action_update_sase()`. That action:

1. early-returns while the pane is still loading (`self._loading`) or a plan worker is in flight;
2. requires `self._uv_tool` to be populated — which only happens **after** the pane's initial async load worker
   completes;
3. computes a `DevUpdatePreview` in a worker, then shows the `PluginActionConfirmModal` (`y` = confirm, `n`/`esc`/`q` =
   cancel);
4. on confirm, submits the tracked update task and calls `_close_admin_center_after_sase_update()`.

Because `_uv_tool` is `None` and `_loading` is `True` until the pane's load worker finishes, we **cannot** just open the
modal and call `action_update_sase()` synchronously — it would be rejected. The faithful, low-risk approach is to **open
the Admin Center on the Updates tab and arm a one-shot "auto-trigger"** that fires `action_update_sase()` once the
pane's initial load completes. This reuses the real action, real preview, real confirm modal, and real task submission —
zero behavioral duplication.

No `sase-core` (Rust) changes are required: this is purely TUI presentation/keybinding/glue that opens an existing modal
and invokes an existing action. The actual update execution is unchanged.

## Implementation steps

### 1. Register the new leader subkey (keymap config + dataclass)

- `src/sase/default_config.yml` — add `update_sase: "U"` to the `leader_mode.keys` map (near the other capital-letter
  entries).
- `src/sase/ace/tui/keymaps/types.py` — add the matching `"update_sase": "U"` entry to the `LeaderModeKeymaps.keys`
  default-factory dict so the dataclass default stays in sync with the YAML.

### 2. Thread a one-shot auto-update flag into the Updates pane

In `src/sase/ace/tui/modals/plugins_browser_pane.py` (`PluginsBrowserPane`):

- Add a keyword-only constructor parameter, e.g. `auto_update_on_load: bool = False`, and store it
  (`self._auto_update_on_load = auto_update_on_load`). It only makes sense together with the default `auto_load=True`,
  which is what the Admin Center uses.
- In `on_worker_state_changed`, at the **end of the initial-load worker's `SUCCESS` branch** (the
  `event.worker is self._worker` success path, right after the existing `self._render_all()`), if the flag is set: clear
  it and schedule the action on the app event loop, e.g. `self.app.call_later(self.action_update_sase)`. Using
  `call_later` (rather than calling inline) keeps the trigger off the worker-state callback and matches
  `_uv_tool`/`_loading` being fully settled.
- In the initial-load worker's `ERROR` branch, clear the flag without triggering (a failed load leaves `_uv_tool`
  unpopulated; the user is simply left on the Updates tab showing the load error, identical to manual navigation on a
  failed load).

Notes / guards already in place that this relies on:

- `action_update_sase()` already guards against double-submission via `self._loading` / `self._sase_update_plan_worker`,
  and already handles the `NotUvToolInstall` (non-uv install) case with a warning toast — so the shortcut inherits
  identical edge-case behavior to pressing `u`.

### 3. Pass the flag through the Admin Center modal

In `src/sase/ace/tui/modals/config_center_modal.py` (`ConfigCenterModal`):

- Add a keyword-only `auto_update: bool = False` constructor parameter; store it.
- In `compose()`, construct the Updates pane with the flag:
  `yield PluginsBrowserPane(id="updates", auto_update_on_load=self._auto_update)`.

This is deterministic and race-free: the pane is composed up front in the `ContentSwitcher`, so the flag is set before
the pane's load worker can complete.

### 4. App-level entry point that opens Updates + arms the prompt

In `src/sase/ace/tui/actions/base.py` (alongside the existing `action_open_*_panel` / `_open_config_center` helpers):

- Extend `_open_config_center(self, initial_tab, *, auto_update: bool = False)` to forward `auto_update` into
  `ConfigCenterModal(initial_tab=initial_tab, auto_update=auto_update)`. Existing callers pass nothing and keep
  `auto_update=False`.
- Add a small public action, e.g. `action_update_sase_shortcut()`, that calls
  `self._open_config_center("updates", auto_update=True)`. (Name kept distinct from the pane's `action_update_sase` to
  avoid confusion.)

### 5. Dispatch the leader subkey

In `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`, inside `_dispatch_leader_key`, add a block mirroring the
`temporary_llm_override` (`,m`) handler:

```python
if key == leader_keys["update_sase"]:
    LeaderModeMixin._remember_leader_key(self, key, remember=remember)
    self.action_update_sase_shortcut()  # type: ignore[attr-defined]
    self._refresh_current_tab()  # type: ignore[attr-defined]
    return True
```

(`,U` works from the main TUI; like all leader keys it is naturally inert while a modal already owns the keyboard —
consistent with existing leader behavior.)

### 6. Command catalog (command palette)

In `src/sase/ace/tui/commands/_mode_commands.py`:

- Add a `_LEADER_LABELS["update_sase"]` entry, e.g. `"Update sase, core, and plugins"`.
- Leave `update_sase` **out** of `_LEADER_TABS` so it defaults to `ALL_TABS` (global), matching how
  `temporary_llm_override` is treated. This yields a `leader.update_sase` command whose `key_display` is `,U`, available
  on all tabs.

### 7. Leader-mode footer bar

In `src/sase/ace/tui/widgets/_keybinding_modes.py`, `update_leader_bindings()`: add an unconditional entry near the
`temporary_llm_override` line, e.g. `bindings.append((k("update_sase"), "update sase"))`, so the LEADER bar advertises
`,U` on every tab. (This is the LEADER-mode bar, not the conditional main footer, so a global entry is consistent with
how `model overrides`, `pin idle`, etc. are listed there.)

### 8. Help modal + docs

This action is global (all tabs), so advertise it in every help-modal binding list and the docs:

- `src/sase/ace/tui/modals/help_modal/changespecs_bindings.py`
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py`
- `src/sase/ace/tui/modals/help_modal/axe_bindings.py`

  In each, add a leader-mode entry mirroring the existing `temporary_llm_override` row, e.g.
  `(f"{d(lm.prefix)}{d(sk(lm.keys, 'update_sase'))}", "Update sase, core & plugins")`. Mind the help-modal width
  conventions (keybinding descriptions truncate at 32 chars).

- `docs/configuration.md` — add `update_sase: "U"` to the documented `leader_mode.keys` example.
- Update any other leader-mode keymap enumeration in the ACE docs (e.g. `docs/ace.md`) if one lists leader shortcuts.

### 9. Tests

Add/extend tests mirroring the established patterns for leader keys:

- `tests/test_keymaps_defaults.py` — assert `reg.leader_mode.keys["update_sase"] == "U"` and
  `LeaderModeKeymaps().keys["update_sase"] == "U"`. (The existing `test_leader_mode_default_subkeys_are_unique` will
  automatically guard against a `U` collision.)
- `tests/test_command_catalog.py` — add a test like `test_update_sase_leader_command_uses_uppercase_u` asserting the
  `leader.update_sase` spec has the expected label, `key_display == ",U"`, and `tabs == ALL_TABS`
  (`("changespecs", "agents", "axe")`).
- Leader dispatch test (e.g. in `tests/ace/tui/test_leader_keymap_dispatch.py`) — pressing `,U` invokes
  `action_update_sase_shortcut` / opens `ConfigCenterModal(initial_tab="updates", auto_update=True)`.
- Pane auto-trigger test (mirror existing `PluginsBrowserPane` tests) — when constructed with
  `auto_update_on_load=True`, the pane calls `action_update_sase` exactly once after its initial load worker reports
  `SUCCESS`, and does **not** call it on load `ERROR`.
- Modal wiring test — `ConfigCenterModal(initial_tab="updates", auto_update=True)` constructs the Updates pane with
  `auto_update_on_load=True`.
- Help-modal advertisement test (mirror `test_agents_help_advertises_*`) — `,U` appears with its label in the relevant
  help bindings.

## Edge cases & behavior parity

- **Non-uv / dev installs:** `action_update_sase` already branches to the dev-update plan for editable installs and
  warns for `NotUvToolInstall`; the shortcut inherits this unchanged.
- **Double-trigger:** the one-shot flag is cleared on first fire; `action_update_sase`'s own
  `_loading`/`_sase_update_plan_worker` guards prevent re-entry.
- **Cancel:** dismissing the y/n prompt leaves the Admin Center open on the Updates tab (same as manual navigation). On
  confirm, the existing `_close_admin_center_after_sase_update()` closes it.
- **Load failure:** flag cleared, no prompt; the Updates tab simply shows the load error.

## Verification

- `just install` then `just check` (lint + mypy + tests), per repo policy after file changes.
- Manual smoke check in the TUI: press `,U` from each tab → Admin Center opens on Updates and the same y/n update prompt
  appears; confirm runs the update and closes the Admin Center; cancel leaves the Updates tab open. Confirm `,u`
  (mark-all-read) is unaffected.

## Out of scope

- No changes to the underlying update mechanics (uv tool upgrade / dev update execution).
- No `sase-core` (Rust) changes — this is presentation/keybinding glue only.
