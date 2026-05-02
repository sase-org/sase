---
create_time: 2026-04-28 15:27:58
status: done
prompt: sdd/prompts/202604/restore_edit_hooks_keymap.md
---
# Restore the "edit hooks" CL-tab keymap (lost when CLs-tab grouping became always-on)

## Problem

Before commit `d7b96606` ("feat(ace): remove FLAT grouping from the CLs tab"), pressing `h` on the CLs tab did one of
two things depending on whether grouping was active:

- Grouping active: collapse the current CL group's fold.
- Grouping inactive (FLAT): fall through to `action_edit_hooks()` — the interactive flow that lets the user add a new
  HOOKS entry, re-run a hook by hint number, or delete a hook.

`H` had a parallel split: collapse-all-groups when grouped, otherwise call `action_hooks_from_failed()` (read the TAP
metahook's failed-targets file and add each as a hook).

Commit `d7b96606` removed FLAT grouping entirely and simplified `action_hooks_or_collapse()` /
`action_hooks_or_collapse_all()` to be fold-only on the CLs tab. The two action methods that used to be reachable
through that fall-through now have **zero callers** anywhere in `src/` or `tests/`:

- `action_edit_hooks()` — `src/sase/ace/tui/actions/hints/_hooks.py:15`
- `action_hooks_from_failed()` — `src/sase/ace/tui/actions/hints/_hooks.py:53`

Both implementations are intact and ready to be re-bound; they simply no longer have a key. Two pieces of UI also still
_claim_ the old behavior exists:

- `src/sase/ace/tui/modals/help_modal/bindings.py:74` — labels `h` as "Edit hooks".
- `src/sase/ace/tui/modals/help_modal/bindings.py:75` — labels `H` as "Add hooks from failed targets".
- `src/sase/ace/tui/widgets/_keybinding_bindings.py:233` — when a failed-hooks file is present on disk, the conditional
  footer still advertises `H` as "hooks (failed)".

So the docs are lying to the user, and the functionality is silently gone.

The user wants the `h` (edit hooks) functionality restored under a fresh, available key.

## Proposal

Bind `action_edit_hooks` to a new app-level key, leaving `h` / `H` as fold-only as the d7b96606 refactor intended. Fix
the help modal so it points at the new key. Surface — but do not silently expand into — the parallel question of what to
do about `action_hooks_from_failed`.

### Recommended key: `f`

Census of currently-bound app-level keys (gathered from `src/sase/default_config.yml` + `src/sase/ace/tui/bindings.py`):

- **Lowercase taken**: `a, b, c, d, e, g, h, i, j, k, l, m, n, o, p, q, r, s, t, u, v, w, x, y, z` — every letter except
  `f`.
- **Uppercase taken**: `A, C, E, G, H, I, J, K, L, M, N, Q, R, S, T, V, W, X, Y`.
- **Uppercase free**: `B, D, F, O, P, U, Z` (note: `Z` is meaningful _inside_ fold-mode as `zZ` = toggle_all, but the
  app-level standalone `Z` is unbound).

`f` is the only available **lowercase** letter, which matters because:

1. The original keymap was lowercase `h`. Restoring lowercase preserves typing rhythm — no shift modifier — so muscle
   memory translates cleanly.
2. `f` is adjacent to `g`/`h` on the home row, keeping the fold/edit cluster physically grouped.
3. The "fix hooks" / "failing hooks" mnemonic reads naturally for a key that re-runs and edits failing hook entries.
4. Conventional vim-style "find" usage is irrelevant here: the codebase already binds `/` (`slash` → `edit_query`) for
   filtering, so `f` is not in the user's filter-key associations on this TUI.

Uppercase `F` is the closest alternative; defer to user preference if `f` feels wrong.

## Files that change (single-key restore — Phases 1 & 2)

All five changes are mechanical and reach the four layers that touch keymaps in this repo:

1. **`src/sase/default_config.yml`** — under `ace.keymaps.app`, add a new `# ChangeSpec edits` group near the existing
   "CL actions" / "Fold / collapse" section:

   ```yaml
   # ChangeSpec edits
   edit_hooks: "f"
   ```

2. **`src/sase/ace/tui/keymaps/types.py`**:
   - Add a tuple to `_BINDING_META` (around line 47, next to `hooks_or_collapse`):
     `("edit_hooks", "Edit Hooks", False),`
   - Add a `edit_hooks: str` field to the `AppKeymaps` dataclass (around line 222, in the "Fold / collapse" or a new
     "ChangeSpec edits" section).
   - The module-level consistency check at line 398 (`_BINDING_META_ACTIONS != _APP_KEYMAP_FIELDS`) raises immediately
     at import time if either side drifts, so this layer self-validates.

3. **`src/sase/ace/tui/bindings.py`** — append a fallback `Binding` so the action is reachable even if a user provides a
   partial config:

   ```python
   Binding("f", "edit_hooks", "Edit Hooks", show=False),
   ```

   Place it next to the existing `Binding("h", "hooks_or_collapse", …)` at line 20 for readability.

4. **`src/sase/ace/tui/modals/help_modal/bindings.py:74`** — change the stale tuple:

   ```python
   (d(a.hooks_or_collapse), "Edit hooks"),     # before — wrong
   (d(a.edit_hooks), "Edit hooks"),            # after  — correct
   ```

   `key_display_name` will render whatever key the registry resolves, so no further help-modal touch-ups are needed.

5. **No work in `src/sase/ace/tui/actions/hints/_hooks.py`** — `action_edit_hooks()` is already correct. The Textual
   binding builder at `src/sase/ace/tui/keymaps/loader.py:298-312` iterates `_BINDING_META`, calls
   `getattr(app_km, "edit_hooks")` to fetch the key, and emits `Binding(key, "edit_hooks", …)` whose action_name
   dispatches to `action_edit_hooks()` automatically.

## Phase plan

### Phase 1 — Wire the new keymap

Make changes (1)–(3) above. Boot `sase ace`; on the CLs tab with a CL selected, press `f` and confirm the hint-input bar
mounts (the same bar `h` previously summoned in FLAT mode).

### Phase 2 — Fix the help modal

Make change (4). Open the help modal (`?`), confirm the "CL Actions" section now shows `f Edit hooks` (and no longer
mis-labels `h` as "Edit hooks"). `h` continues to appear in the "Folds" section as fold-collapse, which is correct.

### Phase 3 — Tests

- The consistency check at `types.py:398` already guards against dataclass/`_BINDING_META` drift at import time, so no
  new test is needed for that invariant.
- `tests/test_keymaps.py` and `tests/test_keymaps_validation.py` parse the default config and validate every key name;
  add a single assertion that `app_km.edit_hooks == "f"` so an accidental rebind is caught.
- `tests/test_keymaps_e2e.py` exercises full key dispatch — add (or extend an existing) test that simulates pressing `f`
  on the CLs tab and asserts `action_edit_hooks` was invoked (e.g. by patching the method or asserting the HintInputBar
  gets mounted with `mode="hooks"`).
- Quick-scan `tests/ace/tui/` for any test that hard-codes `h` as the edit-hooks trigger; update if found. (None
  expected — the action was reached only via fall-through, never directly bound under that name in tests.)

### Phase 4 — `just check`

Run the full lint + type + test gate per the repo's standing instruction. The dataclass field addition will trip mypy
immediately if anything is missed.

## Open questions for the user

These three questions block scope decisions; please answer before I implement.

### Q1 — Should we _also_ restore `action_hooks_from_failed()` under a new key?

`action_hooks_from_failed()` is the sibling orphan reached only through the old `H` fall-through. It reads a TAP
metahook's failed-targets file (`get_failed_hooks_file_path(changespec)`) and adds each `//target` line as a hook.
Today:

- The action method exists but has zero callers.
- The help modal at `bindings.py:75` still claims `H` does this.
- The conditional footer at `_keybinding_bindings.py:233` still advertises `H` as "hooks (failed)" when a failed-hooks
  file exists.

So the gap is real and user-visible. Recommendation: **yes, restore it** under uppercase `F` (mnemonic: "Failed hooks")
for symmetry with the lowercase `f` proposed above. Concretely that adds Phase 3':

- Add `add_hooks_from_failed: "F"` to AppKeymaps + `_BINDING_META` + `default_config.yml` + bindings.py fallback (action
  method already named `action_hooks_from_failed`, so the field name should match: `hooks_from_failed: str`, binding
  action `"hooks_from_failed"`).
- Update help modal `bindings.py:75` to point at `a.hooks_from_failed`.
- Update footer `_keybinding_bindings.py:233` to use `self._kd("hooks_from_failed")` (preserving the
  `if get_failed_hooks_file_path(changespec):` guard, which is the correct conditional pattern per AGENTS.md "Footer
  Keybinding Convention" since the action is sometimes-applicable).

If the answer is "no, leave it alone", we should at minimum **delete** the stale lines at `help_modal/bindings.py:75`
and `_keybinding_bindings.py:233` and remove the `action_hooks_from_failed()` method as dead code, so we stop lying to
the user. The codebase has a "no half-finished implementations" norm — ask before merging silently.

### Q2 — `f` (lowercase) vs `F` (uppercase) for `edit_hooks`?

Recommendation: **lowercase `f`**, matching the original `h` shape (no shift modifier needed) and natural mnemonic.
Uppercase `F` is the next-best option but only makes sense if Q1 is "no" (otherwise `F` is more naturally "Failed
hooks").

### Q3 — Field/action naming

Confirm the new YAML/dataclass field should be named `edit_hooks` so it dispatches to the existing
`action_edit_hooks()`. (This is how every other binding in `_BINDING_META` works; deviating would force renaming the
action method too. Recommendation: keep `edit_hooks`.)

## Out of scope (intentionally)

- Do **not** touch `action_hooks_or_collapse` / `action_hooks_or_collapse_all`. Their fold-only behavior is correct
  post-d7b96606; only the _labels_ in the help modal were stale, and Phase 2 fixes those without behavior changes.
- Do **not** add new functionality to `action_edit_hooks()`. It is being restored as-is.
- The footer pattern for `edit_hooks` itself: `edit_hooks` is always-applicable on the CLs tab, so per AGENTS.md "Footer
  Keybinding Convention" it belongs in the **help modal only**, not the footer. Don't add a footer entry.
