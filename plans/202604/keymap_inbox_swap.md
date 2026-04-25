---
create_time: 2026-04-25 15:26:09
status: done
---
# Keymap swap: free `i` for inbox, move `mark_inactive` under leader mode

## Goal

Reassign two ace TUI keybindings:

1. `mark_inactive` (currently `i`) → leader-mode chord `,I`.
2. `show_notifications` / inbox (currently `N`) → `i`.

Net effect: pressing `i` now opens the notification inbox, while `,I` toggles manual idle. The pinned-idle binding (`I`
→ `mark_inactive_pinned`) is **unchanged** — it still fires from the app level.

## Motivation

`i` is a high-traffic letter and the user wants it for the inbox/notifications modal, which is currently buried on `N`.
`mark_inactive` is rare enough that a two-key chord (`,I`) is acceptable. Capital `I` after the leader prefix (`,`)
keeps the chord mnemonic ("Inactive") and avoids colliding with the existing `,i` (`activity_info`) leader binding.

## Conflict & overlap audit

- App-level `i` is currently only `mark_inactive`. After this change it is free for `show_notifications`.
- App-level `N` is only `show_notifications`. After this change `N` becomes unbound (we are not reassigning it).
- Leader-mode keys in `default_config.yml`: `! r M m h space x X r i c n t .
  > `. Capital `I`is unused, so`,I` is free.
- App-level `I` remains `mark_inactive_pinned` (pin idle). The leader-mode dispatcher only consults `leader_mode.keys`,
  so app-level `I` does not conflict with leader-mode `I`.
- The `action_mark_inactive` Python method stays — only the keymap surface moves. The leader-mode dispatcher will invoke
  `self.action_mark_inactive()`.

## File-level changes

### 1. `src/sase/default_config.yml`

Under `ace.keymaps.app`:

- Delete the line `mark_inactive: "i"`.
- Change `show_notifications: "N"` → `show_notifications: "i"`.

Under `ace.keymaps.modes.leader_mode.keys`:

- Add `mark_inactive: "I"` (alphabetically grouped with the other uppercase-letter keys, e.g. near `kill_all`).

Leave `mark_inactive_pinned: "I"` (under `app:`) untouched.

### 2. `src/sase/ace/tui/keymaps/types.py`

- Remove `("mark_inactive", "Mark Inactive", False)` from `_BINDING_META`.
- Remove the `mark_inactive: str` field from the `AppKeymaps` dataclass.
- Add `"mark_inactive": "I"` to the `LeaderModeKeymaps` defaults dict (the inline default lambda used when leader mode
  is omitted from config).

The module-level consistency check (`_BINDING_META_ACTIONS == _APP_KEYMAP_FIELDS`) will continue to hold because both
sides drop the entry.

### 3. `src/sase/ace/tui/bindings.py`

- Delete `Binding("i", "mark_inactive", "Mark Inactive", show=False)`.
- Change `Binding("N", "show_notifications", ...)` → `Binding("i", "show_notifications", "Notifications", show=False)`.

This file is only used as a Textual class-level fallback; the live runtime bindings come from
`build_app_bindings(self._keymap_registry.app)` invoked in `startup.py`. Keeping it consistent matters for tests and for
the brief window before the registry rebuilds the binding map.

### 4. `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`

In `_handle_leader_key`, add a branch (place it next to the other "always applicable" actions like `activity_info`):

```python
if key == leader_keys["mark_inactive"]:
    self.action_mark_inactive()  # type: ignore[attr-defined]
    self._refresh_current_tab()  # type: ignore[attr-defined]
    return True
```

`action_mark_inactive` already lives on the lifecycle mixin — no other change is needed to invoke it.

### 5. `src/sase/ace/tui/widgets/keybinding_footer.py`

In `update_leader_bindings`, add an entry to the always-shown leader bindings list so the chord is discoverable when the
user enters leader mode:

```python
bindings.append((k("mark_inactive"), "mark idle"))
```

Place it near `activity_info` (both are universally available, not tab/state-conditional). This is consistent with the
existing pattern of listing universally available leader actions in the footer alongside conditional ones.

### 6. `src/sase/ace/tui/modals/help_modal/bindings.py`

In all three section builders (`cls_bindings`, `agents_bindings`, `axe_bindings`), the General section currently has:

```python
(d(a.mark_inactive), "Toggle idle (any key clears)"),
```

`a.mark_inactive` no longer exists. Two options:

**Chosen approach — keep it in General with the chord display:**

Replace each occurrence with:

```python
(f"{d(lm.prefix)}{d(_sk(lm.keys, 'mark_inactive'))}", "Toggle idle (any key clears)"),
```

`lm` is already bound to `km.leader_mode` at the top of every section builder, so no extra plumbing is required.

The pinned-idle line (`a.mark_inactive_pinned`) stays unchanged.

**Rejected alternative:** moving the entry into the per-tab "Leader Mode" section. Rejected because the help reader is
more likely to look up "toggle idle" under General display tweaks than under Leader Mode actions, and the existing
convention in this file is fine with chord displays appearing in General (see `start_agent_from_changespec` already
shown in chord form).

### 7. `src/sase/ace/tui/modals/help_modal/bindings.py` — update inbox label

The help-modal General section already says "Show notifications". With the key now being `i`, that label is fine; the
binding will simply render as `i` because it pulls from `d(a.show_notifications)`. No code change beyond what section 6
already does.

### 8. `docs/ace.md`

The "Remapping Built-in Keys" example at line 786 currently uses `mark_inactive: "I"` as the remap example. That field
is no longer app-level, so the example would fail at startup with a config error. Replace that line with a still-valid
app-level remap example (suggested: `show_notifications: "n"  # Remap i → n`), so the section continues to demonstrate a
meaningful remap and uses the newly relevant `show_notifications` binding.

### 9. `tests/test_keymaps.py`

`test_build_app_bindings_count` asserts exactly **86** bindings (76 configurable + 10 digit). Removing `mark_inactive`
from `AppKeymaps` reduces the configurable count to 75, so the assertion must drop to **85** and the inline
comment/docstring updated accordingly.

Scan the rest of `tests/test_keymaps.py` for any other reference to `mark_inactive` (e.g. tests that build a fixture
with a literal `mark_inactive=...` kwarg in `_default_app_keymaps`) and remove those too. Add (or update) coverage that
ensures `LeaderModeKeymaps` includes `mark_inactive` by default — small dict-membership assertion is enough.

If any other test in `tests/` constructs an `AppKeymaps` directly with all fields specified, the removed field must come
out there as well.

## Out of scope

- No change to `mark_inactive_pinned` (`I` at app level) — sticky idle still works the same way.
- No change to `activity_info` (`,i`) — the leader-mode chord that opens the activity dashboard.
- No new functionality; this is a pure rebinding.

## Validation plan

1. `just install` (workspace clone may have stale deps).
2. `just check` — must pass: lint, mypy, and tests. The keymap-count test change above is the only test-side adjustment
   expected; surface anything else that fails.
3. Manual smoke-test in the TUI:
   - Press `i` → notification modal opens.
   - Press `N` → no-op (no longer bound).
   - Press `,I` → idle indicator toggles on; press any key → idle clears.
   - Press `I` (no leader) → pinned idle still toggles.
   - Press `,i` → activity dashboard still opens.
   - Open `?` help — three General sections show "Toggle idle" labelled with the `,I` chord; "Show notifications"
     labelled with `i`.
   - Enter leader mode (`,`) — footer shows the new `I mark idle` entry.

## Risk & rollback

Risk is low — surface area is small and constrained to keymap configuration plus three downstream consumers (Textual
bindings list, leader dispatcher, help/footer text). Rollback is a single revert of the resulting commit.
