---
create_time: 2026-06-22 10:08:54
status: done
prompt: sdd/prompts/202606/unify_prompt_stash_panel.md
---
# Unify Prompt-Stash Keymaps via a Per-Entry Restore Panel

## Context

The prompt stash currently exposes **two parallel restore flows**, differentiated by a modal-level `destructive` flag
that is fixed at the moment the picker opens:

- **Load (`gp` / insert-mode `<ctrl+g>p`)** — opens `StashedPromptsModal(destructive=False)`. Chosen entries are
  _copied_ into the bar; the stash is left intact; delete-marking is disabled.
- **Restore (`gP` / insert-mode `<ctrl+g>P`)** — opens `StashedPromptsModal(destructive=True)`. Chosen entries are
  _popped_ (removed) from the stash and loaded; the `d` key can also mark entries for discard.

The global `@` keymap (`restore_prompt_stash`) is hard-wired to the destructive flow: it immediately opens the
pop-everything picker.

This means the pop-vs-copy decision is made _before_ the user sees the list, and it is duplicated across four
keybindings plus a global one. The user must pick the right key up front, and a mixed intent ("bring two of these back
for good, but keep this third one stashed") is impossible in a single pass.

This plan **collapses the two flows into one panel** where the pop-vs-keep choice is made _per entry, inside the panel_.
Every entry point — `@` and `<ctrl+g>p` — opens the same panel; the modal-level `destructive` flag disappears.

### Boundary check (Rust core)

This is a **presentation-only** change. The store operations it relies on already live in the Rust facade
(`read_prompt_stash_snapshot`, `pop_prompt_stash`, `append_prompt_stash`) and are **not modified**. The only new logic
is the app-layer decision of _which ids to pop vs. leave_ — a thin orchestration over the existing `pop_prompt_stash`,
not new core behavior. No `sase-core` change is required.

## Goals

- One stash panel, reachable identically from `@` and `<ctrl+g>p`. No modal-level pop-vs-copy mode.
- Per-entry choice inside the panel:
  - `<space>` → **restore + pop** (load into the bar, remove from the stash).
  - `<tab>` → **restore + keep** (load into the bar, leave it in the stash).
- Two clearly distinct, beautiful indicators for the two restore variants, alongside the existing delete indicator.
- Retire `gp`, `gP`, and `<ctrl+g>P`. Keep `<ctrl+g>p` working in **both normal and insert** mode.
- `@` continues to work everywhere (PRs / Agents / Axe tabs, and from the prompt bar in normal mode), now opening the
  panel instead of auto-popping.
- Keep keymap config, help text, the command catalog, hints, tests, and the PNG snapshot in sync.

## Non-Goals

- Do **not** add a new stash storage path, a new core store operation, or a Rust-core change.
- Do **not** reintroduce the retired leader-mode `,P` restore binding.
- Do **not** change how prompts are _captured_ (`gs` / `gS`), the top-bar badge widget, or the badge's snowflake glyph.
- Do **not** change bundle (multi-prompt entry) restore semantics beyond what is described below (bundles remain
  delete-able and restorable-when-highlighted, but are not individually `<space>`/`<tab>`-markable — preserving today's
  behavior).
- Do **not** add/remove any _app-level_ keymap (`@`/`restore_prompt_stash` stays exactly as configured), so the app
  binding count is unchanged.

## UX Design

### One panel, three per-entry marks

The panel title becomes simply **"Stashed prompts (N)"** (no more "Restore" vs "Load" wording). Each row can be in
exactly one of four states; the three marks are mutually exclusive (setting one clears the others on that entry):

| Mark           | Key       | Meaning                                         | Indicator (proposed)      |
| -------------- | --------- | ----------------------------------------------- | ------------------------- |
| Restore + pop  | `<space>` | Load into the bar **and remove** from the stash | `✓` bold violet `#AF87FF` |
| Restore + keep | `<tab>`   | Load into the bar, **leave** it in the stash    | `✚` bold green `#5FD787`  |
| Delete         | `d`       | **Remove** from the stash, do **not** load      | `✗` bold red              |
| (none)         | —         | Leave untouched                                 | two spaces                |

Notes on the indicator design:

- All three glyphs are from the Unicode **Dingbats** block (`✓` U+2713, `✚` U+271A, `✗` U+2717) so they read as one
  visual family; color carries the primary meaning (violet = "comes back from the stash", green = "kept/duplicated", red
  = "discarded"). Violet matches the existing stash-badge color, reinforcing "this leaves the stash."
- `✚` (heavy plus) is verified to render under the pinned Fira Code visual fixtures during implementation; if it does
  not, fall back to ASCII `+` (same column width, same green). The hint line self-documents the glyphs regardless.
- Marked rows keep today's treatment: bold preview when marked for either restore variant; dim + strikethrough when
  marked for delete.

### Keys inside the panel

```
j/k ↑/↓ navigate   space ✓ restore+pop   tab ✚ restore+keep   d ✗ delete   a all   enter confirm   esc/q cancel
```

- `<space>` toggles restore+pop on the highlighted single-prompt row.
- `<tab>` toggles restore+keep on the highlighted single-prompt row. Bound with `priority=True` so it beats the global
  `tab → next_tab` priority binding (matching the existing `revive_agent_modal` precedent).
- `d` toggles delete on the highlighted row (now always available — there is no longer a non-destructive mode that
  disables it).
- `a` toggles **restore + pop** on all selectable rows (the primary bulk action).
- `enter` confirms. **If no rows are marked, `enter` restores + pops the highlighted row** — the conventional stash→pop
  quick path, preserving the muscle memory of today's `gP`-picker enter behavior.
- `esc` / `q` cancel.

### Keymap model after the change

| Key                          | Where                                         | Before                            | After                  |
| ---------------------------- | --------------------------------------------- | --------------------------------- | ---------------------- |
| `@` (`restore_prompt_stash`) | global (all tabs) + prompt bar in NORMAL mode | auto-pop everything (destructive) | open the unified panel |
| `<ctrl+g>p`                  | prompt bar, NORMAL **and** INSERT mode        | load (non-destructive)            | open the unified panel |
| `<ctrl+g>P`                  | prompt bar, INSERT mode                       | restore (destructive)             | **removed**            |
| `gp`                         | prompt bar, NORMAL mode                       | load (non-destructive)            | **removed**            |
| `gP`                         | prompt bar, NORMAL mode                       | restore (destructive)             | **removed**            |

Why this is coherent and reliable:

- In **normal** mode the bar does not consume `@`, so it bubbles to the app-level `restore_prompt_stash` binding —
  verified: `_handle_normal_mode_key` returns `False` for `@`, and the `#@` snippet trigger only fires when the
  preceding character is a literal `#`. So `@` is the natural normal-mode entry point and `gp` is redundant.
- In **insert** mode `@` is (correctly) a literal character, so `<ctrl+g>p` is the insert-mode entry point. It also
  works in normal mode for users who prefer the `^G` prefix, giving one consistent in-bar chord across both modes.
- `<space>` and `<tab>` are no longer needed as separate _entry_ keys, so the two restore semantics move _inside_ the
  panel where they belong.

## Technical Design

### 1. The panel: `src/sase/ace/tui/modals/stashed_prompts_modal.py`

- **Drop the `destructive` constructor flag.** `__init__(self, entries)` only.
- **Replace the two-set selection model** (`_selected` / `_deleted`) with three mutually-exclusive sets: `_pop`,
  `_keep`, `_deleted`. Each toggle action clears the other two for that entry.
- **`StashRestoreResult`** becomes three id lists (drop the `destructive` field):
  ```
  pop_ids: list[str]     # space — restore & remove
  keep_ids: list[str]    # tab   — restore & keep
  delete_ids: list[str]  # d     — remove, no restore
  ```
- **BINDINGS**: `space → toggle_pop`, `Binding("tab", "toggle_keep", priority=True)`, `d → mark_delete`,
  `a → toggle_all` (pop variant), plus the inherited navigation/cancel bindings.
- **Actions**: rename/replace `action_toggle_row` → `action_toggle_pop`; add `action_toggle_keep`; keep
  `action_mark_delete` (no longer mode-gated); `action_toggle_all` selects pop on all selectable rows; `action_confirm`
  builds the three-list result, falling back to popping the highlighted row when nothing is marked.
- **`_stash_row_label`**: extend the marker prefix to three states (pop `✓` / keep `✚` / delete `✗`), keeping the
  fixed-width 2-column marker, the bold-preview-when-restoring and dim-strike-when-deleting treatments.
- **Title/hints**: `"Stashed prompts (N)"`; the single self-documenting hint line above.
- Update the module docstring to describe the unified per-entry model.
- Layout/CSS (`styles.tcss`) is unchanged (still title + `OptionList` + hint static).

### 2. App glue: `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`

- `action_restore_prompt_stash` (the `@` handler) → `await self._open_prompt_stash_panel()`.
- `on_prompt_input_bar_restore_requested` → `await self._open_prompt_stash_panel(bar_mode=event.mode)`.
- Rename `_open_prompt_stash_restore` → `_open_prompt_stash_panel(bar_mode=None)`: same prompt-bar guard (feedback /
  approve-prompt bars toast a no-op), same empty-store toast, same off-thread snapshot read; pushes
  `StashedPromptsModal(entries)` (no `destructive`).
- Replace `_apply_destructive_restore` + `_apply_nondestructive_load` with one `_apply_stash_restore(result)`:
  - `remove_ids = result.pop_ids + result.delete_ids`; `restore_ids = result.pop_ids + result.keep_ids`.
  - Read the snapshot off-thread → `by_id`; build `restore_entries` for `restore_ids` sorted by
    `(created_at, pane_index)` (same oldest-first ordering used today).
  - Pop `remove_ids` off-thread (single `pop_prompt_stash` call) when non-empty.
  - Load `restore_entries` into the bar via the existing `_load_restored_entries`.
  - Toast a count-aware summary via `_notify_restore_outcome` (restored = pop+keep loaded; deleted = delete_ids
    removed). Refresh the badge only when something was popped/deleted (keep-only leaves the badge intact, as the old
    non-destructive path did).

### 3. Prompt-bar dispatch + hints: `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py`

The bare `g` prefix and the `^G` prefix share `_PROMPT_G_PREFIX_BINDINGS`, `dispatch_g_prefix_key`, and
`g_prefix_hint_entries`. To make stash-restore live **only on `^G`** (not bare `g`):

- Add a `ctrl_g_only: bool = False` field to `_PromptGPrefixBinding`.
- In the table: **remove the `P` entry**; change the `p` entry to action `request_open_prompt_stash`, label method
  `_g_prefix_label_open_stash`, and `ctrl_g_only=True`.
- `dispatch_g_prefix_key(self, key, *, target_mode="normal", via_ctrl_g=False)`: skip bindings where
  `ctrl_g_only and not via_ctrl_g` (so bare `gp` returns `False` and falls through — it becomes a silent no-op,
  swallowed by the pending handler, never inserting a literal `p`).
- `g_prefix_hint_entries(self, *, via_ctrl_g=False)`: skip `ctrl_g_only` bindings unless `via_ctrl_g`.
- Replace `request_load_stash` + `request_restore_stash` with a single `request_open_prompt_stash` posting
  `RestoreRequested(self._mode)`.
- Replace the two labels with `_g_prefix_label_open_stash` (e.g. `"stashed prompts…"`); keep
  `_g_prefix_available_stash_restore` as the availability gate for the `p` hint.

### 4. Threading `via_ctrl_g` through the callers

- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py`: in both `_handle_insert_g_prefix_key` and
  `_handle_normal_g_prefix_key`, pass `via_ctrl_g=True` to `dispatch_g_prefix_key` (alongside the existing
  `target_mode`). The bare-`g` caller in `_vim_normal_pending.py` keeps the default (`via_ctrl_g=False`).
- `src/sase/ace/tui/widgets/_prompt_input_bar_g_prefix_hints.py`: `show_g_prefix_hints` already knows the surface via
  `prefix_label` (`"^G"` for the ctrl+g panels, `"g"` for bare). Call
  `self.g_prefix_hint_entries(via_ctrl_g=(prefix_label == "^G"))`. So the `p` hint shows on the `^G` panels (insert +
  normal) but not on the bare-`g` panel.

### 5. Message: `src/sase/ace/tui/widgets/_prompt_input_bar_messages.py`

- `RestoreRequested` drops the `destructive` field; it carries only `mode`. Update its docstring.

### 6. Help, catalog, and docs

- `src/sase/ace/tui/modals/help_modal/binding_common.py` — `PROMPT_INPUT_SECTION`: replace
  `("gp / gP", "Load / restore stashed prompt")` with `("Ctrl+G p / @", "Stashed prompts panel")`.
- `src/sase/ace/tui/commands/catalog.py` — keep the `restore_prompt_stash` entry (label, `Agents` category, all-tabs,
  `@` display) but update aliases from `("stash", "restore", "gP")` to drop the now-invalid `gP` (e.g.
  `("stash", "restore", "pop")`).
- The per-tab help files (`changespecs_bindings.py`, `agents_bindings.py`, `axe_bindings.py`) already list
  `@ → "Restore stashed prompt"` via `restore_prompt_stash`; the label still reads correctly (the panel's primary job is
  restoring), so they need no change. (The retired-leader `,P` cleanup and its tests are untouched.)

## Test Plan

Production behavior changes, so several tests are reworked. Focused suites:

- **`tests/ace/tui/modals/test_stashed_prompts_modal.py`** — rewrite for the unified model: `space` marks pop, `tab`
  marks keep, `d` marks delete (always available), `a` selects-all-pop; `enter` with no marks pops the highlighted row;
  `StashRestoreResult` exposes `pop_ids`/`keep_ids`/`delete_ids`; row markers render `✓`/`✚`/`✗`; remove the
  `destructive`/load-mode tests; add a test that `space` and `tab` are mutually exclusive on one entry.
- **`tests/ace/tui/actions/test_prompt_stash_restore.py`** — drop the `destructive=` parametrization; assert
  `_open_prompt_stash_panel` pushes the panel with snapshot entries; assert `_apply_stash_restore` (a) loads pop+keep
  oldest-first into the mounted/new bar, (b) pops only pop+delete ids, (c) leaves the badge untouched for a keep-only
  result, (d) toasts restored/deleted counts; keep the feedback-mode no-op and empty-store toast guards.
- **`tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py`** — remove the `gP` / `gp` / `<ctrl+g>P` tests; assert
  `<ctrl+g>p` (insert **and** normal mode) posts `RestoreRequested(mode)`; assert bare `g` then `p` posts nothing.
- **`tests/ace/tui/widgets/test_prompt_g_prefix_hints.py`** — `g_prefix_hint_entries(via_ctrl_g=True)` includes the
  single open-stash `p` entry; the default (bare) call excludes it; `P` no longer appears; dispatch:
  `dispatch_g_prefix_key("p", via_ctrl_g=True)` routes to `request_open_prompt_stash`, while
  `dispatch_g_prefix_key("p")` (bare) returns `False`.
- **`tests/test_keymaps_display_help.py`** — update the Prompt-Input assertion to the new
  `("Ctrl+G p / @", "Stashed prompts panel")` line; the global `("@", "Restore stashed prompt")` assertion stays.
- **`tests/test_command_catalog.py`** — update the alias assertion (no longer requires `"gP"`).
- **`tests/ace/tui/visual/test_ace_png_snapshots_prompt_stash.py`** — construct the modal with one row each in `_pop` /
  `_keep` / `_deleted` so all three markers render; regenerate the PNG golden with `--sase-update-visual-snapshots` and
  visually confirm the three glyphs/colors.
- The app-binding count test (`test_keymaps_app_bindings.py`, currently `97`) is **unchanged** — no app-level binding is
  added or removed. The retired-leader tests in `test_keymaps_defaults.py` / `test_keymaps_registry_loading.py` keep
  passing (only a stale code comment referencing `gp`/`gP` may be refreshed).

## Validation

Focused first:

```bash
pytest tests/ace/tui/modals/test_stashed_prompts_modal.py \
       tests/ace/tui/actions/test_prompt_stash_restore.py \
       tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py \
       tests/ace/tui/widgets/test_prompt_g_prefix_hints.py \
       tests/test_keymaps_display_help.py tests/test_command_catalog.py
just test-visual   # regenerate + verify the stashed-prompts modal PNG golden
```

Then, because the repo requires it after code changes (and the workspace may be stale):

```bash
just install
just check
```

## Design Decisions (for reviewer sign-off)

1. **Delete (`d`) is retained** in the unified panel. It is existing, useful functionality (the old destructive picker
   had it) and removing it would regress the panel into a restore-only view. This yields three indicators total, not two
   — the two new restore indicators plus the pre-existing delete indicator.
2. **`enter` with nothing marked restores + pops the highlighted row** (the conventional stash→pop quick path, matching
   the old `gP` picker). The alternative (restore + keep, or no-op) is available if you'd prefer a non-destructive
   default — easy to flip.
3. **Indicators**: `✓` violet (pop) / `✚` green (keep) / `✗` red (delete), with an ASCII `+` fallback for `✚` if the
   pinned font can't render it. Open to a different glyph for "keep" if you have a preference.
