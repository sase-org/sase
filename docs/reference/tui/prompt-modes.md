---
title: Prompt modes
description: NORMAL and Visual mode keys for the sase TUI prompt input widget.
---

# Prompt modes

This page lists NORMAL and Visual mode keys for the sase TUI prompt input widget.

## NORMAL Mode

Press `Escape` or `Ctrl+]` in INSERT mode to enter vim-style NORMAL mode. `Ctrl+]` is
equivalent but avoids the terminal escape-sequence ambiguity that can swallow fast
following keys after `Escape` / `Ctrl+[`. The border title shows `[NORMAL]` and line
numbers switch to relative numbering (current line shows absolute, others show offset).

### Motions

| Key               | Action                             |
| ----------------- | ---------------------------------- |
| `h` / `l`         | Move left / right                  |
| `j` / `k`         | Move down / up (actual lines)      |
| `w` / `W`         | Next word / WORD start             |
| `e` / `E`         | Next word / WORD end               |
| `b` / `B`         | Previous word / WORD start         |
| `ge` / `gE`       | Previous word / WORD end           |
| `f{c}` / `F{c}`   | Find char forward / backward       |
| `t{c}` / `T{c}`   | Till char forward / backward       |
| `;` / `,`         | Repeat / reverse last f/F/t/T      |
| `%`               | Matching bracket                   |
| `0` / `$`         | Line start / end                   |
| `^`               | First non-blank character          |
| `{` / `}`         | Previous / next paragraph boundary |
| `gg` / `G`        | Top / bottom of document           |
| `Ctrl+D`/`Ctrl+U` | Half-page down / up                |

All motions accept a numeric count prefix (e.g., `3j` moves down 3 lines).

### Operators

| Key   | Action                                                                                       |
| ----- | -------------------------------------------------------------------------------------------- |
| `d`   | Delete (takes a motion, e.g. `dw`); copies to clipboard                                      |
| `c`   | Change (takes a motion, e.g. `cw`); `cw`/`cW` stop at the word/WORD end; copies to clipboard |
| `y`   | Yank (takes a motion, e.g. `yw`); copies to clipboard                                        |
| `>`   | Indent lines covered by a motion by two spaces                                               |
| `<`   | Dedent lines covered by a motion by up to two spaces                                         |
| `gu`  | Lowercase text covered by a motion or text object                                            |
| `gU`  | Uppercase text covered by a motion or text object                                            |
| `g~`  | Toggle case for text covered by a motion or text object                                      |
| `D`   | Delete to end of line                                                                        |
| `C`   | Change to end of line                                                                        |
| `S`   | Change entire line                                                                           |
| `Y`   | Yank from the cursor to end of line (charwise, like `y$`)                                    |
| `dd`  | Delete entire line                                                                           |
| `cc`  | Change entire line                                                                           |
| `yy`  | Yank entire line                                                                             |
| `>>`  | Indent current line; count indents multiple lines                                            |
| `<<`  | Dedent current line; count dedents multiple lines                                            |
| `guu` | Lowercase current line; count lowercases multiple lines                                      |
| `gUU` | Uppercase current line; count uppercases multiple lines                                      |
| `g~~` | Toggle case on current line; count toggles multiple lines                                    |
| `dae` | Delete entire buffer (copies to clipboard)                                                   |
| `cae` | Change entire buffer (copies to clipboard)                                                   |
| `yae` | Yank entire buffer (copies to clipboard)                                                     |

Vim-surround commands are also available in NORMAL mode: `ys{motion}{delimiter}` wraps a
motion or text object, `yss{delimiter}` wraps the current line, `ds{delimiter}` removes
the nearest matching surround, and `cs{old}{new}` replaces it. Quotes and backticks pair
with themselves; either side of `()`, `[]`, `{}`, or `<>` selects the matching pair,
with `b` aliasing parentheses and `B` aliasing braces. Other single characters pair with
themselves. For example, `ysiw)` changes `word` to `(word)`, and `cs)]` changes the
parentheses around the cursor to brackets. A count on the `ys` motion expands its
target; a count before `ds` or `cs` selects a farther enclosing pair. Successful edits
are repeatable with `.`.

### Text Objects

Text objects compose with `d`, `c`, and `y`.

| Key                  | Action                                                  |
| -------------------- | ------------------------------------------------------- |
| `iw` / `aw`          | Inner / a word                                          |
| `iW` / `aW`          | Inner / a WORD                                          |
| `i"` / `a"`          | Inner / a double-quoted string                          |
| `i'` / `a'`          | Inner / a single-quoted string                          |
| `` i` `` / `` a` ``  | Inner / a backtick-quoted string                        |
| `i(`/`a(`, `ib`/`ab` | Inner / a parenthesized block                           |
| `i[` / `a[`          | Inner / a square-bracket block                          |
| `i{`/`a{`, `iB`/`aB` | Inner / a brace block                                   |
| `i<` / `a<`          | Inner / an angle-bracket block                          |
| `ip` / `ap`          | Inner / a paragraph; `ap` includes adjacent blank lines |
| `ae`                 | Entire buffer                                           |

### Operator + Search

Any operator followed by `/` or `?` acts up to a search match: `d/foo<Enter>` deletes
from the cursor up to, but not including, the next `foo`, and `d?foo<Enter>` deletes
back to the previous one. It works with `d`, `c`, `y`, `gu`, `gU`, `g~`, `>`, `<`, and
`ys` (the delimiter follows).

| Key                          | Action                                             |
| ---------------------------- | -------------------------------------------------- |
| `{op}/{pat}<Enter>`          | Operate forward up to the match                    |
| `{op}?{pat}<Enter>`          | Operate backward back to the match                 |
| `{op}n` / `{op}N`            | Operate to the next / previous shared-search match |
| `2{op}/{pat}`, `{op}2/{pat}` | Count selects the N-th match (operator × motion)   |

While you type, the exact region is tinted in the operator's color: red with
strikethrough for `d`/`c`, green for `y`, and the theme's secondary color for the
transform family. A backward `d?foo` shows the gold landing match struck through (it
will be deleted), while a forward `d/foo` leaves it intact. The panel says in words what
Enter will do, such as `delete 42 chars · 3 lines`, plus the pane-local count (for
example `2/3`).

The motion never wraps and stays inside the active pane: `d/` only reaches forward and
`d?` only reaches backward. A match starting exactly at the cursor is skipped. When
there is no target, Enter changes nothing and reports `pattern not found`,
`no match after cursor · 2 before` (or `no match before cursor · 2 after`), or
`only 1 match after cursor` when a count asks for too many. `Esc` or `Ctrl+C` restores
everything.

The motion is exclusive, with Vim's column-0 adjustment: when the range ends at column 0
of a later row, it becomes linewise if the start is at or before the first non-blank
column (for example deleting whole lines), and otherwise stops at the end of the
previous row. Matching is the same smartcase literal matching `/` uses, and a successful
operator search records the query so `n` / `N` continue from it.

`.` repeats the same operator, query, direction, and count from the current cursor; a
count on `.` replaces the recorded count, and `c` replays its inserted text. One `u`
restores the whole edit. Not supported: regex, `/e` offsets, empty `d/<Enter>` reusing
the last pattern (it cancels), counted plain `3/`, VISUAL `/`, `d*`/`d#`/`gn`,
cross-pane operators, and wrapscan for operators.

### Other Commands

| Key         | Action                                                                                                |
| ----------- | ----------------------------------------------------------------------------------------------------- |
| `i`         | Enter INSERT mode; inserted text is repeatable with `.`                                               |
| `v`         | Enter charwise VISUAL mode                                                                            |
| `V`         | Enter linewise V-LINE mode                                                                            |
| `a`         | Append after cursor; inserted text is repeatable with `.`                                             |
| `A`         | Append at end of line; inserted text is repeatable with `.`                                           |
| `I`         | Insert at line start; inserted text is repeatable with `.`                                            |
| `o`         | Open below; prompt bullets and ordered items auto-continue, and inserted text repeats with `.`        |
| `O`         | Open above; prompt bullets and ordered items auto-continue, and inserted text repeats with `.`        |
| `[<Space>`  | Insert blank line(s) above current line without leaving NORMAL mode                                   |
| `]<Space>`  | Insert blank line(s) below current line without leaving NORMAL mode                                   |
| `u`         | Undo                                                                                                  |
| `Ctrl+R`    | Redo                                                                                                  |
| `Ctrl+A`    | Increment the number at/after cursor, wrapping to the prompt top (supports count and `.`)             |
| `Ctrl+X`    | Decrement the number at/after cursor, wrapping to the prompt top (supports count and `.`)             |
| `x`         | Delete character                                                                                      |
| `X`         | Delete character before cursor                                                                        |
| `r{c}`      | Replace character(s) at cursor (supports count: `3rx`)                                                |
| `p`         | Paste after cursor / below line from the internal register                                            |
| `P`         | Paste before cursor / above line from the internal register                                           |
| `~`         | Toggle case of character(s) at cursor (supports count: `5~`)                                          |
| `.`         | Repeat last mutation, including inserted text; a count replaces the recorded count                    |
| `J`         | Join current line with next, removing a pulled-up prompt `- ` or `<N>.` marker (supports count: `5J`) |
| `K`         | Preview the macro, workflow, skill, file, glossary term, repo name, or plain word under the cursor    |
| `Ctrl+]`    | Jump to the macro/workflow/skill/glossary definition, file, or repo checkout under the cursor         |
| `/` / `?`   | Search forward / backward in the current prompt pane; after an operator, acts up to the match         |
| `n` / `N`   | Repeat the last confirmed search in its original / opposite direction                                 |
| `*` / `#`   | Search forward / backward for the whole word under the cursor                                         |
| `g*` / `g#` | Like `*` / `#`, but also matches the word as a substring                                              |

In prompt panes, `o` and `O` continue the containing hyphen bullet or ordered item below
or above at the same indentation, including when the cursor is on a physical
continuation line produced by Prettier wrapping. Non-list lines retain ordinary bare
open-line behavior. For an ordered item, `O` on the marker row takes that item's own
number, `O` on a line the item owns takes the next number (the new marker lands after
that item's marker), and `o` always takes the next number; the surrounding run is
renumbered either way. Prompt `J` removes a supported `- ` or `<N>.` marker when joining
onto a nonblank current line, renumbering the run an ordered item left behind; a blank
current line keeps the marker, and non-prompt editors retain vanilla `J` behavior.

For `Ctrl+]`, sase's TUI opens the target directly in `$EDITOR` when there is only one
available action. Inside tmux, or for loadable Markdown macro definitions, it can show a
small chooser for editor, tmux-pane, or load-into-prompt actions. Glossary jumps use the
same flow, targeting the owning project's `sase/sase.yml` `definition` scalar.

The border subtitle shows pending operators and counts (e.g., `2d` when a delete with
count 2 is pending).

Search previews matching text as you type. `Enter` confirms the query, while `Esc` or
`Ctrl+C` cancels and restores the original cursor. The last confirmed search is shared
by every pane in the current `---`-separated prompt stack and survives a stack rebuild,
so switching panes and pressing `n` or `N` reuses the same query against the newly
active pane.

`*` and `#` resolve the keyword run under (or, failing that, forward of) the cursor on
the current line and search for it as a whole word (`g*` / `g#` match it as a substring
instead), landing on the start of the destination match. Unlike `/` and `?`, these are
always case-sensitive, matching vim's exemption of `*` / `#` from smartcase. `n` and `N`
afterward repeat with the same whole-word and case-sensitivity rules, not a plain
smartcase substring search. When no keyword character follows the cursor on the line,
sase's TUI reports "no string under cursor" and leaves the cursor and any existing
search state untouched.

## Visual Mode

Press `v` in NORMAL mode for charwise VISUAL mode, or `V` for linewise V-LINE mode. The
border title shows `[VISUAL]` or `[V-LINE]`. `Escape` returns to NORMAL mode, and `o`
swaps the active selection end.

Visual mode supports the NORMAL-mode motions and counts listed above, including word
motions, paragraph motions, line motions, `f`/`F`/`t`/`T` with `;`/`,` repeats, `%`,
`gg`/`G`, `Ctrl+D`/`Ctrl+U`, and the NORMAL-mode text objects. `v` exits charwise VISUAL
mode; `V` exits V-LINE mode; pressing the other visual key switches selection kind.

Visual changes (`d`, `c`, `>`/`<`, `u`/`U`, `~`) are dot-repeatable over a same-sized
range from the current cursor; visual `c` repeats the replacement text typed before
`Escape`.

| Key       | Action                                                       |
| --------- | ------------------------------------------------------------ |
| `d` / `x` | Delete selection and copy it to the internal register        |
| `c` / `s` | Change selection and enter INSERT mode                       |
| `S{char}` | Surround the exact selection with a delimiter pair           |
| `y`       | Yank selection to the internal register and system clipboard |
| `p`       | Replace selection with the internal register                 |
| `>` / `<` | Indent / dedent selected lines by two spaces                 |
| `u` / `U` | Lowercase / uppercase the selection                          |
| `~`       | Toggle case in the selection                                 |
| `*` / `#` | Search forward / backward for the selected text, literally   |

Visual `*` / `#` search for the exact selected text (including embedded newlines in a
multi-line or V-LINE selection) rather than a resolved keyword, are always
case-sensitive, and return to NORMAL mode at the search destination.

Visual `S` uses the same delimiter pairs as NORMAL-mode surround, preserves an exact
charwise selection, and leaves the unnamed register unchanged. In V-LINE mode the
delimiters go inside the neighboring newlines, so the lines outside the selection do not
join the surrounded text. The edit is one undo step and `.` repeats the saved charwise
length or V-LINE row count from the current cursor; a count before `.` scales that saved
shape. `Escape` or `Ctrl+X` cancels a pending delimiter without replacing the previous
dot-repeat action. Lowercase `s` keeps its change-selection behavior. V-LINE operators
always apply to whole selected lines regardless of the cursor column.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Prompt input](prompt-input.md) — insert mode, alt-brace, search, and macro editing.
- [Prompt stacks](prompt-stacks.md) — multi-agent panes, stash, and trash.
