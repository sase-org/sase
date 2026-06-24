---
create_time: 2026-06-24 12:46:22
status: done
prompt: sdd/prompts/202606/alt_brace_two_space_padding.md
---
# Plan: Two-space padding inside `%{}` alternation braces on open

## Goal

When the user types the opening `{` of a `%{...}` alternation, expand it so the braces contain **two spaces** and place
the cursor **after the first space** (between the two spaces):

```
%{   ->   %{ ␣|␣ }      (cursor sits between the two spaces)
```

i.e. the buffer becomes `%{  }` with the cursor at the column right after the first space.

This must work in both editing surfaces that already share the alternation `|` auto-spacing behavior:

1. The ACE **prompt input widget** (Textual TUI, Python).
2. **Neovim** via the `sase-nvim` plugin.

### Hard requirement (Neovim)

In Neovim we must **not** insert the trailing `}` — other Neovim auto-pair plugins already do that. The `sase-nvim`
plugin must contribute **only the two spaces** (and the cursor placement). In the TUI we own the whole pair, so the TUI
inserts `{  }` itself.

## Why / product context

The alternation shorthand is `%{A | B | C}`. Today, typing `|` inside a live `%{...}` span inserts a padded `|`
separator and normalizes comma spacing. Opening a fresh alternation currently yields a tight `%{}` (TUI) or a bare
literal `%{` (nvim). Padding the braces on open gives the alternation room to breathe and, importantly, **composes
cleanly with the existing `|` separator** so the final result is nicely padded:

- Open `%{` → `%{  }` (cursor between the spaces).
- Type the first branch `A` → `%{ A }` (cursor after `A`, before the trailing space).
- Type `|` → existing separator logic produces `%{ A |  }`, cursor parked in the trailing gap.
- Type the second branch `B` → the gap is consumed, yielding the clean `%{ A | B }`.

(The transient double space before `}` right after typing `|` is exactly the landing pad for the next branch character;
no change to the `|` separator logic is needed.)

## Current state (research summary)

- **TUI brace pairing** is generic: typing `{` runs `plan_pair_insert` which turns `%{` into `%{}` with the cursor
  between the braces. The alternation-specific logic (the `|` separator) lives in
  `src/sase/ace/tui/widgets/_alt_syntax_editing.py`; generic auto-pairing lives in
  `src/sase/ace/tui/widgets/_paired_text_editing.py`; key dispatch is in
  `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` (`_try_prompt_text_pair_edit`). A directive-valid `%` is
  detected by the existing `_is_directive_valid_brace_opening` helper.
- **nvim** deliberately does _not_ pair braces — the `sase-nvim` README explicitly says "use your normal editor
  auto-pair plugin if you want brace pairing." The plugin's `lua/sase/alt_edit.lua` only handles the `|` separator (via
  an `InsertCharPre` autocmd). The sibling `lua/sase/xprompt_spacer.lua` demonstrates the needed pattern: **leave the
  typed character to insert natively, then `vim.schedule` a follow-up buffer edit** on the next tick.
- **No Rust core / LSP work.** The alternation editing helpers are intentionally mirrored client-side in Python and Lua;
  the xprompt LSP server does not advertise on-type formatting and is not involved in this spacing. This change follows
  that existing parallel-implementation pattern (same shape as the already-duplicated `plan_separator`), so no
  `sase-core` change is needed.

## Design

### TUI (Python)

1. Add a pure planner `plan_alt_brace_pair(text, offset)` to `_alt_syntax_editing.py`:
   - Fires **only** when the character immediately before the insertion point is a directive-valid `%` (reuse
     `_is_directive_valid_brace_opening(text, offset - 1)`), so only the alternation opener `%{` is padded and a generic
     `{` is left to the existing generic pairing.
   - Apply the same "safe following character" guard the generic pair insert uses (end-of-text or whitespace/closer) so
     we don't pad `%{word`.
   - Return a `TextEdit` that inserts `{  }` (brace, two spaces, brace) at the cursor with the cursor landing after the
     first space (`cursor = offset + 2`). The TUI owns the whole pair.
2. Wire it into `_try_prompt_text_pair_edit`: for a typed `{`, try close-skip → `plan_alt_brace_pair` → generic
   `plan_pair_insert` (alternation opener wins over generic pairing, but an existing closer under the cursor still moves
   over). The `|` path and all other characters are unchanged. The earlier `_try_jinja_auto_pair` hook is unaffected
   (its first-`{` guard does not match `%{`).

### Neovim (Lua, `sase-nvim`)

1. Add a pure planner `M.plan_brace_padding(line, offset)` to `lua/sase/alt_edit.lua`:
   - Returns `nil` unless the char before the insertion point is a directive-valid `%` (reuse the existing
     `is_directive_valid_brace_opening`), with the same safe-following-char guard as the TUI.
   - Returns a plan that inserts **only two spaces** (never a `}`) positioned right after the natively-typed `{`, with
     the cursor after the first space. (Offsets are expressed relative to the line after the native `{` insert,
     mirroring how `xprompt_spacer.lua` plans against the post-insert line.)
2. Extend the existing `InsertCharPre` handler (`on_insert_char`) to branch on the typed character:
   - `|` → unchanged (existing separator path; swallow the char and schedule the edit).
   - `{` → compute `plan_brace_padding`; if it applies, **do not** swallow the `{` (let it insert natively and let the
     user's external auto-pair plugin add the `}`), then `vim.schedule` the two-space insertion + cursor placement,
     reusing the existing `apply_plan` helper.
   - Net effect: with an external auto-pair plugin the result is `%{  }` (cursor after first space); with no auto-pair
     plugin it is `%{  ` with the same cursor — in both cases `sase-nvim` only ever adds the two spaces.

## Tests

### Python (`tests/ace/tui/widgets/test_prompt_alt_syntax_editing.py`)

- Update `test_alt_auto_pair_inserts_braces` to expect `%{  }` with the cursor after the first space (no longer `%{}`).
- Add pure-helper tests for `plan_alt_brace_pair`: directive-valid `%{` returns the `{  }` edit; a generic `{` (e.g.
  `word{`) and a `%{` followed by a non-space character return `None`.
- Add an integration test for the full compose: open `%{`, type a branch, `|`, second branch → `%{ A | B }`.
- Keep the existing generic-`{` test (`word{}` stays unpadded) and the `%{}` paired-delete tests (they operate on a
  pre-existing empty pair and are unaffected).

### Lua (`sase-nvim` `tests/alt_edit.lua`)

- Add pure-planner tests for `M.plan_brace_padding` (directive-valid `%` returns the two-space plan; non-directive and
  unsafe-following cases return `nil`).
- Update the existing "`%{` stays literal" end-to-end test: in the bare headless harness (no auto-pair plugin) `i%{` now
  yields `%{  ` with the cursor after the first space; update the assertion and comment.
- Optional stretch: an end-to-end test that installs a minimal `inoremap { {}<Left>` to simulate an external auto-pair
  plugin and asserts the full `%{  }`, if feedkeys/remap timing cooperates; otherwise the pure-planner test plus the
  bare end-to-end test provide the coverage.

## Docs

- Update the `sase-nvim` `README.md` "Alt Brace Syntax (`%{...}`)" section: typing `{` to open a `%{...}` now inserts
  two spaces between the braces (cursor after the first space), while the plugin still does **not** insert the closing
  `}` (the user's auto-pair plugin provides it).

## Edge cases / things to verify during implementation

1. **Whitespace-only alternation parsing.** Confirm that the padded-but-unfilled `%{  }` is parsed the same as the old
   empty `%{}` by `split_prompt_for_alternatives` (i.e. it must not trigger a spurious fan-out if the user opens an
   alternation and submits without filling it). Quick check: `split_prompt_for_alternatives("%{  }\nDo work")` should
   return `None`. If it does not, decide whether to trim whitespace-only branches in the parser or to gate the padding.
2. **Clean compose with `|`.** Re-confirm by typing that the open padding plus the existing `|` separator yields
   `%{ A | B }` (traced above).
3. **No regressions** for: generic `{` (not after `%`), Jinja `{{ }}`, `%{` close-skip, and `%{}` paired delete.

## Files to change

- `src/sase/ace/tui/widgets/_alt_syntax_editing.py` — new `plan_alt_brace_pair` planner.
- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` — dispatch the new planner for `{`.
- `tests/ace/tui/widgets/test_prompt_alt_syntax_editing.py` — update + add tests.
- `sase-nvim` linked repo:
  - `lua/sase/alt_edit.lua` — new `plan_brace_padding` planner + `{` branch in the `InsertCharPre` handler (two spaces
    only, no `}`).
  - `tests/alt_edit.lua` — update + add tests.
  - `README.md` — document the new open-padding behavior.

## Validation

- TUI: `just install` then `just check` (ruff + mypy + pytest) in the sase repo.
- nvim: run the headless Lua test for `alt_edit` in the `sase-nvim` linked repo
  (`nvim --headless -u NONE -c "set rtp+=." -l tests/alt_edit.lua`).
