---
create_time: 2026-06-17 10:46:38
status: done
prompt: sdd/prompts/202606/prompt_stack_ctrl_hl_focus.md
---
# Prompt Stack Ctrl+H/L Focus Keymap Plan

## Goal

Correct and simplify the prompt-stack pane keymaps after the previous reorder migration:

- Keep reorder on `Ctrl+Shift+H/L` with the intended semantic mapping:
  - `Ctrl+Shift+H` is the old `,K` behavior: move the active pane higher / earlier.
  - `Ctrl+Shift+L` is the old `,J` behavior: move the active pane lower / later.
- Move pane focus navigation from `Ctrl+Shift+K/J` to unshifted `Ctrl+H/L`:
  - `Ctrl+H` replaces `Ctrl+Shift+K`: focus the previous / higher pane.
  - `Ctrl+L` replaces `Ctrl+Shift+J`: focus the next / lower pane.

The result is a consistent H/L axis: unshifted `Ctrl+H/L` changes focus, shifted `Ctrl+Shift+H/L` reorders the active
pane.

## Current State

- `PromptTextArea._on_key()` currently handles pane focus with exact `ctrl+shift+j` / `ctrl+shift+k` matches.
  - `ctrl+shift+j` calls `PromptInputBar.focus_relative(1)`.
  - `ctrl+shift+k` calls `PromptInputBar.focus_relative(-1)`.
  - The handler works in insert and normal mode and preserves the current vim mode.
- `PromptTextArea._on_key()` currently handles pane reorder with exact `ctrl+shift+h` / `ctrl+shift+l` matches.
  - The implemented direction already matches the intended old-leader semantics: `ctrl+shift+h` uses `delta = -1`;
    `ctrl+shift+l` uses `delta = 1`.
  - Keep that mapping, but add explicit regression coverage so the direction cannot drift again.
- Prompt-local comma-leader `,J` / `,K` has already been retired. Keep it retired.
- `Ctrl+L` already has prompt-local completion behavior:
  - It accepts active file completions.
  - It accepts or synchronously builds soft xprompt / directive / argument completions.
  - If no prompt completion consumes it today, it can fall through to the app-level `dismiss_toasts` binding.
- App-level `Ctrl+L` is still `dismiss_toasts` in `src/sase/ace/tui/bindings.py`; the prompt text area should only
  consume it when it is actually acting as a prompt-stack focus key or completion key.
- `Ctrl+H` can be terminal-sensitive because some terminals historically encode Backspace as Ctrl+H. Match only
  Textual's exact `event.key == "ctrl+h"` and do not intercept `backspace`.

## Design

1. Preserve reorder behavior and make the direction explicit.
   - Leave `ctrl+shift+h -> move_active_pane(-1)` and `ctrl+shift+l -> move_active_pane(1)` intact unless inspection
     during implementation finds a contrary bug.
   - Keep reorder available in insert and normal mode, not visual mode.
   - Keep mode preservation through `move_active_pane(..., target_mode=self._vim_mode)`.
   - Keep retired `,J` / `,K` as swallowed no-ops through the existing comma-leader fallthrough behavior.

2. Replace shifted J/K pane focus with unshifted H/L pane focus.
   - Remove the prompt-local `ctrl+shift+j` / `ctrl+shift+k` focus handler from `PromptTextArea._on_key()`.
   - Add prompt-local focus handling for exact `ctrl+h` and `ctrl+l`.
   - Map `ctrl+h` to `focus_relative(-1)` and `ctrl+l` to `focus_relative(1)`.
   - Preserve the existing mode semantics: focus from insert lands in insert; focus from normal lands in normal.
   - Continue to exclude visual / visual-line mode so visual selection semantics stay untouched.

3. Resolve the `Ctrl+L` completion conflict deliberately.
   - File completion acceptance wins first when `_file_completion_active` and `event.key == "ctrl+l"`.
   - Soft completion accept-or-build wins next when `_accept_or_build_soft_completion()` returns true.
   - Only if no completion action consumes `Ctrl+L` should `Ctrl+L` act as prompt-stack focus-next.
   - This preserves the explicit `Ctrl+L` completion workflow introduced by `prompt_ctrl_l_completion.md`.
   - For multi-pane stacks, if no completion consumes `Ctrl+L`, stop/prevent the event even at the bottom edge so it
     does not dismiss toasts or bubble to unrelated app bindings.

4. Scope focus-key consumption to real multi-pane prompt stacks.
   - In a single-pane prompt bar, `Ctrl+L` should keep its current behavior: completion first, otherwise fall through to
     app-level `dismiss_toasts`.
   - In a single-pane prompt bar, do not consume exact `ctrl+h`; there is no pane to focus, and this reduces the risk of
     interfering with terminals that report Backspace-like input as Ctrl+H.
   - In a multi-pane prompt stack, consume exact `ctrl+h` / `ctrl+l` in insert and normal mode, whether or not movement
     is possible at the current edge.

5. Update discoverability and comments.
   - Change multi-pane insert and normal subtitles from `[^⇧J/K] pane` to a compact `[^H/L] pane`.
   - Keep reorder advertised as `[^⇧H/L] move`.
   - Update `PromptInputBar.focus_relative()` docstrings, `PromptInputBar` subtitle docstrings, and the normal-mode
     pending subtitle comment to describe `Ctrl+H/L` focus and `Ctrl+Shift+H/L` reorder.
   - Update the shared help modal Prompt Input section:
     - Keep `Ctrl+T / Ctrl+L` completion documentation.
     - Replace `Ctrl+Shift+J/K` pane focus with `Ctrl+H/L` pane focus.
     - Keep `Ctrl+Shift+H/L` pane reorder.
   - Do not change `src/sase/default_config.yml`; these are prompt-widget-local bindings, not configurable app keymap
     entries.
   - Do not rewrite historical SDD plans except for any new submitted plan artifact that the plan command creates.

6. Keep the TUI keypress path lightweight.
   - Reuse `PromptInputBar.focus_relative()` for focus changes.
   - Do not add disk I/O, subprocesses, JSON parsing, synchronous project scans, or new refresh paths inside `_on_key`.
   - Keep the existing in-memory focus update, active-class update, widget focus call, and coalesced height scheduling.

## Tests

Update targeted tests around the prompt stack keymaps:

- In `tests/ace/tui/widgets/test_prompt_stack_keymaps.py`:
  - Replace focus-navigation tests with `ctrl+h` / `ctrl+l`.
  - Assert `Ctrl+H` focuses the previous / higher pane in normal mode and preserves normal mode.
  - Assert `Ctrl+H` focuses the previous / higher pane in insert mode and preserves insert mode.
  - Assert `Ctrl+L` focuses the next / lower pane and clamps at the bottom edge without bubbling.
  - Assert `Ctrl+Shift+J/K` no longer move focus.
  - Keep reorder tests on `ctrl+shift+h` / `ctrl+shift+l`, with explicit direction assertions:
    - `Ctrl+Shift+H` moves the active pane higher / earlier, matching old `,K`.
    - `Ctrl+Shift+L` moves the active pane lower / later, matching old `,J`.
  - Update helper setup that currently uses `ctrl+shift+k` to focus an upper pane so it uses `ctrl+h`.
  - Add a regression proving `Ctrl+L` does not focus panes when it is consumed by completion. A focused test can
    monkeypatch the active text area's `_accept_or_build_soft_completion()` or use an existing completion fixture,
    whichever is less brittle.
  - Keep the retired `,J` / `,K` no-op test and the plain `J` line-join test.
- In `tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py`:
  - Update subtitle assertions from `[^⇧J/K] pane` to `[^H/L] pane`.
  - Keep `[^⇧H/L] move` assertions.
- In `tests/test_keymaps_display_help.py`:
  - Replace the help assertion for `Ctrl+Shift+J/K` pane focus with `Ctrl+H/L`.
  - Keep the `Ctrl+Shift+H/L` reorder assertion.
- Run any existing prompt completion tests affected by the `Ctrl+L` precedence path, especially
  `tests/ace/tui/widgets/test_prompt_live_completion.py` and representative file-completion tests if implementation
  moves the completion branch.

## Verification

Run focused tests first:

```bash
.venv/bin/pytest tests/ace/tui/widgets/test_prompt_stack_keymaps.py
.venv/bin/pytest tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py tests/test_keymaps_display_help.py
.venv/bin/pytest tests/ace/tui/widgets/test_prompt_live_completion.py
```

Then run full validation:

```bash
just check
```

## Risks and Mitigations

- `Ctrl+L` conflict with completion: completion must win before focus navigation. The new focus key should only run
  after file completion and soft completion decline the key.
- `Ctrl+L` conflict with app-level toast dismissal: in multi-pane prompt stacks, `Ctrl+L` should be consumed as pane
  focus when no completion consumes it; in single-pane prompts it should keep falling through when no completion exists.
- `Ctrl+H` terminal ambiguity: match only exact `ctrl+h`, never `backspace`, and consume it only for multi-pane stacks.
- Retiring `Ctrl+Shift+J/K`: update docs and tests so users see the new H/L focus model, and add no-movement regression
  coverage for the old shifted J/K keys.
- Subtitle density: prefer `[^H/L] pane  [^⇧H/L] move`, which keeps focus and reorder visually adjacent without adding
  prose to the live prompt footer.
