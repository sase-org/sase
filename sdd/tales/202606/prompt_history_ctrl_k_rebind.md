---
create_time: 2026-06-13 11:44:15
status: done
prompt: sdd/prompts/202606/prompt_history_ctrl_k_rebind.md
---
# Plan: Fix the broken prompt-history trigger (rebind `Ctrl+.` → `Ctrl+K`)

## Problem

The `Ctrl+.` keymap added in `4e4076492 feat(ace): add prompt-input history trigger (sase-4m.3)` is supposed to open the
prompt-history modal from the prompt input bar, pre-filtered by the current single-line prompt. It works on the author's
terminal but silently fails for most users: instead of opening history, a literal `.` is inserted into the prompt.

## Root cause

The trigger is a raw key interception in `PromptTextArea._on_key` (`src/sase/ace/tui/widgets/prompt_text_area.py:306`):

```python
if event.key in {"ctrl+full_stop", "ctrl+period"}:
```

`Ctrl+.` (Ctrl + period) is **not representable in the legacy terminal control-code scheme**. The C0 control codes only
cover a fixed set of characters (`Ctrl+A`..`Ctrl+Z` → `0x01`..`0x1A`, plus `Ctrl+[ \ ] ^ _ @`). There is no control byte
for `Ctrl+.`. Terminals that do **not** implement an enhanced keyboard protocol simply send the plain `.` byte (`0x2E`)
when you press `Ctrl+.`, indistinguishable from a normal period. Textual therefore reports the key as `full_stop`, the
`_on_key` branch never matches, and the period falls through to the default handler and is inserted as text.

Only terminals that negotiate the **kitty keyboard protocol / CSI-u** (kitty, foot, Ghostty, recent WezTerm, or tmux
with `extended-keys on` passing it through) encode `Ctrl+.` as a distinct CSI-u sequence that Textual decodes to
`ctrl+full_stop`. That is why it works for the author but not in tmux-without-extended-keys, macOS Terminal.app, and
other legacy setups.

Secondary note: `"ctrl+period"` in the matched set is not a real Textual key name — it is dead code that never matches
on any terminal.

## Decision (from clarifying questions)

- **Q1 → Rebind to a portable `Ctrl+<letter>`.** Replace `Ctrl+.` entirely with a key that every terminal can encode.
  (We are _not_ keeping `Ctrl+.` or relying on enabling the kitty protocol.)
- **Q2 → `Ctrl+K`.** `Ctrl+K` maps to C0 control code `0x0B`, which every terminal emits identically. Textual decodes it
  to `ctrl+k`.

### Why `Ctrl+K` is safe inside the prompt input

`ctrl+k` is bound elsewhere, but both bindings are preempted while the prompt input is focused:

1. **App-level `jump_to_entry_forward`** (`bindings.py:22`, keymap `ctrl+k`). This binding is **non-priority**
   (`keymaps/types.py:47` → `("jump_to_entry_forward", "Forward Jump", False)`), so the focused widget gets the key
   first. `PromptTextArea._on_key` intercepts it and calls `event.stop()`, so the app-level forward-jump never fires
   while typing a prompt.
2. **Textual `TextArea`'s built-in `ctrl+k`** (`delete_to_end_of_line_or_delete_line`). The interception runs and calls
   `event.prevent_default()` before `super()._on_key`, so the built-in delete action is preempted too.

This is exactly the pattern already used for `ctrl+r`: that key is the app-level "jump back" binding, yet inside the
prompt input it is repurposed for the recursive file finder (`prompt_text_area.py:341`). `Ctrl+K` will behave the same
way. Net effect: `Ctrl+K` opens history when the prompt input is focused, and still does forward-jump everywhere else —
mirroring the existing `Ctrl+R` dual role.

**Tradeoff to confirm:** inside the prompt input, `Ctrl+K` will no longer perform TextArea's "delete to end of line".
This matches the previous model (the old `Ctrl+.` handler also intercepted unconditionally) and leaves vim-normal-mode
editing and other readline keys intact. If preserving delete-to-end-of-line is desired, the alternative is to intercept
`Ctrl+K` only when history would actually open (prompt mode + single line) and otherwise let it fall through — but the
simpler unconditional intercept is recommended for predictability.

## Changes

### Core fix

1. **`src/sase/ace/tui/widgets/prompt_text_area.py`** (~line 306): change the branch from
   `if event.key in {"ctrl+full_stop", "ctrl+period"}:` to `if event.key == "ctrl+k":`. Keep its current placement
   (before the vim visual/normal dispatch) so it works in insert, normal, and visual modes, just as `Ctrl+.` did. The
   handler still delegates to `action_open_prompt_history()`, which already guards prompt-mode + single-line and no-ops
   otherwise.

2. **`src/sase/ace/tui/widgets/prompt_input_bar.py`** (~line 114): update the placeholder hint `[^.] history` →
   `[^K] history` (non-feedback placeholder only; feedback mode has no history).

### Tests

3. **`tests/ace/tui/widgets/test_prompt_history_trigger.py`**: replace the three `pilot.press("ctrl+full_stop")` calls
   with `pilot.press("ctrl+k")`, and rename the three `test_ctrl_full_stop_*` functions to `test_ctrl_k_*`. Add a small
   regression test that pressing the literal `.` key (`pilot.press("full_stop")`) inserts a period and does **not** emit
   a `HistoryRequested` — documenting the intended legacy behavior and guarding against re-binding to an unencodable
   key.

4. **`tests/ace/tui/test_prompt_bar_history_requests.py`** (line 67): rename
   `test_ctrl_dot_history_cancel_refocuses_prompt_bar_without_unmounting` → `test_ctrl_k_history_...` (name-only; this
   test constructs the message directly and presses no key, so no behavioral change).

### Docs

5. **`docs/ace.md`**: line 1623 (`| Ctrl+. | Open prompt history… |`) and line 1831 ("Press `Ctrl+.` from the prompt
   input…") → `Ctrl+K`. Leave line 67 (`Ctrl+R / Ctrl+K | Jump back / forward in PR history`) as-is, since that
   documents the app-level jump; optionally add a one-line note that `Ctrl+K` opens prompt history while the prompt
   input is focused (parallel to `Ctrl+R`).
6. **`docs/blog/posts/prompt-widget-and-nvim.md`** (line 91): `Ctrl+.` → `Ctrl+K`.

### Out of scope / intentionally unchanged

- **Leader `,.` (`prompt_history`)** keymap (`keymaps/types.py:442`, `default_config.yml:204`, help-modal binding
  lists). This is a separate, configurable, app-level binding that opens the same modal; leader sequences do not suffer
  the `Ctrl+.` encoding problem, so it stays.
- **`default_config.yml`**: no change. The in-input trigger is a hard-coded `_on_key` interception, not a configurable
  keymap, so it has no config entry.
- **`?` help modal**: it only documents the leader `,.` binding, not the in-input `Ctrl+.`/`Ctrl+K` trigger, so no
  help-modal edit is strictly required. (Optional: add a `Ctrl+K` prompt-input entry for discoverability — verify during
  implementation.)
- **CLI `.` history argument** (`parser_commands.py`, `query_handler/special_cases.py`, `docs/configuration.md`):
  unrelated CLI-level shortcut; unchanged.

## Verification

- `just install` then `just check` (lint + mypy + tests). Per repo rules, `just install` first because workspaces are
  ephemeral.
- Run the updated `test_prompt_history_trigger.py` / `test_prompt_bar_history_requests.py` suites.
- Manual sanity in a legacy terminal (e.g. tmux without extended-keys): focus the prompt input, press `Ctrl+K` →
  prompt-history modal opens pre-filtered; typing `.` still inserts a period.
