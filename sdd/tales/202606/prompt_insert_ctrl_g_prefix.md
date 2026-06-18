---
create_time: 2026-06-18 08:01:17
status: done
prompt: sdd/prompts/202606/prompt_insert_ctrl_g_prefix.md
---
# Prompt Insert-Mode Ctrl+G Prefix Plan

## Goal

Add insert-mode access to the prompt input widget's existing prompt-local normal-mode `g` prefix keymaps by using
`Ctrl+G` as the insert-mode prefix. The old direct insert-mode `Ctrl+G` editor keymap should move to `Ctrl+G g`, with
`Ctrl+G Ctrl+G` accepted as a convenience alias. The same context-aware hint panel used for normal-mode `g` should
appear above the prompt stack when the insert-mode prefix is pending.

This is TUI presentation work. It should not require Rust core changes, SASE config schema changes, or app-level keymap
changes. The app-level `Ctrl+G` keymap for "edit last VCS xprompt" remains valid outside the prompt; the focused prompt
input must still intercept `Ctrl+G` so it does not leak to the app binding.

## Current Shape

- `PromptTextArea.BINDINGS` currently binds `ctrl+g` directly to `action_open_editor()`.
- Normal-mode prompt `g` keymaps are already table-driven in
  `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py`.
- The same table feeds both `dispatch_g_prefix_key()` and `g_prefix_hint_entries()`, which is the right drift-resistant
  source of truth.
- Normal-mode `g` hints are rendered by `src/sase/ace/tui/widgets/_prompt_input_bar_g_prefix_hints.py` into the
  `#prompt-g-prefix-hints` panel mounted above `#prompt-stack`.
- Normal-mode pending `g` is owned by `_pending_keys == "g"` and routed through `_vim_normal_pending.py`; insert mode
  has no comparable prefix state today.

## Target UX

In prompt INSERT mode:

| Key                     | Behavior                                                                        |
| ----------------------- | ------------------------------------------------------------------------------- |
| `Ctrl+G g`              | Open the current prompt in `$EDITOR`; for stacked prompts, open the whole stack |
| `Ctrl+G Ctrl+G`         | Same editor action as `Ctrl+G g`                                                |
| `Ctrl+G Enter`          | Submit only the active pane, matching normal-mode `g<enter>`                    |
| `Ctrl+G j` / `Ctrl+G k` | Focus next / previous pane                                                      |
| `Ctrl+G J` / `Ctrl+G K` | Move active pane down / up                                                      |
| `Ctrl+G -`              | Add an empty bottom pane                                                        |
| `Ctrl+G =`              | Show/focus the frontmatter panel                                                |
| `Ctrl+G s` / `Ctrl+G S` | Stash active pane / all non-empty panes                                         |
| `Ctrl+G p` / `Ctrl+G P` | Load / restore stashed prompts                                                  |

Mode behavior:

- `Ctrl+G` alone starts a pending insert-mode prefix and shows hints; it does not open the editor.
- `Esc` while the insert-mode prefix is pending cancels the prefix and hides hints without switching to NORMAL mode.
- Unknown insert-mode continuations hide the hints and are swallowed as a no-op, matching normal-mode unknown `gX`
  behavior.
- Pane focus and reorder reached from insert mode should leave the target pane in INSERT mode, so the prefix is useful
  without requiring an `Esc` / `i` round trip. Normal-mode `g` behavior should remain unchanged and continue to leave
  panes in NORMAL mode.
- Feedback and approve-prompt bars should keep editor access through `Ctrl+G g` / `Ctrl+G Ctrl+G`; prompt-only stack and
  stash continuations remain unavailable there.

## Implementation Plan

1. Generalize prompt prefix dispatch just enough for insert-mode callers.
   - Extend `PromptInputBarStackActionsMixin.dispatch_g_prefix_key()` to accept a target mode, defaulting to `"normal"`.
   - Keep the existing normal-mode dispatch path unchanged by default.
   - Route pane focus/reorder through that target mode so `Ctrl+G j/k/J/K` can keep insert mode while `g j/k/J/K` keeps
     normal mode.
   - Do not add editor behavior to the stack action table; `action_open_editor()` belongs to `PromptTextArea` because it
     needs the active text and cursor location.

2. Add an insert-mode `Ctrl+G` pending-prefix state to `PromptTextArea`.
   - Add a small boolean state field such as `_insert_g_prefix_pending`.
   - In `_on_key`, handle this state before normal insert-mode submission/text insertion paths, including the `Enter`
     special case.
   - First `Ctrl+G`: stop/prevent the event, set the pending state, and ask the bar to show the prefix hints.
   - Pending `Ctrl+G` + `g` or pending `Ctrl+G` + `Ctrl+G`: clear the pending state, hide hints, and call
     `action_open_editor()`.
   - Pending `Ctrl+G` + a prompt continuation: call `dispatch_g_prefix_key(key, target_mode="insert")`, clear/hide, and
     swallow the key.
   - Pending `Ctrl+G` + `Esc`: clear/hide and stay in insert mode.
   - Pending unknown continuation: clear/hide and swallow without mutating prompt text.
   - Clear the pending prefix whenever mode changes, prompt search activates, the prompt is submitted/cancelled, or a
     structural action completes.

3. Reuse and extend the existing pretty hint panel.
   - Keep `#prompt-g-prefix-hints` and its styling/height accounting so the normal-mode panel stays visually stable.
   - Allow `show_g_prefix_hints()` to render a configurable prefix label, with normal mode using `g` and insert mode
     using a compact `^G` / `Ctrl+G` display.
   - Include the same context-aware entries returned by `g_prefix_hint_entries()` for insert mode.
   - Add an editor entry for insert mode that advertises `Ctrl+G g` and the `Ctrl+G Ctrl+G` convenience alias.
   - Include the prefix label in the hint-panel signature so switching between normal `g` hints and insert `Ctrl+G`
     hints updates the title/content correctly.

4. Remove the direct prompt editor binding.
   - Remove or neutralize the `("ctrl+g", "open_editor", ...)` entry from `PromptTextArea.BINDINGS` so the widget no
     longer advertises or dispatches direct `Ctrl+G` as the editor keymap.
   - Keep `action_open_editor()` intact for the new prefix path and for existing programmatic tests.
   - Ensure the first `Ctrl+G` is still stopped at the widget level, so the app-level `Ctrl+G` binding does not fire
     while the prompt owns focus.

5. Update user-facing prompt copy and docs.
   - Update prompt placeholders/subtitles from `[^G] editor` to the new prefixed editor form.
   - Update `docs/ace.md` INSERT-mode key table and prompt-stack section to document the `Ctrl+G` prefix equivalents.
   - Do not change `src/sase/default_config.yml`: the config-level `ctrl+g` entry is the app-level "last VCS xprompt in
     editor" keymap, not the focused prompt widget editor binding.

## Tests

Focused widget tests should cover:

- `Ctrl+G` alone in INSERT mode shows the hint panel and does not open the editor or trigger the app-level `Ctrl+G`.
- `Ctrl+G g` opens the editor for single-pane prompts.
- `Ctrl+G Ctrl+G` opens the editor convenience path.
- Stacked prompt editor behavior still posts `AllEditorRequested` through the new key sequence.
- `Ctrl+G -`, `Ctrl+G =`, `Ctrl+G Enter`, `Ctrl+G j/k`, `Ctrl+G J/K`, `Ctrl+G s/S`, and `Ctrl+G p/P` dispatch to the
  same underlying actions as normal-mode `g` continuations.
- Insert-mode pane focus/reorder continuations leave the active pane in INSERT mode; existing normal-mode tests still
  prove normal-mode continuations leave panes in NORMAL mode.
- `Esc` with a pending insert prefix hides hints and leaves `_vim_mode == "insert"`.
- Unknown `Ctrl+G z` hides hints and does not insert `z`.
- Existing normal-mode `g` hint tests, `gg`, counted `gg`, and Vim `g` operators remain unchanged.

Likely files to update or add tests in:

- `tests/ace/tui/widgets/test_prompt_g_prefix_hints.py`
- `tests/ace/tui/widgets/test_prompt_input_bar_stack_editor.py`
- `tests/ace/tui/widgets/test_prompt_stack_keymaps_add_pane.py`
- `tests/ace/tui/widgets/test_prompt_stack_keymaps_focus.py`
- `tests/ace/tui/widgets/test_prompt_stack_keymaps_reorder.py`

## Validation

After implementation:

1. Run `just install` before validation if the workspace dependencies are not current.
2. Run targeted tests:
   - `pytest tests/ace/tui/widgets/test_prompt_g_prefix_hints.py`
   - `pytest tests/ace/tui/widgets/test_prompt_input_bar_stack_editor.py`
   - `pytest tests/ace/tui/widgets/test_prompt_stack_keymaps_add_pane.py`
   - `pytest tests/ace/tui/widgets/test_prompt_stack_keymaps_focus.py`
   - `pytest tests/ace/tui/widgets/test_prompt_stack_keymaps_reorder.py`
3. Run `just check` before final response, per repo instructions for source changes.
