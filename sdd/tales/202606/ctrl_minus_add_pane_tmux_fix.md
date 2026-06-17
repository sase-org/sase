---
create_time: 2026-06-17 10:49:11
status: done
prompt: sdd/prompts/202606/ctrl_minus_add_pane_tmux_fix.md
---
# Plan: Fix `Ctrl+-` add-pane chord not firing (legacy/tmux terminals)

## Problem

The `Ctrl+-` keymap recently added to the prompt input widget (commit `cdc5027b2`, "migrate prompt stack add-pane to
Ctrl+-") does nothing when pressed. The shortcut is supposed to append an empty bottom pane to the prompt stack and drop
into it, replacing the retired normal-mode `-` keymap.

## Root cause (diagnosed and empirically verified)

The handler in `src/sase/ace/tui/widgets/prompt_text_area.py` (`_on_key`, ~line 412) only matches one key name:

```python
if event.key == "ctrl+minus" and self._vim_mode in {"insert", "normal"}:
```

`Ctrl+-` is only delivered to Textual as `ctrl+minus` when the Kitty keyboard protocol's CSI-u disambiguation reaches
the app end-to-end (the terminal sends `\x1b[45;5u`). That condition does **not** hold in the user's environment:

- The TUI is run inside **tmux** (`TERM=tmux-256color`, tmux 3.5a).
- `Ctrl+-` has a legacy C0 control-byte representation: `0x1f` (the "unit separator", physically shared with `Ctrl+_`
  and `Ctrl+/`). When a key has a legacy byte form, the terminal stack — tmux in particular — emits that ambiguous
  legacy byte instead of the Kitty CSI-u sequence.
- Textual maps `0x1f` to the key name `ctrl+underscore`. This is documented directly in Textual's source,
  `textual/_ansi_sequences.py`: `"\x1f": (Keys.ControlUnderscore,),  # Control-underscore (Also for Ctrl-hyphen.)`

So when the user presses `Ctrl+-`, the handler receives `event.key == "ctrl+underscore"`, the `== "ctrl+minus"` check
fails, and the event falls through — nothing happens.

Empirical confirmation via Textual's own parser (`textual.__version__ == 8.0.0`):

| Physical key           | Sequence emitted | `event.key` Textual reports |
| ---------------------- | ---------------- | --------------------------- |
| `Ctrl+-` (legacy/tmux) | `0x1f`           | `ctrl+underscore`           |
| `Ctrl+-` (Kitty CSI-u) | `\x1b[45;5u`     | `ctrl+minus`                |
| `Ctrl+Shift+J` (Kitty) | `\x1b[106;6u`    | `ctrl+shift+j`              |

### Why the sibling chords work but this one does not

The `Ctrl+Shift+J/K` and `Ctrl+Shift+H/L` chords this feature was modeled on **have no legacy control-byte form** —
`Ctrl+Shift+J` cannot collapse to anything other than the extended encoding, so the terminal/tmux is forced to send the
disambiguated CSI-u sequence and Textual reliably sees `ctrl+shift+j`. `Ctrl+-` is the only chord in the group that owns
an ambiguous legacy byte, so it is the only one that degrades to the `ctrl+underscore` legacy name. This asymmetry is
exactly what the user observed.

### Why the existing test did not catch it

`tests/ace/tui/widgets/test_prompt_stack_keymaps.py` exercises the chord with `await pilot.press("ctrl+minus")`.
Textual's `Pilot.press` synthesizes a `Key` event with that literal name and injects it **after** the terminal ANSI
parser — so the test proves the handler reacts to a key _named_ `ctrl+minus`, but never validates that a real terminal
actually emits that name. The legacy `ctrl+underscore` path is completely untested.

## Scope / boundary check

This is presentation-layer Textual key handling (which `event.key` string the widget reacts to). It does not cross the
Rust core backend boundary — no `sase-core` wire/API, binding, or domain behavior is involved. All changes stay in this
repo.

## Proposed fix

Make the add-pane handler accept the legacy alias in addition to the Kitty name, so the chord fires regardless of
whether the terminal disambiguates `Ctrl+-`:

1. **`src/sase/ace/tui/widgets/prompt_text_area.py`** — broaden the condition:

   ```python
   if event.key in ("ctrl+minus", "ctrl+underscore") and self._vim_mode in {
       "insert",
       "normal",
   }:
   ```

   - `ctrl+minus` covers Kitty-native terminals (kitty, ghostty, foot, etc.).
   - `ctrl+underscore` covers legacy / tmux terminals, where `Ctrl+-` arrives as the `0x1f` control byte. This is the
     path the user is hitting.
   - Update the explanatory comment to record _why_ both names are matched (the `0x1f` legacy collapse and Textual's
     `ctrl+underscore` mapping), replacing the current comment's claim that "Textual normalizes `-` to `minus`", which
     is only true under full Kitty disambiguation.

2. **Document and accept the side effect.** Because `Ctrl+-`, `Ctrl+_`, and `Ctrl+/` all collapse to the same `0x1f`
   byte in legacy mode, binding `ctrl+underscore` means those three are physically indistinguishable there and will all
   add a pane. This is unavoidable in legacy terminals (the bytes are identical) and harmless — none of those chords has
   a competing binding in the prompt text area. Under the Kitty protocol they remain distinct (`ctrl+minus` /
   `ctrl+underscore` / `ctrl+slash`) and only the first two trigger add-pane, which is acceptable. A short note in the
   comment captures this.

3. **Regression tests** in `tests/ace/tui/widgets/test_prompt_stack_keymaps.py`:
   - Add `ctrl+underscore` variants of the existing add-pane tests (`test_ctrl_minus_adds_bottom_pane_from_normal` /
     `..._from_insert`) asserting the legacy key name also appends a pane and lands in it in insert mode. This directly
     guards the bug.
   - Keep the existing `ctrl+minus` tests so both terminal paths are covered.
   - Optionally parametrize the two existing add-pane tests over `("ctrl+minus", "ctrl+underscore")` rather than
     duplicating bodies, to keep the file tidy.
   - Add one small, explicit assertion (a parser-level check or an inline comment with a citation) recording that a real
     terminal emits `ctrl+underscore` for `Ctrl+-` via `0x1f`, so the rationale for the second key name is not lost.
     Prefer a comment + citation over asserting against Textual internals to avoid brittleness across Textual upgrades.

## Out of scope / no change needed

- **Help modal & subtitles.** They display `^-` / `[^-] add`, which is the correct label for the physical key the user
  presses. No user-facing relabeling is required.
- **`Ctrl+Shift+*` chords.** They have no legacy byte form and already work; they do not need the alias treatment.
- **Other prompt-area Ctrl chords** (`ctrl+s`, `ctrl+c`, `ctrl+k`, `ctrl+j`). These are `Ctrl+letter` combos whose
  legacy control codes are their _intended_ encodings, so they are unaffected. `ctrl+minus` was the only ambiguous
  `Ctrl+symbol` chord in the group.
- **`sase-core`.** No backend changes (see boundary check above).

## Verification

- `just install` (ephemeral workspace may have stale deps), then `just check`.
- New + existing keymap tests pass (`tests/ace/tui/widgets/test_prompt_stack_keymaps.py`).
- Manual confirmation in the user's real environment (inside tmux): launch `sase ace`, open a prompt, press `Ctrl+-` in
  both insert and normal mode, and confirm a new bottom pane is appended and focused in insert mode.
