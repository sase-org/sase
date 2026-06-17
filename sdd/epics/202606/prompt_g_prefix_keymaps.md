---
create_time: 2026-06-17 13:19:17
status: done
prompt: sdd/prompts/202606/prompt_g_prefix_keymaps.md
bead_id: sase-4s
tier: epic
---
# Prompt Input `g` Prefix Keymap Migration Plan

## Goal

Migrate the prompt input widget's recently-added prompt-local structural and stash keymaps onto a `g` prefix, remove the
prompt-local comma leader/hints, restore Vim-inspired normal-mode `J` line join, and keep the resulting UX discoverable
through a `g` prefix hint panel.

This is prompt-widget work, plus removal of the global app-leader stash restore shortcut. It should not require Rust
core API changes. Prompt-stack layout, rendering, and key handling are TUI presentation concerns and belong in this
repo.

## Target UX

Prompt input widget, in normal mode:

| New key | Replaces                | Behavior                                                                                                            |
| ------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `gj`    | bare `J`                | Focus next/lower prompt pane, cycling at edges                                                                      |
| `gk`    | bare `K`                | Focus previous/higher prompt pane, cycling at edges                                                                 |
| `gJ`    | `Down`                  | Move active prompt pane lower/later, cycling at edges                                                               |
| `gK`    | `Up`                    | Move active prompt pane higher/earlier, cycling at edges                                                            |
| `g-`    | `Ctrl+-` / `Ctrl+_`     | Add an empty bottom pane and enter insert mode                                                                      |
| `g=`    | `Ctrl+Shift+=` and `,f` | Toggle the xprompt property/frontmatter panel; if the panel owns focus, deactivate it and return to the prompt body |
| `gs`    | `,s`                    | Stash the active non-empty pane/draft                                                                               |
| `gS`    | `,S`                    | Stash all non-empty panes                                                                                           |
| `gP`    | `,P`                    | Restore chosen stash entries into the active prompt bar and remove them from the stash                              |
| `gp`    | new                     | Load/copy chosen stash entries into the active prompt bar without deleting them from the stash                      |

Other intended outcomes:

- The prompt-local comma leader and its hint widget go away. `,s`, `,S`, `,P`, and `,f` should no longer dispatch.
- The prompt `g` hint panel replaces the comma hint panel and appears when the prompt body is in normal mode with a
  pending `g` prefix.
- Existing Vim `g` commands continue to work: `gg`, counted `gg`, `ge`/`gE`, and the `gu`/`gU`/`g~` operators.
- Bare normal-mode `J` is restored as line join, including counts and dot-repeat.
- Bare normal-mode `K` should not focus panes anymore and should not leak to app-level bindings while the prompt owns
  focus.
- `gP`/`gp` are prompt-local only. The app-level `,P` restore path should be removed from default leader-mode config,
  help, footer, and command palette surfaces.
- All migrated prompt `g` commands are normal-mode prompt commands. Insert-mode users reach them through `Esc` then the
  `g` sequence; this avoids stealing literal `g` typing.

## Important Existing Surfaces

- Prompt bar widget and composition: `src/sase/ace/tui/widgets/prompt_input_bar.py`
- Prompt stack actions and current comma leader table: `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py`
- Current comma hint panel: `src/sase/ace/tui/widgets/_prompt_input_bar_leader_hints.py`
- Prompt stack rendering and height accounting: `src/sase/ace/tui/widgets/_prompt_input_bar_stack_rendering.py`
- Prompt body key handling: `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py`
- Vim normal-mode `g` pending resolution: `src/sase/ace/tui/widgets/_vim_normal_pending.py`
- Vim normal-mode motion dispatch: `src/sase/ace/tui/widgets/_vim_normal_motions.py`
- Vim normal-mode edit commands and operator execution: `src/sase/ace/tui/widgets/_vim_normal_editing.py`
  `src/sase/ace/tui/widgets/_vim_normal_operator_exec.py`
- Frontmatter/xprompt property panel: `src/sase/ace/tui/widgets/_prompt_input_bar_frontmatter.py`
  `src/sase/ace/tui/widgets/frontmatter_panel.py`
- Prompt stash app glue and modal: `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`
  `src/sase/ace/tui/modals/stashed_prompts_modal.py`
- App leader keymaps and surfaces to remove `restore_prompt_stash` from: `src/sase/default_config.yml`
  `src/sase/ace/tui/keymaps/types.py` `src/sase/ace/tui/keymaps/loader.py`
  `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py` `src/sase/ace/tui/widgets/_keybinding_modes.py`
  `src/sase/ace/tui/commands/catalog.py` `src/sase/ace/tui/modals/help_modal/*_bindings.py`

## Phase 1: Build The Prompt `g` Prefix Foundation

Owner focus: key-dispatch architecture and hint panel, with old keymaps still allowed where necessary.

Tasks:

1. Replace the prompt comma-leader metadata with prompt `g` prefix metadata.
   - Rename concepts away from "leader" where practical: `PromptGPrefixHintEntry`, `dispatch_g_prefix_key`,
     `g_prefix_hint_entries`, `show_g_prefix_hints`, `hide_g_prefix_hints`.
   - Use one declarative table for prompt-specific `g` continuations so dispatch and hints cannot drift.
   - Include entries for `j`, `k`, `J`, `K`, `-`, `=`, `s`, `S`, `p`, and `P`.

2. Integrate with existing Vim `g` pending state.
   - In `_handle_normal_pending_key`, when `pending == "g"`, let the prompt bar try prompt-specific dispatch first.
   - If the prompt bar does not handle the continuation, fall through to existing Vim behavior for `gg`, `ge`, `gE`,
     `gu`, `gU`, and `g~`.
   - Do not let an unknown `gX` sequence leave hints stuck open.

3. Replace the comma hint panel with a `g` hint panel.
   - Rename the widget id from `#prompt-leader-hints` to something like `#prompt-g-prefix-hints`.
   - Rename state fields from `_leader_hints_*` to `_g_prefix_hints_*`.
   - Update TCSS selectors and height accounting.
   - Trigger the panel from `_update_count_display()` when `self._pending_keys == "g"`, and hide it otherwise.

4. Keep hints context-aware.
   - `gj/gk/gJ/gK`: only useful for multi-pane prompt stacks.
   - `g-` and `g=`: prompt mode only.
   - `gs`: prompt mode with non-empty active pane.
   - `gS`: prompt mode, multi-pane stack with at least one non-empty pane.
   - `gp/gP`: prompt mode with stash entries available.
   - Feedback / approve-prompt bars should show no prompt `g` hints.

5. Preserve prompt focus isolation.
   - With the prompt body focused, a now-unused comma should not open app-level leader mode. It can still perform Vim
     reverse character-search repeat when `_last_char_search` exists; otherwise it should be swallowed as a prompt-local
     no-op.

Tests:

- Add/rename `tests/ace/tui/widgets/test_prompt_g_prefix_hints.py`.
- Cover hint entries for single pane, multi-pane, empty stash, non-empty stash, and feedback mode.
- Cover show/hide on `g`, second key, `Esc`, and unknown continuation.
- Cover `gg` and counted `gg` still work after the hint integration.
- Cover `gu/gU/g~` tests still pass.

Validation:

- `just install` if the workspace has not already been installed.
- `pytest tests/ace/tui/widgets/test_prompt_g_prefix_hints.py tests/test_prompt_normal_mode_motions.py tests/test_prompt_normal_mode_case_ops.py`
- `just check`

## Phase 2: Migrate Pane Navigation/Reorder And Restore Vim `J`

Owner focus: prompt-stack movement and Vim normal-mode editing behavior.

Tasks:

1. Move pane focus from bare `J/K` to `gj/gk`.
   - `gj`: call `focus_relative(+1, target_mode="normal")`.
   - `gk`: call `focus_relative(-1, target_mode="normal")`.
   - Remove the special bare normal-mode `J/K` focus block from prompt key handling.
   - Ensure bare `K` is swallowed as a prompt-local no-op so it does not bubble to app-level `K` bindings.

2. Move pane reorder from normal-mode arrows to `gJ/gK`.
   - `gJ`: call `move_active_pane(+1, target_mode="normal")`.
   - `gK`: call `move_active_pane(-1, target_mode="normal")`.
   - Remove the normal-mode `up/down` pane reorder special case so single-pane and multi-pane prompts regain normal
     TextArea arrow behavior.

3. Restore old Vim-inspired `J` line join.
   - Reintroduce the old `_join_lines(count)` helper into `_vim_normal_operator_exec.py`.
   - Re-bind bare `J` in `_vim_normal_editing.py`.
   - Restore previous join semantics: trim trailing whitespace on the current line, trim leading whitespace on the next
     line, insert one space when both sides are non-empty, handle empty next lines, support counts, and record mutation
     for dot-repeat.

4. Update user-facing prompt subtitles.
   - Normal-mode subtitle should advertise `gj/gk`, `gJ/gK`, `g-`, `g=`, `gs/gS`, and `i` as space allows.
   - Keep compact single-pane wording; do not advertise multi-pane-only commands when there is only one pane unless the
     hint panel is the intended discovery surface.

Tests:

- Rewrite `tests/ace/tui/widgets/test_prompt_stack_keymaps.py` for `gj/gk/gJ/gK`.
- Add regressions that bare `J` joins instead of focusing, and bare `K` does not focus or bubble.
- Restore `tests/test_prompt_normal_mode_join.py` to the previous positive join tests.
- Update/remove tests that asserted `J` no-op and arrow reorder.
- Keep edge cycling tests for focus and reorder.

Validation:

- `pytest tests/ace/tui/widgets/test_prompt_stack_keymaps.py tests/test_prompt_normal_mode_join.py tests/test_prompt_normal_mode_motions.py`
- `just check`

## Phase 3: Migrate Add-Pane And XPrompt Properties Panel To `g-` / `g=`

Owner focus: structural stack mutation and frontmatter panel focus/deactivation.

Tasks:

1. Move add-pane to `g-`.
   - Dispatch through the prompt `g` prefix table to `add_bottom_pane()`.
   - Remove prompt-body handling for `ctrl+minus` and `ctrl+underscore`.
   - Update tests so old Ctrl-minus paths are inert and `g-` is the supported path.

2. Move the xprompt property/frontmatter panel toggle to `g=`.
   - Dispatch body-side `g=` to `toggle_frontmatter_panel()`, not `focus_frontmatter_panel()`, so it can both open/focus
     and deactivate.
   - Remove `,f` dispatch entirely.
   - Remove prompt-body handling for `FRONTMATTER_PANEL_BODY_TOGGLE_KEYS`.
   - Update or retire `FRONTMATTER_PANEL_BODY_TOGGLE_KEYS` / `FRONTMATTER_PANEL_TOGGLE_KEYS` so the old `Ctrl+Shift+=`
     route no longer owns the behavior.

3. Make `g=` work when the property panel already owns focus.
   - Add a panel-local pending `g` sequence in `FrontmatterPanel`.
   - In panel row-navigation mode, `g` then `=` should call `deactivate()` with the same semantics the old toggle used.
   - For inline/raw editor modes, preserve literal text entry. If implementing `g=` there, buffer the pending `g` and
     replay/insert it into the focused child if the next key is not `=`.
   - Add a test for the required path: open panel with `g=`, press `g=`, verify focus returns to the previously active
     prompt pane and the panel closes or remains visible according to existing `deactivate()` semantics.

4. Clear transient completion state before these structural actions, as the old Ctrl handlers did.

Tests:

- Update `tests/ace/tui/widgets/test_frontmatter_panel.py` from comma/Ctrl cases to `g=`.
- Add old-key regressions for `,f`, `Ctrl+Shift+=`, `Ctrl+Shift+plus`, and `Ctrl+-`.
- Update prompt stack add-pane tests to `g-`.
- Confirm `g=` is no-op outside prompt mode.

Validation:

- `pytest tests/ace/tui/widgets/test_frontmatter_panel.py tests/ace/tui/widgets/test_prompt_stack_keymaps.py`
- `just check`

## Phase 4: Migrate Stash Keymaps And Add Non-Destructive `gp`

Owner focus: stash capture/restore semantics, global leader removal, and off-thread stash I/O where touched.

Tasks:

1. Move stash capture to `gs` / `gS`.
   - Dispatch through the prompt `g` prefix table.
   - Remove comma stash dispatch.
   - Keep capture semantics unchanged: `gs` captures the active pane and removes it; `gS` captures all non-empty panes
     and dismisses the bar when appropriate.

2. Move destructive restore to prompt-local `gP`.
   - `gP` should post/request a prompt-stash load in destructive mode.
   - It is only dispatched from an active prompt input widget in prompt mode.
   - It should not be reachable through app leader mode or command palette.

3. Add non-destructive stash load on `gp`.
   - Reuse the stash picker UI, but make the operation "load/copy" rather than "restore/pop".
   - Selected entries should be loaded oldest-first with the same `(created_at, pane_index)` ordering as destructive
     restore.
   - The chosen entries must remain in the stash.
   - The stash badge should remain unchanged after a pure `gp` load.
   - Prefer disabling delete marking in the non-destructive modal mode. If delete is left enabled, delete-marked rows
     must be explicit and tested separately; selected load rows still must not be deleted.

4. Make the app restore glue explicit about destructive vs non-destructive mode.
   - Add a flag or enum to `RestoreRequested` / `StashRestoreResult` / modal construction, or introduce a new message
     name if that reads cleaner.
   - For destructive `gP`, use existing `pop_prompt_stash`.
   - For non-destructive `gp`, read the snapshot and load selected entries without calling `pop_prompt_stash`.
   - Keep prompt body key handlers UI-only. Since this code path already reads/pops JSONL stash data, move new or
     touched store work off the Textual event loop with `asyncio.to_thread()` where practical, then push the modal or
     apply completion effects back on the UI thread.

5. Remove global app leader `restore_prompt_stash`.
   - Delete it from `src/sase/default_config.yml`.
   - Delete it from `LeaderModeKeymaps`.
   - Add it to `_RETIRED_LEADER_KEYS` so stale user config cannot revive it.
   - Remove dispatch from `_leader_mode.py`.
   - Remove leader footer `has_stashed_prompts` rendering and tests that expect `,P`.
   - Remove help-modal leader entries and command-palette catalog entries for `leader.restore_prompt_stash`.
   - Keep the top-bar stash badge; it still drives prompt-local hint availability for `gp/gP`.

Tests:

- Update `tests/ace/tui/widgets/test_prompt_stash_capture.py` to `gs/gS`.
- Update `tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py` to `gP` and add `gp`.
- Update `tests/ace/tui/actions/test_prompt_stash_restore.py` for destructive vs non-destructive results.
- Update `tests/ace/tui/modals/test_stashed_prompts_modal.py` for any modal mode/title/hint changes.
- Replace `tests/ace/tui/widgets/test_keybinding_footer_restore_stash.py` with a removal/regression test, or delete it
  if better covered elsewhere.
- Add keymap/default tests proving `restore_prompt_stash` is absent and stale overrides are retired.

Validation:

- `pytest tests/ace/tui/widgets/test_prompt_stash_capture.py tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py tests/ace/tui/actions/test_prompt_stash_restore.py tests/ace/tui/modals/test_stashed_prompts_modal.py tests/test_keymaps_defaults.py tests/test_keymaps_registry_loading.py tests/test_command_catalog.py tests/test_command_catalog_guards.py`
- `just check`

## Phase 5: Docs, Help, Visual Snapshots, And Final Sweep

Owner focus: user-facing surfaces and full-repo consistency.

Tasks:

1. Update help/documentation.
   - `src/sase/ace/tui/modals/help_modal/binding_common.py`: prompt input section should show `g` prefix keymaps, not
     comma/Ctrl/bare `J/K`/arrow bindings.
   - `docs/ace.md`: update prompt stack key table and stash prose:
     - `gj/gk`, `gJ/gK`, `g-`, `g=`, `gs/gS`, `gp/gP`.
     - `gP` removes selected stash entries; `gp` loads without deleting.
     - Restore no longer opens from a global `,P` when no prompt bar is active.
   - Refresh comments/docstrings that still describe comma leader, `Ctrl+-`, `Ctrl+Shift+=`, bare `J/K` pane focus, or
     arrow pane reorder.

2. Update visual coverage.
   - Rename the visual test from prompt comma-leader hints to prompt `g` prefix hints.
   - Regenerate the PNG snapshot with the new panel title/content.
   - Ensure the hint panel still contributes to prompt-bar height correctly.

3. Run a repository-wide search and fix stale references.
   - Search terms: `,s`, `,S`, `,P`, `,f`, `prompt-leader`, `leader_hints`, `Ctrl+-`, `ctrl+minus`, `Ctrl+Shift+=`,
     `ctrl+shift+equals`, `K / J`, `Up / Down`, and `restore_prompt_stash`.
   - Leave historical SDD/tale files alone unless they are current product docs or tests.

4. Final validation.
   - Run focused prompt suites first for quick signal.
   - Run visual snapshot tests if the snapshot changed.
   - Run `just check` before handoff.

Suggested focused tests:

- `pytest tests/ace/tui/widgets/test_prompt_g_prefix_hints.py`
- `pytest tests/ace/tui/widgets/test_prompt_stack_keymaps.py`
- `pytest tests/ace/tui/widgets/test_frontmatter_panel.py`
- `pytest tests/ace/tui/widgets/test_prompt_stash_capture.py`
- `pytest tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py`
- `pytest tests/ace/tui/actions/test_prompt_stash_restore.py`
- `pytest tests/test_prompt_normal_mode_join.py tests/test_prompt_normal_mode_motions.py tests/test_prompt_normal_mode_case_ops.py`
- `pytest tests/test_keymaps_defaults.py tests/test_keymaps_registry_loading.py tests/test_keymaps_display_help.py tests/test_command_catalog.py tests/test_command_catalog_guards.py`
- `pytest -m visual tests/ace/tui/visual/test_ace_png_snapshots_prompt_stack.py --sase-update-visual-snapshots` only
  when intentionally updating the prompt hint golden
- `just check`

## Risks And Guardrails

- The biggest risk is breaking existing Vim `g` behavior. Keep prompt-specific `g` continuations narrow and let existing
  Vim branches handle all other continuations.
- Do not add synchronous stash disk reads or pops directly to key handlers. UI key handling should post intent and
  return; file work should happen off-thread when this flow is touched.
- Removing global `,P` requires config, help, footer, command catalog, and stale override cleanup. Missing one of these
  will make the key appear available in one surface while not working in another.
- The `g=` panel-active path is easy to miss because focus is no longer in `PromptTextArea`. Test it through
  `FrontmatterPanel`, not only through the prompt body.
- The final implementation should preserve user edits and cursor/focus state across pane focus/reorder/add/restore just
  as the current stack model does.
