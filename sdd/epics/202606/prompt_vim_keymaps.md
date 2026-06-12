---
create_time: 2026-06-12 12:48:38
status: wip
prompt: sdd/prompts/202606/prompt_vim_keymaps.md
bead_id: sase-4l
tier: epic
---
# Plan: Fill in Missing Vim Keymaps in the Prompt Input Widget

## Product Context

The `sase ace` prompt input widget (`src/sase/ace/tui/widgets/prompt_text_area.py`) has a vim-style NORMAL mode
implemented across three modules:

- `src/sase/ace/tui/widgets/_vim_normal.py` — NORMAL-mode key dispatch (`VimNormalModeMixin`)
- `src/sase/ace/tui/widgets/_vim_normal_ops.py` — operator execution, dot-repeat, count/pending-state helpers
  (`VimNormalOpsMixin`)
- `src/sase/ace/tui/widgets/_vim_motions.py` — pure motion/text-object finder functions

An audit of this code against real Vim found that the basics are solid (motions
`h j k l w W b B e E 0 $ ^ gg G f F t T ; ,`, operators `d`/`c` with counts and `iw/iW/aw/aW/ae` text objects,
`D C x s ~ J`, dot-repeat, undo, count prefixes), but several high-value Vim capabilities are missing entirely. Most
notably **you cannot copy prompt text without deleting it** (no `y`), **you cannot paste in NORMAL mode** (no `p`/`P` —
even though `docs/ace.md` already documents `p` as existing, which is a doc/code mismatch), and **there is no visual
mode**.

This plan implements the missing functionality in six phases. Each phase is a coherent, independently shippable feature
set that will be completed by a distinct agent instance.

## Audit Findings

### Missing features worth implementing (in scope)

1. **Yank + registers + paste** — `y` operator (with all existing motions/text objects), `yy`, `Y`, `p`, `P`, with
   counts. Highest-value gap: copying text out of (and within) the prompt currently requires deleting it.
2. **Visual mode** — `v` (charwise) and `V` (linewise) selection with motions, then `d`/`x`/`c`/`y`/`p` on the
   selection, plus `o` (swap ends). Second-highest-value gap; Textual's `TextArea` already has native selection support
   to build on.
3. **Quote/bracket text objects** — `i"/a"`, `i'/a'`, `` i`/a` ``, `i(/a(` (+ `ib/ab`), `i[/a[`, `i{/a{` (+ `iB/aB`),
   `i</a<`. Prompts are full of quoted strings, file paths, and code; `ci"`, `da(` etc. are among the most-used vim
   commands.
4. **`%` matching-bracket motion** — jump between matching `()`, `[]`, `{}`; works with operators (`d%`).
5. **Redo** — `Ctrl+R` in NORMAL mode (undo `u` exists; redo is missing). No conflict: the existing `Ctrl+R` recursive
   file finder binding is INSERT-mode-only.
6. **`r{char}`** — replace character(s) under cursor, with count support; dot-repeatable.
7. **`X`** (delete char before cursor) and **`S`** (synonym for `cc`).
8. **`ge`/`gE`** — backward word/WORD end motions.
9. **Paragraph motions `{`/`}`** and **`ip`/`ap` text objects** — useful for multi-paragraph prose prompts.
10. **Indent operators** — `>>`/`<<` with counts, and `>`/`<` in visual mode (markdown-friendly 2-space unit).
11. **Case operators** — `gu`/`gU`/`g~` with motions and text objects, line forms (`guu`/`gUU`/`g~~`), and visual-mode
    `u`/`U`/`~`.

### Fidelity bugs found (in scope)

- **`cw`/`cW` behaves incorrectly**: in Vim, `cw` on a non-blank character acts like `ce` (it does not consume the
  trailing whitespace before the next word). The current implementation reuses the `w` motion verbatim, so `cw` eats
  trailing whitespace. Fix to match Vim.
- **`docs/ace.md` documents `p` (Paste) as an existing NORMAL-mode command, but it is not implemented.** Phase 1 makes
  the documentation true.

### Considered and deliberately excluded (out of scope)

- **Named registers (`"a`–`"z`), marks, macros (`q`), `/`-search, `R` replace mode, `H/M/L`, `zz/zt/zb`, jumplist
  (`Ctrl+O`/`Ctrl+I`)** — power features whose payoff doesn't justify their complexity in a prompt input widget that
  typically holds a few lines to a few paragraphs of text. `f/F/t/T` + word motions cover in-buffer navigation at this
  scale.
- **`gj`/`gk` display-line motions** — potentially nice for soft-wrapped prose, but requires investigation of Textual's
  wrapped-line navigator; not worth blocking a phase on. May be revisited later.
- **Counts on insert commands (`3ifoo<Esc>`), `gi`, `Ctrl+E`/`Ctrl+Y` scrolling** — marginal value; `Ctrl+Y` is already
  taken by the workflow-YAML editor binding.

## Cross-Cutting Engineering Constraints (apply to every phase)

- **Read `memory/long/tui_perf.md` first** (via the `/sase_memory_read` skill / `sase memory read`) — all of this code
  runs in per-keystroke handlers on the Textual event loop. New key handling must be pure in-memory work. The one
  allowed exception is the _existing_ synchronous `copy_to_system_clipboard()` mirroring pattern already used by
  `d`/`c`. **Paste must never shell out to read the system clipboard** — it reads the internal register only (see Phase
  1).
- **Module layout**: don't grow `_vim_normal.py` unboundedly. New machinery goes in new sibling modules following the
  existing mixin/helper pattern (e.g. `_vim_registers.py`, `_vim_visual.py`, `_vim_text_objects.py`), with pure finder
  functions kept separate from key-dispatch code so they are unit testable.
- **Dot-repeat**: every new mutating command must integrate with the existing `_mutation_key_buffer` /
  `_record_mutation()` dot-repeat machinery the way `d`/`c`/`~`/`J` do (visual-mode operations may be exempt if faithful
  repeat semantics prove disproportionate — document the limitation if so).
- **Counts**: every new motion/operator/command accepts the numeric count prefix where Vim does, including
  operator-count × motion-count multiplication via `_consume_pending_operator()`.
- **Mode/pending-state indicator**: keep the border title (`[NORMAL]`, and new `[VISUAL]`/`[V-LINE]`) and the
  pending-operator subtitle (`_update_count_display()`) accurate for all new operators and pending states (e.g. pending
  `y`, `r`, `gu`).
- **Tests**: use the `PromptPage` harness from `sase.ace.testing`, in per-feature files following the existing
  `tests/test_prompt_normal_mode_<feature>.py` naming convention. Cover counts, operator composition, edge cases (empty
  buffer, single line, start/end of buffer, cursor at end of line), and dot-repeat where applicable.
- **Docs**: update the "NORMAL Mode" section of `docs/ace.md` (motions/operators/other-commands tables) in the same
  phase that ships the feature.
- **Normal-mode cursor convention**: the existing implementation allows the cursor at `col == len(line)` in NORMAL mode
  (unlike real Vim's clamp). Preserve this convention; do not introduce clamping.
- **No config changes**: vim-mode keys are intentionally hardcoded in the widget, not in `src/sase/default_config.yml`.
- **Finish with `just install` then `just check`** before declaring the phase done.

## Phases

### Phase 1 — Vim register, yank operator, and paste (`y`, `yy`, `Y`, `p`, `P`)

The foundation phase. Introduce an internal "unnamed register" (`_vim_registers.py`): a `(text, kind)` pair where `kind`
is `charwise` or `linewise`, stored on the widget.

- All existing register-writing operations (`d`, `c`, `x`, `s`, `D`, `C`, `dd`, `cc`, …) populate the register with the
  correct kind (linewise for `dd`/linewise operators, charwise otherwise) _in addition to_ the existing system-clipboard
  mirroring.
- `y` joins `d`/`c` as a first-class operator in the operator-pending framework: `y{motion}` for every motion that `d`
  supports today, `yy` (linewise, via operator doubling), `Y` (= `yy`, Vim semantics), `y` + text objects (`yiw`, `yaw`,
  `yae`, …). Yank does not modify the buffer, leaves the cursor per Vim (start of the yanked region for charwise;
  unmoved for `yy`), and mirrors to the system clipboard.
- `p`/`P` paste from the internal register with count support: charwise pastes after/before the cursor; linewise pastes
  open a new line below/above and place the cursor on the first non-blank of the pasted text. Paste is dot-repeatable
  and recorded as a mutation. Paste must be undoable as a single `u` step.
- Generalize `_execute_charwise_operator`/`_execute_linewise_operator` to accept the new non-deleting operator cleanly
  (this generalization is what Phases 2 and 6 build on).
- Fix `docs/ace.md`: the `p` row becomes true; add `y`/`yy`/`Y`/`P` rows.
- Tests: `tests/test_prompt_normal_mode_yank_paste.py`.

### Phase 2 — Visual mode (`v`, `V`) — depends on Phase 1

Add charwise visual (`v`) and linewise visual (`V`) modes in a new `_vim_visual.py` mixin, built on Textual `TextArea`'s
native selection.

- Entering: `v`/`V` from NORMAL mode anchor the selection at the cursor; border title shows `[VISUAL]` / `[V-LINE]`.
  `v`/`V` inside visual mode switch kinds or exit per Vim; `Escape` returns to NORMAL mode.
- Motions: all existing NORMAL-mode motions (`h j k l w W b B e E ge-family later, 0 $ ^ gg G f F t T ; ,`, counts)
  extend the selection. Text objects (`iw`, `aw`, `iW`, `aW`, `ae`) select their range.
- Operators on the selection: `d`/`x` (delete), `c`/`s` (change), `y` (yank), `p` (replace selection with register
  contents), `~` (toggle case). All write the register with the correct kind (linewise in V-LINE). After an operator,
  return to NORMAL mode (or INSERT for `c`) with Vim cursor placement.
- `o` swaps the anchor and cursor ends of the selection.
- V-LINE operations are linewise: whole lines deleted/yanked regardless of column.
- Tests: `tests/test_prompt_visual_mode.py` (+ a second file split if it grows large, e.g.
  `tests/test_prompt_visual_mode_operators.py`).
- Docs: new "Visual Mode" subsection in `docs/ace.md`.

### Phase 3 — Quote/bracket text objects and `%` motion — depends on Phase 2

New pure finders in `_vim_text_objects.py` (or extend `_vim_motions.py` if cleaner), wired into both operator-pending
mode and visual mode.

- Quote objects (single-line, per Vim): `i"`, `a"`, `i'`, `a'`, `` i` ``, `` a` ``. `a` forms include trailing (else
  leading) whitespace per Vim. When the cursor is not inside quotes, search forward on the line per Vim.
- Bracket objects (multiline, nesting-aware): `i(`/`a(` (+ aliases `ib`/`ab`), `i[`/`a[`, `i{`/`a{` (+ aliases
  `iB`/`aB`), `i<`/`a<`. Find the innermost enclosing pair around the cursor, honoring nested pairs.
- These compose with `d`, `c`, `y` in operator-pending mode and select the range in visual mode (`ci"`, `da(`, `yi{`,
  `vi(`, …).
- `%` motion: from a bracket character (or the first bracket at/after the cursor on the line, per Vim), jump to its
  match across lines; inclusive when used with operators (`d%`).
- Tests: `tests/test_prompt_normal_mode_quote_bracket_objects.py`, `tests/test_prompt_normal_mode_percent.py`.
- Docs: extend the text-objects/motions tables.

### Phase 4 — Fidelity fixes and small commands (`cw`, `r`, redo, `X`, `S`, `ge`, `gE`) — independent

A pack of small, high-frequency improvements; no dependency on Phases 1–3 (rebase-light by design).

- **`cw`/`cW` Vim-compat fix**: when the cursor is on a non-blank character, `cw` behaves like `ce` (`cW` like `cE`) —
  do not consume whitespace before the next word. `dw` keeps its current (correct) behavior. Counts behave per Vim
  (`2cw` ≈ `2ce`).
- **`r{char}`**: pending-key replace. `r` waits for the next character (subtitle indicates pending state, like `f`);
  `3rx` replaces 3 chars with `x`; fails silently (no-op) if fewer than count chars remain on the line; `r<Enter>` need
  not be supported. Dot-repeatable.
- **Redo**: `Ctrl+R` in NORMAL mode calls the TextArea redo machinery (mirror of how `u` wraps `undo()`).
- **`X`**: delete count chars before the cursor (charwise, register-writing).
- **`S`**: synonym for `cc` (with count = `<count>cc`).
- **`ge`/`gE`**: backward word/WORD-end motions via the existing `g`-pending-key mechanism; work with operators
  (inclusive).
- Tests: `tests/test_prompt_normal_mode_small_commands.py` (and extend the existing change/motion test files where the
  `cw` fix belongs).
- Docs: update tables; document the `cw` semantics.

### Phase 5 — Paragraph motions and text objects (`{`, `}`, `ip`, `ap`) — visual wiring depends on Phase 2

- `{`/`}` motions: move to the previous/next blank line (Vim paragraph boundaries), with counts; exclusive when used
  with operators (`d}` deletes up to, not including, the blank line); usable in visual mode.
- `ip`/`ap` text objects: inner paragraph (the contiguous non-blank block, or blank block when on a blank line) and
  a-paragraph (plus trailing — else leading — blank lines). Linewise when used with operators (`dip`, `yap`) and in
  visual mode (`vip` extends linewise-style per Vim is acceptable to approximate as selecting whole lines).
- Tests: `tests/test_prompt_normal_mode_paragraphs.py`.
- Docs: extend motions/text-objects tables.

### Phase 6 — Indent and case operators (`>>`, `<<`, visual `>`/`<`, `gu`, `gU`, `g~`) — depends on Phases 1–2

- **Indent**: `>>`/`<<` indent/dedent the current line (count = N lines) by a fixed 2-space unit (markdown-friendly);
  `>`/`<` with linewise motions/text objects (`>j`, `>ip`) and in visual mode (indent the selected lines, exit visual
  per Vim). Dedent removes up to one unit of leading whitespace. Dot-repeatable.
- **Case operators**: `gu` (lowercase), `gU` (uppercase), `g~` (toggle) as operators taking motions and text objects
  (`guiw`, `gUae`, `g~$`), with line forms `guu`/`gUU`/`g~~`; extends the existing `g` pending-key handling into proper
  multi-key operator state. In visual mode: `u`/`U`/`~` apply to the selection. Dot-repeatable.
- Tests: `tests/test_prompt_normal_mode_indent.py`, `tests/test_prompt_normal_mode_case_ops.py`, visual variants in the
  visual-mode test files.
- Docs: extend operator tables; document the 2-space indent unit.

## Phase Ordering / Dependency Summary

```
Phase 1 (yank/registers/paste)  ──►  Phase 2 (visual mode)  ──►  Phase 3 (quote/bracket objects, %)
                                            │
                                            ├──►  Phase 5 (paragraphs — visual wiring only)
                                            └──►  Phase 6 (indent + case operators)
Phase 4 (fidelity & small commands) — independent, can run any time
```

Recommended execution order: 1, 2, 3, 4, 5, 6 (4 may be parallelized with 2/3 if desired).

## Verification

Each phase: targeted pytest files above + the full `just check` gate (lint, mypy, fast test suite including PNG visual
snapshots). The vim-mode features have no disk/subprocess work on the keypress path (other than the pre-existing
clipboard mirroring), so no TUI perf benchmarks should regress; if any phase touches rendering (visual-mode selection
styling), sanity-check with `SASE_TUI_PERF=1` per `memory/long/tui_perf.md`.
