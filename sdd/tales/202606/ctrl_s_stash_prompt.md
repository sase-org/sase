---
create_time: 2026-06-24 07:52:57
status: done
prompt: sdd/prompts/202606/ctrl_s_stash_prompt.md
---
# Plan: Rebind `<Ctrl+S>` in the prompt input widget to stash

## Goal

Make stashing prompt drafts faster by moving the stash actions onto the `<Ctrl+S>` chord in the ACE prompt input widget,
and free up the `g`-prefix `s` slot so the two stash flavors stay reachable.

### Current behavior

In the prompt input bar (`PromptTextArea` + `PromptInputBar`):

- `<Ctrl+S>` → submit the **whole stack** as one multi-prompt (`action_submit_prompt_stack` →
  `_handle_whole_stack_submission`).
- `gs` / `<Ctrl+G> s` → **stash the current/active pane** (`stash_active_pane`).
- `gS` / `<Ctrl+G> S` → **stash all panes** (`stash_all_panes`).
- `<Ctrl+G> p` / `@` → open the stashed-prompts panel (unchanged by this work).

### Target behavior

- `<Ctrl+S>` → **stash the current/active pane** (new primary stash trigger; works in insert, normal, and visual vim
  modes, prompt-mode only).
- `gs` / `<Ctrl+G> s` → **stash all panes** (the old `gS` behavior, moved here).
- `gS` / `<Ctrl+G> S` → **removed** (become harmless swallowed no-ops, falling through to vim's own `g` handling).
- `<Ctrl+S>` whole-stack submit → **removed as a direct chord**. The whole-stack submit feature is _not_ deleted: it is
  still reachable via the existing submit chooser (press `<Enter>` on a multi-pane stack → choose "Submit all" / `a`).
- `<Ctrl+G> p` / `@` → unchanged.

This satisfies the user's answers: current-pane stash on `<Ctrl+S>`; `gS`→`gs` and `<Ctrl+G> S`→`<Ctrl+G> s`
(stash-all); both stash flavors retained because the new chord only stashes the current pane.

## Design notes / decisions

- **Single canonical g-prefix table.** Both the bare-vim `g` prefix and the `<Ctrl+G>` prefix dispatch through one
  declarative table (`_PROMPT_G_PREFIX_BINDINGS` in `_prompt_input_bar_stack_actions.py`) that also feeds the hint
  panel. Changing the `s` row and dropping the `S` row updates `gs`/`gS` _and_ `<Ctrl+G> s`/`<Ctrl+G> S` together — no
  parallel edits, no drift.
- **Presentation-only / no Rust changes.** Per the core-backend boundary rule, keybindings and the g-prefix dispatch
  table are presentation-only Textual glue. Stash _persistence_ still goes through the unchanged `prompt_stash_facade`
  (Rust-backed). Verified: `sase-core` has no keymap/stash-dispatch logic to touch.
- **No `default_config.yml` change.** The prompt-local `gs`/`gS`/`<Ctrl+S>`/`<Ctrl+G>` chords are hardcoded in the
  widget, not in the configurable keymap registry. Only the unrelated app-level `@` restore key (`restore_prompt_stash`)
  lives in config, and it is unchanged.
- **Single-pane `gs`.** `stash_all_panes` is only _hinted_ when the stack has >1 pane, but dispatch does not gate on
  availability, so `gs` on a lone pane still stashes it (as a one-item "all" bundle) — identical to today's `gS` on a
  lone pane. No regression; `<Ctrl+S>` remains the advertised single-pane stash key.
- **Submit chooser keeps its `ctrl+s`.** `PromptSubmitChoiceModal` binds `ctrl+s` (and `a`) to "Submit all". That modal
  is a separate widget (out of the user's "prompt input widget" scope) and there `ctrl+s` is a natural "yes, submit all"
  affirmation. Left as-is intentionally; documented here so it is a decision, not an oversight.

## Implementation

### 1. Rebind the `<Ctrl+S>` chord — `widgets/_prompt_text_area_key_handling.py`

- In `_on_key`, replace the `event.key == "ctrl+s"` branch (today: stop/prevent + `action_submit_prompt_stack()`) with
  one that resolves the prompt bar via `_find_prompt_bar()` and calls `bar.stash_active_pane()` (no-op when no bar /
  non-prompt mode, matching the existing guard in `stash_active_pane`). Keep the branch in its current position (before
  the vim-mode branches) so the chord works in all modes. Update the inline comment from "whole-stack submit" to "stash
  the active pane".
- Remove the now-unused `action_submit_prompt_stack` entry from the `TYPE_CHECKING` stub block (the method itself stays
  — see step 3).

### 2. Move stash-all onto `s`, drop `S` — `widgets/_prompt_input_bar_stack_actions.py`

- In `_PROMPT_G_PREFIX_BINDINGS`: point the `"s"` binding at `stash_all_panes` / `_g_prefix_label_stash_all` /
  `_g_prefix_available_stash_all`, and delete the `"S"` binding row.
- Remove the now-orphaned `_g_prefix_label_stash_active` and `_g_prefix_available_stash_active` methods. Keep
  `stash_active_pane` (now called directly by `<Ctrl+S>`).
- Update docstrings: `stash_active_pane` ("the `gs` keymap" → "the `<Ctrl+S>` keymap"); `stash_all_panes` ("the `gS`
  keymap" → "the `gs` / `<Ctrl+G> s` keymap").

### 3. Documentation-only touch-ups to the submit path

- `widgets/_prompt_text_area_actions.py`: `action_submit_prompt_stack` stays (still invoked by the submit chooser's
  "all" branch in `_open_submit_choice_panel`); update its docstring to drop the `<Ctrl+S>` reference and point to the
  chooser.
- `widgets/_prompt_input_bar_actions.py`: `_handle_whole_stack_submission` docstring — change "(`^S`)" to note it's
  reached via the submit chooser.
- `widgets/_prompt_input_bar_messages.py`: `Submitted` docstring — change the `whole_stack` bullet's "(`<ctrl+s>`)" to
  the chooser.

### 4. Update user-facing hint strings — `widgets/prompt_input_bar.py`

- `insert_mode_subtitle` (multi-pane): `[^S] all` → `[^S] stash` (current pane); keep `[^G Enter] this`. Single-pane
  subtitle unchanged.
- `normal_mode_subtitle`: multi-pane `[gs/gS] stash` → `[^S/gs] stash` (current/all); single-pane `[gs] stash` →
  `[^S] stash`.
- Update both method docstrings accordingly.

### 5. Update the help modal — `modals/help_modal/binding_common.py`

In `PROMPT_INPUT_SECTION`:

- Replace `("gs / gS", "Stash current / all panes")` with two rows: `("Ctrl+S", "Stash current pane")` and
  `("gs / Ctrl+G s", "Stash all panes")`.
- Remove `("Ctrl+S", "Submit all panes (multi-agent)")` (submit-all stays covered by the existing
  `("Enter", "Submit (chooser when stacked)")` row).
- Net line count unchanged, so column split / 57-char box width are unaffected. (Per ace help rules, new descriptions
  are ≤32 chars.)

## Tests

### Behavioral tests to update (`tests/ace/tui/widgets/`)

- **`test_prompt_stack_submit_cancel.py`**
  - Module docstring: stop claiming `<Ctrl+S>` submits the whole stack.
  - `test_ctrl_s_submits_whole_stack_as_multi_prompt` → rewrite as "ctrl+s stashes the active pane" (assert a `Stashed`
    message with `source="current"`; the whole-stack submit path stays covered by the existing parametrized
    `test_submit_choice_all_submits_whole_stack`, which already exercises `a` and `ctrl+s` inside the chooser).
  - `test_ctrl_s_is_noop_in_feedback_mode` → keep, asserting no stash is posted in feedback mode.
  - Subtitle tests: `[^S] all` → `[^S] stash` (multi-pane insert); single-pane "omits send all" assertion updated to the
    new reality; single-pane normal exact string `[gs] stash` → `[^S] stash`. Rename `..._advertises_send_all` /
    `..._omits_send_all` to reflect stash.
- **`test_prompt_stash_capture.py`** — re-map key presses to the new bindings:
  - Stash-current cases now drive `<Ctrl+S>` (replacing today's `g s`), including a from-insert case (replacing
    `<Ctrl+G> s`) and the multi-pane "keep bar, remove only active" case.
  - The stash-all (`g S` / `<Ctrl+G> S`) cases become `g s` / `<Ctrl+G> s` (assertions unchanged: `source="all"`,
    frontmatter preserved, dismiss bar).
  - Feedback-mode no-op test drives `<Ctrl+S>` and `g s`.
  - Update the module docstring's `gs`/`gS` description.
- **`test_prompt_g_prefix_hints.py`**
  - Single-pane hint lists: drop the `("s", "stash this draft")` entry (stash-all is only available with >1 pane;
    current-pane stash is no longer on the g prefix).
  - Multi-pane hint lists: replace `("s", "stash this pane")` + `("S", "stash all panes")` with a single
    `("s", "stash all panes")`; fix the `keys == [...]` list to end `..., "s"`.
  - Rendered-panel substring assertions for the single-pane / `^G` cases: `gs`/`^Gs` no longer appear there — assert
    absence.
  - `test_dispatch_g_prefix_key_routes_each_continuation`: `s` now routes to `stash_all_panes`;
    `dispatch_g_prefix_key("S")` now returns `False`; update the iterated keys and the expected `calls` list.

### Help-text test (`tests/`)

- **`test_keymaps_display_help.py`**: replace the `("gs / gS", "Stash current / all panes")` assertion with assertions
  for the two new rows (`("Ctrl+S", "Stash current pane")`, `("gs / Ctrl+G s", "Stash all panes")`).

### Visual snapshot

- **`prompt_stack_g_prefix_hints_120x40.png`** renders the two-pane g-prefix hint panel, which now shows
  `s → stash all panes` and no `S` row. Regenerate the golden with the documented `--sase-update-visual-snapshots` flag
  (intentional visual change) and confirm the diff is exactly the stash-row change.

## Verification

- `just install` (ephemeral workspace), then `just check`.
- Run the prompt-stack / stash widget suites and the help-keymap test; regenerate and re-run the visual snapshot suite.
- Manual smoke in `sase ace`: confirm `<Ctrl+S>` stashes the current pane (badge increments, bar keeps remaining panes /
  dismisses when empty); `gs` and `<Ctrl+G> s` stash all and dismiss; `gS` / `<Ctrl+G> S` do nothing; `<Enter>` on a
  multi-pane stack still offers "Submit all"; `@` / `<Ctrl+G> p` still restore.

## Out of scope

- `PromptSubmitChoiceModal`'s own `ctrl+s` = "Submit all" binding (separate modal).
- The app-level `@` (`restore_prompt_stash`) keymap and stash storage/restore flow.
- Any Rust / `sase-core` changes (none required).
