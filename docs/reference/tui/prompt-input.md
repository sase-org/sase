---
title: Prompt input
description: Insert mode, alt-brace syntax, macro editing, search, and launch-target picking in the sase TUI prompt widget.
---

# Prompt input

This page lists insert-mode keys, alt-brace syntax, macro editing, search, and
launch-target picking for the sase TUI prompt widget.

## Prompt Input Widget

The prompt input is a multiline TextArea widget with vim-style INSERT, NORMAL, VISUAL,
and V-LINE modes. The widget provides markdown syntax highlighting for prompt content
(headings, bold, italic, code blocks, lists, etc.). The first dash of an unindented or
space-indented `- ` bullet, and the digits plus delimiter of an unindented or
space-indented `<N>.` / `<N>)` ordered marker, are additionally bolded with the same
theme-aware accent, including inside fenced code; this presentation does not change the
prompt text. A tab-indented dash or ordered marker is not treated as a list marker.

Known macro syntax is layered over the Markdown colors using the active theme: `#macro`
references are bold in the theme's success color, `%directives` are bold in its warning
color, `/skill` references use a tint of the accent color, and `---` separators are
dimmed. Argument text is split into parts instead of one flat color — delimiters such as
`:`, `(`, `,`, and `)` and the `=` sign are muted, keyword names use a lighter tint of
the owning reference's color, and values are tinted by type (strings, numbers, and
booleans each get their own hue). Directive arguments get the same treatment in the
directive palette. An argument that names an unknown keyword, repeats a keyword, or has
a value of the wrong type is additionally underlined.

When loaded prompt text contains literal top-level `---` multi-agent separators, sase's
TUI renders the text as a prompt stack: one pane per agent segment. YAML frontmatter at
the start stays prompt-level metadata, and `---` lines inside fenced code blocks are
left alone. A `#name` macro swarm invocation stays a single pane and expands only when
it is launched. During live editing, typed `---` lines stay literal text; add prompt
panes with `g-` in prompt NORMAL mode. The detailed multi-agent parsing rules live in
the [Macro reference](../macros/multi-agent-prompts.md#multi-agent-prompts). For
steps to split and follow independent tasks, see
[Run agents in parallel](../../guides/run-agents-in-parallel.md).

### Cursor Readout

Every mounted pane advertises its cursor position as `Ln <line>, Col <column>`, both
1-based and counted in document columns (the character index within the logical line,
not the soft-wrapped screen column). The active pane's readout sits flush right on the
bar's bottom border, next to the mode hints; each parked pane's readout sits on the
right end of its own `─── ▍ agent N ───` separator rule. The digits are painted the
color of that pane's own vim-mode cursor -- gold for NORMAL, cyan for INSERT, magenta
for VISUAL / V-LINE -- so the readout and the cursor it describes always match. On a
narrow terminal the active-pane readout always wins over the mode hints (which truncate
first) and the prompt-search match pill; a parked pane's readout is dropped entirely
rather than abbreviated if its separator cannot fit both the readout and the `agent N`
label.

### Prompt Search

In prompt NORMAL mode, `/` and `?` open an incremental search panel for forward and
reverse searches. As you type, matches are highlighted in the active pane and the
panel's right edge shows the selected stack-global count, such as `2/3`. `Enter` accepts
the current local match and keeps the highlights; `Esc` or `Ctrl+C` cancels the search,
restores the origin cursor, and clears the highlights. If a query has matches elsewhere
in the prompt stack but none in the active pane, the panel says
`no match in this pane · N in stack`; accepting still does nothing until the active pane
has a local match.

After a search is accepted, the count moves to a compact two-tone pill on the prompt
bar's bottom border, just left of the `Ln, Col` readout. The query chip is graphite and
uses the accent color for the search sigil; the count chip is solid warning gold, the
same color as the current-match highlight, with the current ordinal in bold. The chip
ink is chosen for maximum contrast from the theme's own foreground and background while
avoiding colors that 256-color terminals with base16 palettes repaint. The sigil records
how the search was made: `/` for forward, `?` for reverse, `*` for whole-word forward,
and `#` for whole-word reverse. Non-whole-word word searches (`g*`, `g#`, and VISUAL `*`
/ `#`) use `/` or `?`.

`n` and `N` repeat the recorded search across every non-auxiliary prompt pane in stack
order, with the existing wrap toasts when the traversal crosses the top or bottom. `*`,
`#`, `g*`, and `g#` search from the word under the cursor; VISUAL `*` and `#` search the
selected text. The pill's number is always stack-global and follows the highlighted
match, even if you move the cursor away afterward. It disappears with the highlights:
`Esc`, entering INSERT, edits, pane switches, and starting a new search all clear it.
See [Operator + Search](prompt-modes.md#operator-search) for operating up to a match with `d/`, `d?`,
`dn`, and `dN`.

On narrow terminals, the bottom border keeps the cursor readout first. The mode hints
truncate or drop before the search pill; then the pill drops its query segment and keeps
only the count; if even that cannot fit, only `Ln, Col` remains.

### INSERT Mode (Default)

| Key                          | Action                                                                                                                                                                                                                                                                                                                          |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Enter`                      | Open the submission panel for a non-empty agent prompt; pressing `Enter` again confirms the primary launch action. Does not accept a completion candidate                                                                                                                                                                       |
| `Ctrl+S`                     | Stash the active pane; from an empty prompt, open the Prompts overlay on Stash                                                                                                                                                                                                                                                  |
| `Ctrl+C`                     | Cancel the prompt; in a prompt stack, cancel only the selected pane                                                                                                                                                                                                                                                             |
| `Ctrl+J`                     | Insert a newline; continue a containing `- ` bullet or `<N>.` item (renumbered), or leave the list from an empty marker                                                                                                                                                                                                         |
| `Ctrl+A`                     | Move to start of line (jumps to previous line start if already at col 0)                                                                                                                                                                                                                                                        |
| `Ctrl+E`                     | Move to end of line (jumps to next line end if already at end)                                                                                                                                                                                                                                                                  |
| `Ctrl+F`                     | Accept a highlighted completion-menu candidate; with no menu, take the whole inline ghost when the rest of the line is blank, or move one character forward                                                                                                                                                                     |
| `Ctrl+G`                     | Start the prompt-local prefix (`g` or `Ctrl+G` again opens `$EDITOR`)                                                                                                                                                                                                                                                           |
| `Ctrl+G Enter`               | Submit only the selected pane                                                                                                                                                                                                                                                                                                   |
| `Ctrl+G j/k`                 | Focus the next / previous pane and leave the target pane in INSERT mode                                                                                                                                                                                                                                                         |
| `Ctrl+G J/K`                 | Move the active pane down / up and leave it in INSERT mode                                                                                                                                                                                                                                                                      |
| `Ctrl+G -`                   | Add an empty bottom pane                                                                                                                                                                                                                                                                                                        |
| `Ctrl+G G`                   | Open the Memory panel; seeds from the glossary term under the cursor when there is one                                                                                                                                                                                                                                          |
| `Ctrl+G m`                   | Open the Memory panel; seeds from the `#memory/<stem>` reference under the cursor when there is one                                                                                                                                                                                                                             |
| `Ctrl+G D`                   | Choose a local or eligible enrolled launch target and update the pane's `%dispatch` selector                                                                                                                                                                                                                                    |
| `Ctrl+G d`                   | Edit the macro definition under the cursor in the prompt bar                                                                                                                                                                                                                                                                    |
| `Ctrl+G f`                   | Reformat the active prompt pane's Markdown with Prettier                                                                                                                                                                                                                                                                        |
| `Ctrl+G w`                   | Write a bound macro definition; unbound drafts fall through to save-as                                                                                                                                                                                                                                                          |
| `Ctrl+G =`                   | Show/focus the macro frontmatter panel; its rows-mode `g=` returns to the originating pane                                                                                                                                                                                                                                      |
| `Ctrl+G s`                   | Bundle every non-empty pane into one stash row                                                                                                                                                                                                                                                                                  |
| `Ctrl+G S`                   | Overwrite a pinned stashed prompt with the current stack                                                                                                                                                                                                                                                                        |
| `Ctrl+G x` / `Ctrl+G Ctrl+X` | Open, retarget, or edit an existing mini-macro pane                                                                                                                                                                                                                                                                             |
| `Ctrl+G t` / `Ctrl+G Ctrl+T` | Open, retarget, or edit an existing snippet pane (see [Authoring a snippet from the prompt bar](snippets.md#authoring-a-snippet-from-the-prompt-bar))                                                                                                                                                                                      |
| `Ctrl+G X`                   | Save as reusable macro/snippet; macro mode converts raw `<tags>`                                                                                                                                                                                                                                                                |
| `Ctrl+G L`                   | Convert the active pane into a frontmatter-local macro; raw `<tags>` become inputs                                                                                                                                                                                                                                              |
| `Ctrl+G Ctrl+C`              | Cancel every pane in the prompt stack at once                                                                                                                                                                                                                                                                                   |
| `Ctrl+G p`                   | Open the Prompts overlay on Stash                                                                                                                                                                                                                                                                                               |
| `Ctrl+G r`                   | Open the recent-files history menu (recently referenced files and `@kind:payload` references)                                                                                                                                                                                                                                   |
| `Ctrl+Y`                     | Open the workflow YAML editor                                                                                                                                                                                                                                                                                                   |
| `Ctrl+K`                     | Open the Prompts overlay on History from a single-line prompt, scoped to that prompt's project (see [Prompts Overlay](prompts-overlay.md#prompt-history-modal))                                                                                                                                                                                   |
| `Ctrl+P`                     | Cycle toward older workspace MRU prefixes (no-prefix stop before wrapping); in a macro keyword slot, open the keyword menu at its last row                                                                                                                                                                                      |
| `Ctrl+N`                     | Cycle toward newer workspace MRU prefixes (no-prefix stop before wrapping); in a macro keyword slot, open the keyword menu at its first row                                                                                                                                                                                     |
| `Ctrl+T`                     | Completion (structured tokens, paths, prompt-local words, history words, or next-word ghosts and border peeks; at a whitespace boundary it requests next words instead — recent files moved to `Ctrl+G r`; a second press accepts the highlighted word-menu row or takes one ghost or peek word; see [Completion](prompt-completion.md#completion)) |
| `Ctrl+R`                     | Recursive fuzzy file finder using the same prompt-aware path root as file completion                                                                                                                                                                                                                                            |
| `Tab`                        | Expand a snippet or advance its tabstop; otherwise indent a bullet or nest an ordered item under a preceding marker                                                                                                                                                                                                             |
| `Shift+Tab`                  | Retreat to the previous snippet tabstop; otherwise dedent a bullet or unnest an ordered item into its enclosing run                                                                                                                                                                                                             |
| `#@`                         | Open Macro snippet picker (type `#` then `@`)                                                                                                                                                                                                                                                                                   |
| `Escape` / `Ctrl+]`          | Switch to vim NORMAL mode; `Ctrl+]` is the race-free alternative when typing following NORMAL commands quickly                                                                                                                                                                                                                  |

In prompt INSERT mode, sase's TUI auto-pairs safe openers for `()`, `[]`, `{}`, `<>`,
single quotes, double quotes, and backticks. Typing the matching closer over an
auto-inserted closer moves the cursor across it instead of duplicating it, and backspace
or delete removes both sides of an empty pair. Pairing is conservative: it is suppressed
before token characters, when text is selected (the typed character replaces the
selection literally), for contractions or possessives, and for repeated quotes/backticks
needed to type Markdown fences or code spans.

When `(` is typed immediately after a macro or supported directive argument delimiter,
the prompt input normalizes the shorthand in one keyboard edit. A single colon is
removed (`#review:` -> `#review()`), while `::` followed only by ASCII spaces is moved
after a complete pair (`#review:: body` -> `#review():: body`) with the caret inside the
parentheses. Typing `(` immediately after a closed macro argument list continues the
list by adding a comma and placing the caret before `)`, for example
`#review(path=a):: body` becomes `#review(path=a,|):: body`; the remaining macro
argument menu opens when `auto_macro_menu` is enabled. Empty lists and lists that
already end in a comma only move the caret. The double-colon form preserves the exact
spaces and suffix text; tabs, newlines, nonbreaking spaces, directive argument lists,
selected text, and literal regions keep ordinary insertion behavior.

INSERT-mode `Ctrl+J` and prompt NORMAL-mode `o` / `O` continue a containing
space-indented `- ` bullet using that bullet's indentation. Prompt NORMAL-mode `J` is
the inverse operation: when it folds the next line into a nonblank current line, it
drops that line's supported `- ` marker. Bullet continuation also works from physical
continuation lines, including Prettier-wrapped nested bullets; non-bullet lines keep the
ordinary bare newline or open-line behavior. In INSERT mode, when there is no selection,
pressing `Ctrl+J` anywhere on a line containing only zero or more leading spaces
followed by `- ` replaces that marker with a bare newline and moves the cursor to column
zero, ending the list -- but only when the line above that marker is itself part of a
hyphen bullet. The common sequence is therefore `Ctrl+J` once to create the next sibling
marker and `Ctrl+J` again to exit the list. A marker-only line whose preceding line is
not part of a bullet -- a freshly typed `- ` on the first line, or one following a blank
line or plain prose -- grows a sibling marker on the next line instead, so the exit
still happens on the following press. Those two edits are separate undo checkpoints. A
selection uses the normal replacement path instead. Extra spaces after the marker, tab
indentation, other Markdown markers, and markers containing text do not trigger either
path.

Ordered items (`<N>.` or `<N>)`, one to nine digits) mirror every one of those hyphen
rules for `Ctrl+J`, `o`, `O`, and `J`, and add the one thing ordered lists need: after
each structural edit, sase's TUI renumbers the surrounding _run_ -- the maximal sequence
of same-indent, same-delimiter siblings, joined across blank lines and each item's own
owned continuation lines -- so the live numbers agree with what `gf` (Prettier
formatting) would produce. When a run's second item repeats the first item's number,
every item in the run keeps that number (the `1. / 1. / 1.` convention Prettier
preserves); otherwise later items are numbered sequentially from the first item's start.
`Ctrl+J`, `o`, and `O` give a newly inserted item the number after its nearest preceding
sibling, or the run's first number when there is none. `J` drops the pulled-up marker
and renumbers the run it left behind. A renumber that changes a marker's width (`9.` ->
`10.`) shifts every line that item owns by the same amount so indentation stays correct,
and leading zeros (`007. `) are recognized as a marker but always renumber to plain
decimal.

In INSERT mode, `Tab` and `Shift+Tab` do snippet work before list shifting. `Tab` first
expands a trigger word immediately before the cursor, then advances to the next live
snippet tabstop. `Shift+Tab` first retreats to a previous live tabstop. When that
snippet action reports no movement or expansion, the selection is collapsed, and the
cursor is anywhere on a direct marker line beginning with zero or more spaces followed
by `- `, sase's TUI indents or dedents that bullet. Each press shifts only that logical
line by the same two-space unit as vim `>>` / `<<`; dedent removes up to one unit, and
the cursor follows the shifted content. Physical continuation lines, tab indentation,
and other Markdown marker styles are excluded.

The same fallback applies to ordered items from anywhere on the direct `<N>.` / `<N>)`
marker line. Ordered `Tab` nests at the _content column_ of the nearest preceding marker
line (either session, same or lower indent) instead of a fixed two-space unit, because
an ordered item can only interrupt its parent's paragraph when numbered `1`: `Tab` with
no preceding marker line to nest under is a no-op, `Tab` landing under an existing
nested run continues that run at its next number, and `Tab` that starts a new nested
list numbers the moved item `1`. `Shift+Tab` moves the item back out to its parent's
indent and gives it the next number in that outer run; at the outermost level it is a
no-op. Both carry the item's owned block along and renumber the source and destination
runs as one undo checkpoint.

Text automatically wraps at the terminal width, breaking at spaces (never mid-word).
Line numbers appear in cyan when the text exceeds one line. The native cursor cell is
color-coded by prompt Vim mode: INSERT uses cyan, NORMAL uses gold, and VISUAL or V-LINE
uses magenta.

Uppercase `TODO` at identifier boundaries is a visual draft marker. sase's TUI gives
`TODO`, `TODO:`, `TODO(owner)`, and `TODO(owner):` headers the exact `#FFD700` gold used
by the Agents-tab `RUNNING` status with explicit deep navy `#00005F` text. The deep navy
stays legible on gold without relying on the terminal's customizable ANSI black palette
entry. Only a header ending in `:` activates the quiet, theme-aware warm italic
annotation style for the rest of that line; punctuation and prose after bare `TODO` or
`TODO(owner)` retain their ordinary prompt syntax. When the first content in a dash-list
item is the exact `TODO:` header, the body style continues through lazy and indented
continuation lines, nested list content, and later paragraphs that Markdown assigns to
that item. It stops at the sibling-item or outside-content boundary, and structural list
dashes keep their bullet color. Checklist prefixes, `TODO(owner):`, and a `TODO:` later
in item prose retain the same-line behavior.

Inline backtick spans and closed or live unclosed backtick/tilde fenced code blocks are
literal zones: TODO-shaped text inside them receives no marker or body treatment and is
omitted from the count. Ordinary quotation marks are not code delimiters. Lowercase
`todo` and identifiers such as `TODOS`, `TODO2`, and `preTODO` remain ordinary text.
When markers exist, the prompt border shows a matching deep-navy-on-gold `TODO N` count
pill for every non-literal match across the full prompt stack, including compact
inactive panes and markers outside the active viewport. The pill disappears immediately
when the last marker is edited away.

TODO treatment does not move the cursor during history or stash restoration, and sase's
TUI stashes and opens the literal prompt text in `$EDITOR` unchanged. Submitting an
agent prompt with one or more visible TODO markers opens a neutral y/n confirmation with
**Keep editing** focused by default. Keeping the draft preserves the exact prompt or
prompt stack without launching or writing history; approving launches the same literal
prompt text unchanged. The warning uses the same detector as the gold marker and count
pill, so TODO-shaped text in inline or fenced code, lowercase `todo`, and non-boundary
identifiers such as `TODOS`, `TODO2`, and `preTODO` do not trigger it. Feedback and
coder-prompt submission keep their existing unguarded behavior. Only the
colon-terminated body-note color follows the active dark or light theme, while the
shared deep-navy-on-gold header and count pill remain fixed; search matches, selections,
yank feedback, and the cursor retain their higher-priority treatments.

### Raw Placeholder Inputs

Raw `<placeholder>` tags in sase's TUI prompt bar act like ad hoc prompt inputs. When
you submit a prompt containing one or more highlighted raw tags, sase's TUI opens the
**Prompt Inputs** panel before launch. The panel lists each unique tag once, shows a
one-line context snippet and an occurrence count, and collects values on the same page
as any required frontmatter-declared `input:` arguments. After confirmation, sase's TUI
substitutes the collected values into the prompt and records history for the resolved
prompt that the agents actually received.

Inline backtick spans, fenced code blocks, and `%macros_enabled:false` regions are
literal zones. Tags inside those zones are not highlighted as raw placeholders, recorded
in the saved common-placeholder store, or collected on submit. Their text is still
offered as a current-prompt completion candidate, ranked after live tags. Use backticks
when a tag-like value is meant to survive literally, for example
``keep `<div>` unchanged``.

Each raw placeholder row must be filled before launch unless it is marked literal. Press
`Ctrl+L` in the Prompt Inputs panel to toggle **keep literal** for the focused
placeholder row; when focus is outside the field list, `Ctrl+L` marks all still-empty
placeholder rows literal. A literal row counts as filled and leaves its original
`<placeholder>` text in the launched prompt.

Set `ace.prompt_inputs.collect_raw_placeholders: false` to stop collecting raw tags on
submit; declared frontmatter inputs are still collected. Set
`ace.prompt_inputs.macro_placeholder_args: false` to keep live raw tags literal when
using `gX`, `gL`, or a fresh `gx` extraction and mint no placeholder-derived `text`
inputs; Jinja-variable inference for `gL` still runs. See
[Raw Prompt Placeholders](../macros/templating.md#raw-prompt-placeholders) for
the exact conversion and naming rules.

### Launch Target Picker

From any ordinary prompt pane, press `gD` in NORMAL mode or `Ctrl+G D` in INSERT mode to
open **Launch Target**. The first row is `here`, followed by enrolled aliases in
alphabetical order. Local enrollment data labels every non-quarantined remote `ok` and
enables it; quarantined rows remain visible with their diagnostic context but are
disabled. This is a local eligibility catalog, not a live gateway health check; use the
Admin Center Machines tab's `s` action when current reachability matters. Move with `j`
/ `k` and press `Enter`, or select one of the first ten rows directly with `1`–`9` /
`0`.

Choosing a remote inserts or replaces the pane's single `%dispatch:<alias>` selector.
Choosing `here` removes it. The prompt context line appears while the pane has a
`%dispatch` selector: a valid one shows the cached Target and Source, and for a remote
also states that source proof is checked on submit; an invalid one shows `Target error`
with the reason. It stays hidden for ordinary local launches, unless the pane carries an
invalid `%auto` spelling: that shows an `Auto error` segment with the same message the
launch path raises, and Enter does not submit until the spelling is fixed. On
submission, the prompt bar closes immediately and source proof runs off the UI thread as
the first pending launch stage. A failed proof restores the prompt with
`source blocked: <reason>` in its context line (or saves it to the stash if another
prompt or modal now owns the screen).

After source preflight passes, sase's TUI inserts a provisional `QUEUED` remote row
before the background launch settles. A structured accepted owner response keeps it
`QUEUED`; a settled response changes it to `STARTING`. If the launch finishes without a
structured dispatch result—including the current rejection and failed-receipt paths—the
row becomes outcome-unknown `WAITING`; use **Agents: check dispatch launch outcome**
from the command palette. Once the owner's catalog exposes the matching logical or exact
locator, sase's TUI removes the provisional row in favor of that authoritative row. The
[Remote Dispatch Runbook](../integrations/remote-dispatch.md#launch-and-operate) explains the portable
source requirements and remote operation model.

<a id="prompt-stacks"></a>
Moved to [Prompt stacks](prompt-stacks.md#prompt-stacks-1).
### Editing an Existing Macro from the TUI

Loading a definition into the prompt bar for editing puts the bar into a **targeting**
state instead of a plain draft: the bar tracks the exact source file your edits will
write to, and everything below applies whenever the bar shows a target. Every surface
that loads an editable definition enters this state the same way:

- The Config Macros child's `Enter` (see [Editing Macros](snippets.md#editing-macros)).
- The Select Macro `#` picker's `Ctrl+O` ("edit here"), alongside its existing `Ctrl+E`
  (open in `$EDITOR`) and `Ctrl+I` (inline-expand) keys.
- The jump panel (`Ctrl+]`, `gd`) and `gd` under the cursor in the prompt bar.
- Returning from a whole-bar `$EDITOR` round trip (`Ctrl+G g`) preserves whatever target
  the bar already had — your edits stay bound to the same file.

A read-only source (legacy, plugin, built-in) loads without a target: the bar shows a
persistent read-only marker instead of binding, and `gw` falls through to the save-as
flow rather than clobbering the original.

**Visual state.** A targeted bar's border switches from a solid to a **double** rule so
the state reads at a glance in any theme: `$secondary` when clean, `$warning` when dirty
or when the source changed on disk underneath you, and a dim `$foreground` when
read-only. The border title shows a `✎ <reference>` chip using the canonical reference
you'd actually type (`#foo`, `#memory/foo`, `/skill-name`) — not the file stem —
followed by a state marker: dim `✓` (clean), gold `●` (dirty), `🔒 read-only`, or
`⚠ changed on disk` (another process edited the file since you loaded it). The
frontmatter panel's border tints to match and auto-shows on a targeted load, even before
you add any frontmatter fields.

**Saving.** `Enter` opens the submit chooser by default for non-empty prompt drafts:
ordinary single panes, targeted panes, and multi-pane stacks all use the same panel. The
chooser's rows are target- and pane-count-aware: `Enter`/`s` launches a single pane,
`Enter`/`a` launches all panes in a multi-pane stack, `c` launches only the current
pane, `w` saves to the targeted reference (its subtitle names the destination when
dirty, or says there's nothing to save when clean), and `X` forks the definition to a
new location. Set `ace.prompt_submission.confirm_on_enter: false` to make plain `Enter`
launch the active pane immediately; `gw` / `Ctrl+G w` performs the same save directly,
and the bar's subtitle shows a `[^G w] save <reference>` hint whenever a target is
active. If the source changed on disk since you loaded it, the save opens a conflict
prompt offering overwrite, reload, or save-as instead of silently clobbering the
external edit.

**Chezmoi-managed homes.** With `use_chezmoi: true`, editing a definition under `$HOME`
whose chezmoi source already exists writes to that chezmoi **source** file, not the
applied copy — the applied copy is regenerated by `chezmoi apply` and would otherwise
silently discard your edit on the next apply. The border title and the follow-up actions
modal both surface this redirect so it's never a surprise.

**Follow-up actions.** After a save (or an `E` / `$EDITOR` edit), a follow-up modal
offers only the actions that apply to the file you just wrote, each toggleable and run
through the tracked proc queue in order:

- **Commit & push** — offered when the write path is inside a git repo with changes.
- **Apply chezmoi** — offered when the write redirected to a chezmoi source; scoped to
  just the one home target, never a whole-home apply.
- **`sase memory init`** — offered instead of the two above when you edited a
  [SASE memory note](../memory/memory.md), since it already commits and pushes
  for you while regenerating `AGENTS.md` and the provider instruction shims.
- **`sase skill init`** — offered instead of the two above when you edited a canonical
  [skill source](../macros/fields.md#skill-field), since it already commits,
  pushes, and deploys the generated skill files for you.

With a single offered action, `Enter` runs it and `Esc` skips, matching the previous
plain commit/push confirmation. With more than one, each row's key toggles it and
`Enter` runs everything still selected.

<a id="completion"></a>
<a id="next-word-prediction"></a>
Moved to [Prompt completion](prompt-completion.md#completion).
### Alt Brace Syntax (`%{...}`)

The prompt input has dedicated highlighting and editing help for the `%{A | B}` alt
fan-out shorthand (see the
[Alt Directive reference](../macros/directive-composition.md#alt-directive)). It
distinguishes the alt delimiters from the branch separators so a fan-out is easy to read
at a glance:

- The `%{` opener and `}` closer are styled as **delimiters** (bold accent).
- Top-level `|` branch **separators** use a dimmed accent so they read differently from
  the delimiters.
- A branch name before a top-level `=` (e.g. `sec=` in `%{sec=... | perf=...}`) is
  highlighted as a **branch name**.
- An unmatched `%{` (or stray closer) is flagged as an **error** span.

The alt overlay layers on top of the existing Jinja and search highlighting rather than
replacing it, and it uses the same size guards, so highlighting stays responsive on
large prompts.

Editing help in sase's TUI prompt input mirrors the Jinja auto-pair behavior and only
fires for the `%{...}` shorthand. Any `%` directly before `{` opens an alternation,
wherever it appears: at a word boundary, mid-word (`foo%{bar | baz}qux`), after
punctuation, or nested inside another branch:

- **Auto-pair** — typing `{` immediately after `%` inserts `%{  }` and parks the cursor
  between the two padding spaces. The expansion fires at end of line, before whitespace,
  before a bracket closer (`)`, `]`, `}`, `>`), and before trailing punctuation (`.`,
  `,`, `;`, `:`, `!`, `?`), so a fan-out can be inserted before the existing `?` in
  `Which is better %{ A | B }?`. It remains suppressed before word characters and other
  token-opening characters.
- **Paired delete** — backspacing the `{` in `%{|}` also removes the auto-inserted `}`;
  a forward delete on `%|{}` removes both braces.
- **`|` separator normalization** — typing `|` inside a live `%{...}` span inserts a
  padded `|` separator, keeps the cursor after the trailing space and before the closing
  `}`, and normalizes comma spacing in the current branch. For example, typing `|` at
  the end of `%{foo ,bar, and baz` yields `%{foo, bar, and baz | }` with the cursor
  before `}`. Openers inside literal zones (inline code, fenced blocks, disabled
  regions) are ignored; an unclosed span never extends past the cursor's own line, so a
  stray opener cannot capture a later `|`; and when alternations nest, the innermost
  span wins.
- **No Jinja pair after `%{`** — typing `%`, `#`, or `{` right after an alternation
  opener starts a branch (`%m:`, `#macro`) instead of a Jinja `{%  %}` or `{#  #}` pair.

These edits are suppressed when there is an active selection or when the cursor is not
inside a `%{...}` context, so ordinary `{` and `|` typing elsewhere is unaffected.
External editor integrations do not own `%{}` auto-pairing or paired delete;
editor-local brace-pair plugins own that lifecycle there. The
[Neovim plugin](https://github.com/sase-org/sase-nvim) still provides the same
separator-normalization behavior for prompt buffers.

<a id="normal-mode"></a>
<a id="motions"></a>
<a id="operators"></a>
<a id="text-objects"></a>
<a id="operator-search"></a>
<a id="other-commands"></a>
Moved to [Prompt modes](prompt-modes.md#normal-mode).
<a id="visual-mode"></a>
Moved to [Prompt modes](prompt-modes.md#visual-mode).

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Prompt modes](prompt-modes.md) — NORMAL and Visual keys.
- [Prompt stacks](prompt-stacks.md) — multi-agent panes, stash, and trash.
- [Prompt completion](prompt-completion.md) — token completion and next-word prediction.
- [Snippets](snippets.md) — snippet expansion and the Macro Browser.
- [Prompts overlay](prompts-overlay.md) — History, Stash, and Trash.
