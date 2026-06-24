---
create_time: 2026-06-24 13:26:48
status: done
prompt: sdd/prompts/202606/swap_stash_panel_space_tab.md
---
# Plan: Swap `<space>` and `<tab>` keymaps on the prompt stash panel

## Goal

On the prompt stash panel (the `StashedPromptsModal` "Stashed prompts" picker), swap the two row-marking keys so that:

- `<tab>` marks a row **restore + pop** (✓) — the action currently bound to `<space>`.
- `<space>` marks a row **restore + keep** (+) — the action currently bound to `<tab>`.

All other behavior (`d` delete, `a` toggle-all, `enter` confirm, `esc`/`q` cancel, j/k navigation, mutual exclusivity,
bundle-row inertness, marker glyphs ✓ / + / ✗) stays exactly as it is. This is a pure key-rebinding change — no action
logic, no selection model, and no result wiring changes.

## Background / Context

The prompt stash panel is implemented entirely in the TUI layer as a Textual `ModalScreen`:

- **Panel:** `src/sase/ace/tui/modals/stashed_prompts_modal.py` (`StashedPromptsModal`).
- **Current bindings:**
  - `("space", "toggle_pop", "Restore + pop")` → `action_toggle_pop()` (✓, adds to `self._pop`).
  - `Binding("tab", "toggle_keep", "Restore + keep", priority=True)` → `action_toggle_keep()` (+, adds to `self._keep`).

### Key facts established during exploration

1. **These keys are hardcoded in the modal's `BINDINGS`, not config-driven.** `default_config.yml` only defines
   `restore_prompt_stash: "at"`, which is the _global key that opens the panel_ (`@`), not the in-panel toggles. The
   keymap registry (`keymaps/loader.py`, `keymaps/types.py`) and `bindings.py` reference only `restore_prompt_stash`
   (the open action). **No changes are needed in `default_config.yml`, the keymap registry, or `bindings.py`.**

2. **`priority=True` belongs to the `tab` key, not to the action.** Textual normally consumes `<tab>` for focus
   traversal, so the screen-level `tab` binding needs `priority=True` to win. After the swap, `priority=True` must stay
   on the `tab` binding (now `toggle_pop`). The `space` binding does not need it (space has no special focus meaning)
   and currently has none.

3. **The in-panel keys are documented only by the modal's own hint line** (`_hint_text()`), not by the `?` help modal.
   The help modal (`help_modal/binding_common.py`, `agents_bindings.py`, `changespecs_bindings.py`, `axe_bindings.py`)
   only documents the _open_ action ("Stashed prompts panel" / "Restore stashed prompt"). So no help-modal edits are
   required, and the AGENTS.md "keep the `?` help popup in sync" rule is satisfied by updating the modal's hint line.

4. **Boundary:** keybindings are presentation-only Textual state per `memory/rust_core_backend_boundary.md`, so this
   stays entirely in the Python TUI repo — no `sase-core` Rust change.

5. **`a` (toggle-all) keeps marking rows for pop.** `action_toggle_all` operates on `self._pop`. The request is to swap
   only `<space>` and `<tab>`; `a` is out of scope and intentionally remains a "select all for restore + pop" bulk
   action. (Documented here so the implementer does not "fix" it.)

## Scope of changes

### 1. Source: `src/sase/ace/tui/modals/stashed_prompts_modal.py`

- **`BINDINGS`** (currently lines ~143–144): swap the action each key triggers, keeping `priority=True` on the `tab`
  entry:
  - `<tab>` → `toggle_pop` with `priority=True` (use a `Binding(...)` so `priority` can be set).
  - `<space>` → `toggle_keep` (no priority needed).
  - Keep the binding descriptions paired with their action ("Restore + pop" stays with `toggle_pop`, "Restore + keep"
    stays with `toggle_keep").
  - Do **not** rename `action_toggle_pop` / `action_toggle_keep` — only the key→action mapping changes, so the action
    handlers and the `_pop` / `_keep` sets are untouched.

- **`_hint_text()`** (currently line ~189): update the hint so each key shows its new action + marker. The two
  key/action tokens swap while every other token and the overall layout/length stay identical (so the fixed-width modal
  still fits on one line). Target string:

  ```
  "j/k ↑/↓ navigate   space + restore+keep   tab ✓ restore+pop   "
  "d ✗ delete   a all   enter confirm   esc/q cancel"
  ```

  (`space` now pairs with `+ restore+keep`; `tab` now pairs with `✓ restore+pop`. The substrings `restore+pop`,
  `restore+keep`, and `delete` remain present, so existing substring assertions still hold.)

- **Module docstring** (currently lines ~4–6): update the prose so `<space>` marks "restore and keep" and `<tab>` marks
  "restore and pop". The `on_mount` comment ("j/k/space/a/d and enter all land on it") remains accurate and needs no
  change.

### 2. Unit test: `tests/ace/tui/modals/test_stashed_prompts_modal.py`

Update the pilot key-press tests so each test name, the pressed key, and the asserted result set all agree with the new
bindings (keep coverage of both pop and keep paths):

- `test_space_toggles_then_enter_restores_pop_set` → presses `space`; now produces **keep**. Rename to
  `test_space_toggles_then_enter_restores_keep_set` and assert `keep_ids` (was `pop_ids`).
- `test_tab_toggles_then_enter_restores_keep_set` → presses `tab`; now produces **pop**. Rename to
  `test_tab_toggles_then_enter_restores_pop_set` and assert `pop_ids` (was `keep_ids`).
- `test_space_and_tab_are_mutually_exclusive` → presses `space` then `tab` (tab last). After the swap the last press
  (`tab`) is now **pop**, so flip the assertion to `pop_ids == ["a"]`, `keep_ids == []`.
- `test_delete_wins_over_prior_pop_selection` (presses `space` then `d`) → `space` is now **keep**, so it exercises
  "delete wins over keep". Rename to `test_delete_wins_over_prior_keep_selection`.
- `test_delete_wins_over_prior_keep_selection` (presses `tab` then `d`) → `tab` is now **pop**, so it exercises "delete
  wins over pop". Rename to `test_delete_wins_over_prior_pop_selection`. (Both delete-wins tests still assert
  `delete_ids == ["a"]`, so only the names/comments swap.)
- `test_space_is_inert_for_bundle_rows` → `space` is now **keep**, which is also inert for bundle rows
  (`action_toggle_keep` honors `_is_selectable`). The test remains valid as-is; the assertion is unchanged. Optionally
  update the inline comment for accuracy.
- `test_title_and_hints_describe_unified_panel` → still passes unchanged (asserts the substrings `restore+pop`,
  `restore+keep`, `delete`, all still in the hint).
- **Module docstring** (lines ~4–5): swap the "`space` marks restore+pop, `tab` marks restore+keep" description.

### 3. Visual snapshot: `tests/ace/tui/visual/test_ace_png_snapshots_prompt_stash.py` + golden PNG

- The modal snapshot (`test_stashed_prompts_restore_modal_png_snapshot`) sets the marker sets directly
  (`modal._pop = {"recent"}`, `modal._keep = {"cleanup"}`, `modal._deleted = {"longpreview"}`) rather than via key
  presses, so the rendered markers are unchanged. **The only visual delta is the hint line at the bottom of the modal**
  (swapped space/tab labels).
- Regenerate the golden `tests/ace/tui/visual/snapshots/png/stashed_prompts_restore_modal_120x40.png` with
  `just test-visual ... --sase-update-visual-snapshots` (accept the intentional hint-text change), then visually confirm
  the diff is limited to the hint line.
- The other golden (`stashed_prompts_indicator_badge_120x40.png`) does not render the modal hint and is unaffected —
  leave it untouched.
- Update the snapshot module docstring only if it describes the key mapping (it currently describes which _entries_ get
  which markers via direct set assignment, which is unaffected — no change expected there).

## Out of scope / explicitly unchanged

- `action_toggle_all` (`a`) still marks rows for restore + pop.
- `d` delete, `enter` confirm, `esc`/`q` cancel, j/k/arrow navigation.
- Marker glyphs and styling (✓ pop, + keep, ✗ delete).
- The global open key (`@` / `restore_prompt_stash`) and everything in `default_config.yml`, `keymaps/`, and
  `bindings.py`.
- The `?` help modal (does not document in-panel keys).
- `sase-core` Rust backend (presentation-only change).

## Verification

1. `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy + tests).
2. Targeted tests:
   - `tests/ace/tui/modals/test_stashed_prompts_modal.py`
   - `tests/ace/tui/actions/test_prompt_stash_restore.py` (should pass unchanged — it drives result handlers, not keys).
3. `just test-visual` for the ACE PNG suite; regenerate the one stash-modal golden with `--sase-update-visual-snapshots`
   and confirm the diff is limited to the hint line.
4. Manual sanity check (optional): open the stash panel in `sase ace`, verify `<tab>` marks ✓ (pop) and `<space>`
   marks + (keep), and that `<tab>` is still captured by the modal (not swallowed by focus traversal).

## Risks / Notes

- **`priority=True` regression risk:** the single most important detail is keeping `priority=True` on the `tab` binding
  after the swap. Dropping it would let Textual's focus traversal eat `<tab>`, silently breaking the new restore+pop
  key. The manual check and the renamed `test_tab_*_restores_pop_set` pilot test both guard this.
- The hint string keeps the same total length (only two tokens swap), so no risk of overflowing the fixed-width (~96
  col) modal hint line.
