---
create_time: 2026-06-24 07:30:17
status: done
prompt: sdd/prompts/202606/prompt_history_load_more_ctrl_d.md
---
# Plan: Rebind prompt-history "load more" from PageDown to `Ctrl+D`

## Goal

In the ACE prompt-history modal, prompt history is sharded so only the most recent 250 prompts load on open; pressing a
key loads the next 250 older prompts ("load more"). That trigger is currently `PageDown`. Change the trigger to
`Ctrl+D`, and update every place that wires or documents the key so the UI, help, and docs stay in sync.

Scope is **only** the prompt-history modal. The visually-similar saved-agent-group revival modal also uses a `pagedown`
→ `load_more` binding, but it is a separate feature and (importantly) already binds `Ctrl+D` to delete — it must be left
untouched.

## Background / why this needs care

The binding is a hardcoded Textual `Binding` on the modal class, **not** part of the configurable keymap system in
`src/sase/default_config.yml`. The only keys in `default_config.yml` related to prompt history are the leader keys that
_open_ the modal (`prompt_history`, `prompt_history_edit_first`, `prompt_history_cancelled`), which are unrelated and
stay as-is. So there is no config-file change.

`Ctrl+D` is used elsewhere in the app (e.g. app-level `scroll_detail_down`, and per-modal scroll/delete actions), but
Textual bindings are **scoped**: a binding on this modal/screen takes precedence while the modal is open. The precedent
is the saved-agent-group revival modal, which already owns `Ctrl+D` locally. So global usage is not a blocker.

There is exactly **one real in-scope conflict**: the prompt-history modal focuses its filter input (`FilterInput`, a
subclass of Textual's `Input`) on mount, and Textual's `Input` binds `Ctrl+D` to `delete_right` (delete the character to
the right of the cursor). Without handling, pressing `Ctrl+D` while the filter box is focused (the default focus) would
mutate the filter text instead of loading more prompts.

This is the **same class of problem the modal already solves** for `Ctrl+X` (which `Input` binds to "cut") and `Tab`
(focus cycling): the modal intercepts those keys in its screen-level `on_key` handler. We follow that established
pattern for `Ctrl+D`. (The navigation mixin `OptionListNavigationMixin.NAVIGATION_BINDINGS` does _not_ bind `Ctrl+D`, so
there is no conflict from list navigation.)

## Changes

### 1. `src/sase/ace/tui/modals/prompt_history_modal.py` (the core change)

- **Binding** (currently `Binding("pagedown", "load_more", "Load More", priority=True)`): change the key from
  `"pagedown"` to `"ctrl+d"`. Keep `priority=True` and the `load_more` action name. The `action_load_more` /
  `_load_more_async` plumbing is unchanged.

- **`on_key` interception**: add a `Ctrl+D` branch mirroring the existing `Ctrl+X`/`Tab` branches —
  `event.prevent_default()`, `event.stop()`, then `self.action_load_more()`. This guarantees `Ctrl+D` triggers load-more
  (rather than the focused `FilterInput`'s `delete_right`) regardless of binding-resolution order. Update the `on_key`
  docstring to note `Ctrl+D` is intercepted because the focused `Input` binds it to `delete_right`.

- **Hint footer string**: in the bottom hints `Static`, replace `PgDn: older +250` with `^d: older +250` (matching the
  `^n/^p`, `^g`, `^i`, `^x`, `^y` short-form convention already used in that same string).

- **Count-label suffix**: in `_history_count_label()`, replace the `" · PgDn +250 older"` suffix with
  `" · ^d +250 older"`. (The "loading older..." suffix has no key reference and stays.)

### 2. Help modal binding tables (6 strings)

These per-tab help entries describe the prompt-history modal ("Prompt history (PgDn older)" / "History +cancelled (PgDn
older)"). Replace `PgDn` with `^d` in each:

- `src/sase/ace/tui/modals/help_modal/agents_bindings.py` — both prompt-history rows.
- `src/sase/ace/tui/modals/help_modal/changespecs_bindings.py` — both prompt-history rows.
- `src/sase/ace/tui/modals/help_modal/axe_bindings.py` — both prompt-history rows.

Keep within the help modal's description width budget (max 32 chars per the ace help-modal formatting rule); `^d` is
shorter than `PgDn`, so all entries shrink and stay within budget.

### 3. User-facing docs: `docs/ace.md`

The "Prompt History Modal → Keybindings" table currently does **not** list the load-more key at all (a pre-existing
documentation gap). Add a row documenting the new binding, e.g. ``| `Ctrl+D` | Load older prompts (+250) |``, placed
consistently with the other rows. This keeps the docs in sync with functionality (per the repo's help/docs-sync
convention).

## Explicitly out of scope (do NOT change)

- `src/sase/ace/tui/modals/saved_agent_group_revival_modal.py` — separate modal; it owns `pagedown` → `load_more` _and_
  already binds `Ctrl+D` → `delete_group`. Leave entirely.
- `src/sase/ace/tui/widgets/agent_list.py` — generic `pagedown` list page-scroll, unrelated.
- `src/sase/ace/tui/keymaps/types.py` — `"pagedown"` is just a valid key-name in the keymap type registry.
- `src/sase/default_config.yml` — the load-more binding is not config-driven; the prompt-history leader keys there are
  unrelated.
- Historical SDD tales/plans under `sdd/` that mention `PgDn` (e.g. the sharded-prompt-history tale) — these are records
  of past work and are not rewritten.

## Tests

- **New Pilot/interaction test** (in `tests/ace/tui/modals/test_prompt_history_modal.py`): with a monkeypatched
  deterministic `load_prompt_record_page` that returns a non-exhausted first page then a second page, mount the modal,
  type filter text into the focused `FilterInput`, press `Ctrl+D`, and assert (a) a second page was appended /
  `load_more` ran, and (b) the filter text is unchanged (proving `Ctrl+D` did not fall through to the input's
  `delete_right`). This is the test that locks in the conflict resolution.
- **Count-label test**: add/extend a unit assertion for the non-exhausted `_history_count_label()` branch asserting the
  suffix now reads `^d +250 older` (existing count-label test only covers the exhausted branch).
- Confirm existing `test_prompt_history_modal.py` tests still pass (they assert on labels/filter/preview and do not
  reference the key, so they should be unaffected).

## Visual snapshot

The prompt-history modal has a PNG golden (`prompt_history_modal_redesign_120x40`) that renders the bottom hints line,
which now shows `^d` instead of `PgDn`. Regenerate it with the visual-update flag
(`just test-visual --sase-update-visual-snapshots`, or the equivalent pytest flag) and commit the updated golden. (The
snapshot fixture renders the exhausted state, so the count-label suffix change is not captured, but the hints-line
change is.)

## Verification

- `just install` then `just check` (lint + mypy + tests).
- `just test-visual` to confirm the regenerated golden matches.
- Manual smoke (optional): open the prompt-history modal, confirm `Ctrl+D` loads the next 250 older prompts, confirm
  typing in the filter box and pressing `Ctrl+D` loads more without deleting filter characters, and confirm `PageDown`
  no longer triggers load-more.

## Risks / notes

- `Ctrl+D` conventionally means "scroll half-page down" / "delete-forward" elsewhere; within this modal we deliberately
  scope it to load-more and override the filter input's `delete_right`. Losing forward-delete in this narrow filter box
  is acceptable (Backspace/Delete remain; the modal already overrides `Ctrl+F`/`Ctrl+B` and `Ctrl+X` in this input), and
  semantically "down into older history" is a reasonable fit.
- If the new Pilot test shows `priority=True` alone already prevents the input from eating `Ctrl+D`, the `on_key` branch
  is still kept as defense-in-depth and is harmless (the `action_load_more` guard plus the exclusive worker make any
  double-trigger a no-op).
