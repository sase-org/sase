---
title: Prompt stacks
description: Multi-agent prompt stacks, stash, and trash in the sase TUI prompt widget.
---

# Prompt stacks

This page lists prompt-stack panes, stash, and trash keys in the sase TUI prompt widget.

## Prompt Stacks {#prompt-stacks-1}

Prompt stacks are sase's TUI editing surface for literal `---` multi-agent prompts.
Loading multi-agent prompt text from history, a whole-bar editor session, or an editor
buffer that returned with a ` @` review marker splits top-level `---` segment separators
into panes labeled `agent 1`, `agent 2`, and so on; the border title shows
`Prompt · N agents`. Restoring stashed prompts and using marked-agent `,x` can also open
a stack, but those paths load one pane per selected draft or agent instead of re-parsing
each pane's text. Panes are ordered top-to-bottom for whole-stack submission. The bottom
pane is active by default so you can keep drafting the newest segment; it is not a
priority marker, and pressing `Enter` immediately opens the submit chooser.

Inactive panes stay compact, and the active pane takes the available height; each parked
pane's separator rule also carries a live [cursor readout](prompt-input.md#cursor-readout) of that
pane's own position. A `---` line typed while INSERT mode is active stays literal prompt
text; use `Ctrl+G -` while drafting, or `g-` from prompt NORMAL mode, to add a new
bottom pane. `Ctrl+G g` and `Ctrl+G Ctrl+G` open the whole stack in `$EDITOR` when the
bar already has multiple panes (a single-pane bar opens just the current prompt).
Returning from a whole-bar editor session, or from a single-pane editor buffer with a
` @` review marker, reloads macro-style Markdown and parses `---` separators into fresh
panes. History loads parse only real multi-agent prompts; a single history item with
leading YAML frontmatter stays one verbatim pane instead of auto-opening the Frontmatter
Panel.

A single-pane editor session normally launches the moment you close `$EDITOR`. To review
it in the prompt bar first, end any line of the buffer with the exact suffix ` @` (a
space followed by `@`). On return, that marker is stripped from every matching line and
the cleaned text reloads with editor-file semantics: leading macro frontmatter is lifted
into the Frontmatter Panel and real `---` separators split into one pane per agent, so a
marked multi-agent buffer comes back as a reviewable stack instead of launching. The
marker is editor-return-only — typing ` @` in the prompt bar and submitting carries no
special meaning. (This replaces the removed `%edit` directive.)

In prompt INSERT mode, pressing `Ctrl+G` opens the same context-aware hint row as prompt
NORMAL mode's `g` prefix, plus the editor continuation. Press `Esc` while the prefix is
pending to cancel it and stay in INSERT mode.

In prompt NORMAL mode, pressing `g` opens a small hint row for the prompt-local `g`
prefix actions currently available.

| Key         | Action                                                                                                                                                                              |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Enter`     | Open the submit chooser by default; `Enter` inside that panel confirms the primary action. With `ace.prompt_submission.confirm_on_enter: false`, submit the active pane immediately |
| `Ctrl+S`    | Stash the active pane; from an empty prompt, open the Prompts overlay on Stash                                                                                                      |
| `g<enter>`  | Launch the selected pane and remove it from the stack                                                                                                                               |
| `Ctrl+C`    | Record the selected pane as cancelled history and remove it; the final remaining pane cancels normally                                                                              |
| `Escape`    | Enter NORMAL mode for stack navigation                                                                                                                                              |
| `gj` / `gk` | Focus the next / previous pane in NORMAL mode; inside the panel, jump to the top / bottom prompt pane                                                                               |
| `gJ` / `gK` | Move the active pane down / up in NORMAL mode; reorder cycles at the stack edges                                                                                                    |
| `g-`        | Add an empty bottom pane in NORMAL mode and switch it to INSERT mode                                                                                                                |
| `gG`        | Open the Memory panel; seeds from the glossary term under the cursor when there is one                                                                                              |
| `gm`        | Open the Memory panel; seeds from the `#memory/<stem>` reference under the cursor when there is one                                                                                 |
| `gD`        | Choose a local or eligible enrolled launch target and update the pane's `%dispatch` selector                                                                                        |
| `gT`        | Open the Snippets panel; seeds from a bare trigger or `#[trigger]` under the cursor when one can be resolved without I/O                                                            |
| `g=`        | Show/focus the macro frontmatter panel; in panel rows mode, return to the originating prompt pane                                                                                   |
| `gs`        | Bundle every non-empty pane into one stash row and dismiss the prompt bar                                                                                                           |
| `gS`        | Overwrite a pinned stashed prompt with the current stack, leaving the bar open                                                                                                      |
| `gw`        | Write a bound macro definition; unbound drafts fall through to save-as                                                                                                              |
| `gd`        | Edit the macro definition under the cursor in the prompt bar                                                                                                                        |
| `gf`        | Reformat the active prompt pane's Markdown with Prettier                                                                                                                            |
| `gx`        | Open, retarget, or edit an existing mini-macro pane                                                                                                                                 |
| `gt`        | Open, retarget, or edit an existing snippet pane (see [Authoring a snippet from the prompt bar](snippets.md#authoring-a-snippet-from-the-prompt-bar))                                          |
| `gX`        | Save as reusable macro/snippet; macro mode converts raw `<tags>` and leaves the bar open                                                                                            |
| `gL`        | Convert the active pane into a frontmatter-local macro; raw `<tags>` become inputs                                                                                                  |

Submitting one pane at a time re-attaches prompt-level frontmatter to the launched pane
so local macros and metadata continue to resolve. Empty selected panes are dropped
without launching. Whole-stack submission joins panes in top-to-bottom order and then
uses the usual multi-agent launch path, including `%wait`, `%id`, `%model`, and other
segment-local directives. A selected-pane TODO warning counts only that pane; a
whole-stack warning counts visible markers across all non-empty submitted panes.
Choosing **Keep editing**, `n`, `Escape`, or `q` leaves pane order, selection,
frontmatter, and source binding intact. Segment order alone does not make later agents
wait; add `%wait` to a later pane when it must start after the immediately preceding
submitted pane succeeds. That bare wait binding also applies when the wait comes from a
frontmatter-local or file-backed macro referenced by the pane. Explicit waits, `%queue`,
and waits inside literal code/disabled regions keep their normal meanings.

The `Enter` submit chooser accepts `Enter`, `a`, or `Ctrl+S` for all panes, `c` for the
current pane, and `Esc`/`q` to cancel without changing the stack. For a single ordinary
prompt, the panel contains one **Launch agent** row and `Enter`/`s` launches it. Set
`ace.prompt_submission.confirm_on_enter: false` to skip this panel; then plain `Enter`
immediately submits an ordinary single pane, the active pane of a stack, or a targeted
pane. Outside that chooser, `Ctrl+S` is always an active-pane stash shortcut.

Prompt stashes are a per-user draft pile stored outside prompt history. `Ctrl+S`
captures the selected non-empty pane plus the shared prompt frontmatter; when other
panes remain the bar stays open, and when the last pane is stashed the bar closes
without also recording the draft as cancelled history. If the active pane is empty,
`Ctrl+S` opens the Prompts overlay on Stash instead. `gs` captures all non-empty panes
in their current order as one bundled stash row and dismisses the bar. `gS` opens an
update flow for an existing pinned stash and overwrites the chosen row with the current
non-empty panes. Manual and restart stashes remember the active pane and its cursor, and
restore focuses that pane in INSERT mode at the same logical line and column. Legacy
rows and failed-launch recovery rows have no saved position, so they still restore to
the last pane at end of text. `gX` and `Ctrl+G X` open one save screen containing the
name, storage location, resolved path, and a live preview when the name collides. Inside
that screen, `Ctrl+X` switches between macro and snippet mode. `Ctrl+T` remains manual
completion in the prompt input and does not toggle this save screen. A successful
whole-stack save binds the prompt stack to that source. `gw` then performs atomic
write-back, and if the source changed since load it offers overwrite, reload, or save-as
instead of clobbering it. `gd` loads the simple macro under the cursor for the same
bound editing loop. `gx` first shows the [location picker](snippets.md#save-location-picker) and
then opens or retargets one focused mini-macro pane. Press `e` there to fuzzy-find an
existing definition and edit it in place, or override a read-only one into a writable
destination. Saving that pane publishes the definition without binding the surrounding
prompt stack. `gL` converts the active pane through a prefilled frontmatter ghost row
and rewrites the pane to invoke the committed helper. Before `gX` opens the save
preview, its macro version converts live `<label>` tags into required Jinja `text`
inputs; switching that screen to snippet mode shows and saves the original active-pane
body instead. A fresh `gx` extraction applies the same raw-placeholder conversion to the
copied origin-pane body before the mini pane opens and seeds the mini definition's
inferred inputs. Raw placeholders typed later in the mini pane are saved as edited; the
mini save review does not run another conversion pass. `gL` also applies the conversion
when it creates a frontmatter-local helper. Set
`ace.prompt_inputs.macro_placeholder_args: false` to disable these conversions while
preserving `gL` Jinja-variable inference. `gw` only writes the currently bound
definition—it does not reinterpret newly typed raw placeholders. Tags in inline code,
fenced code, and disabled macro regions stay literal throughout. See
[Raw Prompt Placeholders](../macros/templating.md#raw-prompt-placeholders) for
the exact launch, conversion, and naming rules.

`Ctrl+G p` opens the Prompts overlay on the Stash tab from the prompt bar. From the main
sase's TUI tabs, when you are not typing in a text field, `@` acts on Stash. If the open
bar is Plan Feedback or Coder Prompt, `@` warns
`Restore is only available for agent prompts` and stops. Otherwise a lone pinned draft
is loaded into the prompt bar and stays in Stash. A lone unpinned draft is loaded and
then removed from Stash; it is not moved to Trash. When Stash is empty or holds more
than one draft, `@` opens the overlay on Stash instead of loading one. `,@` or clicking
the `stash:` chip always opens that overlay, including when exactly one draft is stashed
and when Stash is empty. The empty placeholder says to stash the current prompt. When
Trash has rows, it also names that count and says to press `t` to view. `[` and `]`
toggle between the Stash and History tabs with wraparound, so `]` from Stash opens
History. Trash is a view of the Stash tab, not a third tab. Press `t` on Stash, or
select the 🗑️ chip, to open it. From Trash, `t` or `Esc` returns to the Stash list. `[`
or `]` from Trash opens History, and the bracket that returns to the Stash tab brings
Trash back, because the tab remembers which view was open.

In the Stash tab, `space` toggles a row's persistent pin, `Tab` toggles a row's restore
mark, `d` marks one row for discard, `D` marks every row for discard, `a` toggles
restore marks on all rows, and `Enter` confirms the marked set; restores are pin-aware,
so marked pinned rows stay stashed. With no explicit marks, `Enter` restores the
highlighted row; pinned rows stay stashed when restored, while unpinned rows are removed
from Stash and are not moved to Trash. Press `y` to copy the highlighted row's exact
prompt body through the shared nonblocking clipboard path (OSC 52 plus a manual-copy
fallback): the payload is the stored body verbatim — multiline and bundled `---`
content, whitespace, Unicode, and raw references included, without frontmatter or
preview metadata — and the panel stays open with its highlight, scroll position, pins,
and staged marks intact. A row with an empty body copies that empty string; with no
highlighted row, `y` is a no-op.

Number keys `1`-`9` and `0` restore rows 1-10 directly with the same pin-aware behavior.
`@` on the Stash tab restores the newest draft, so `@@` pops the latest stash when
several are stashed. On the Stash list, `Escape` or `q` closes the overlay and discards
unconfirmed marks. Confirming discards for only some rows keeps the overlay open and
repaints it in place; discarding every row, or combining discards with restores, closes
the overlay. A small `stash: ≡ N` pink-chip top-bar group shows how many restorable
drafts are currently stashed; the Trash count appears as the 🗑️ chip on the Stash tab,
expanding to `Trash N/LIMIT` in the Trash view.

Every Prompts overlay entry point — including the History ones (`Ctrl+K`, `,.`, `,>`) —
first reads the stash store. If that read fails (for example a stale core binding, or a
parse or lock error), an error toast beginning `Failed to read stashed prompts` names
the cause and no overlay opens.

Discarding a Stash row moves it to the **Trash view** immediately with no y/n — `d`/`D`
then `Enter` sends the marked rows straight to Trash, including pinned rows and batches
that overflow the Trash limit — newest-deleted-first with the deletion age visible,
unless `ace.prompt_stash.trash_limit` is `0` (see below). In the Trash view, `Enter` (or
a digit key, or marked `Tab`/`a`) restores rows back to Stash while the overlay stays
open; it never loads the prompt bar. `d`/`D` stage rows for permanent deletion and
`Enter` asks for explicit confirmation before purging; `Ctrl+Y` copies a row. Trash
holds at most `ace.prompt_stash.trash_limit` entries (default 100; this is an
entry-count limit, not a byte quota): when a discard batch overflows it, the success
toast names the actual evictions and `sase prompt stash-archive` for recovery. Setting
the limit to `0` disables Trash recovery: Stash `d`/`D` plus `Enter` then delete
permanently (still archived; see below), and a partial discard is applied without a
confirmation prompt. A lowered limit is applied the next time the overlay opens, before
that window is shown. Over-limit rows are permanently deleted, oldest discarded first.
The toast reads `Trash limit lowered to N: permanently deleted K oldest draft` (or
`drafts`). The Trash view in the window that just opened still lists the rows and
`Trash N/LIMIT` count from before that deletion, so the count can be higher than the new
limit. Close the overlay and open it again to see the rows that remain. `Enter` on a row
that was already deleted does not restore it and does not show a success toast. The
Trash view then repaints from the store, so every already-deleted row disappears. If
applying the limit fails, the stored Trash is left unchanged and the overlay still
opens. The error toast is `Failed to reconcile Trash limit: ...`, or
`Prompt stash is busy — retry` when the stash lock times out. Trash recovers only drafts
deliberately discarded from Stash. A successful restore of an unpinned Stash row removes
that row without putting it in Trash. This overlay has no action that deletes History
rows.

A permanent removal, and a replacement of a row's text, frontmatter, or cursor, is
archived first to the append-only `prompt_stash_archive.jsonl` sitting next to
`prompt_stash.jsonl`. The copy keeps the full previous text. Reason names are `popped`,
`purged`, `evicted`, and `overwritten`; see
[Recover a Stashed Draft](../prompt-history.md#recover-a-stashed-draft). Moving a row into Trash,
and bringing it back from Trash, do not write an archive copy. A confirmed purge stays
recoverable from that file. List recent archive rows with `sase prompt stash-archive` (a
bare invocation defaults to `list`), filter with `-q/--query` and `-r/--reason`, inspect
one draft with `sase prompt stash-archive show ID`, and append drafts back to Stash with
`sase prompt stash-archive restore ID...` (unique id prefixes work). The purge
confirmation, purge and eviction toasts, and the in-place delete toast all name this
recovery command.

Compact demo — discard `fix flaky parser test`, then recover it. Leave at least one
other Stash row unmarked. Discarding every Stash row closes the overlay, so the later
steps would start by opening Stash again:

1. Stash tab: highlight the row, press `d`, then `Enter`. The toast reads
   `Moved 1 draft to Trash` and the Stash tab's 🗑️ chip shows `🗑️ 1`.
2. Press `t` to open the Trash view: the row sits newest-first with its deletion age
   under the `🗑️ Trash 1/100` pill.
3. Press `Enter`: the toast reads `Restored 1 draft to Stash`, the overlay stays open,
   and `t`/`Esc` return to a Stash tab holding the recovered draft.

Trash requires the current stash core binding: restart old TUI processes before the new
behavior takes effect, since mixed-version operation is unsupported. Before the first
new-format write, sase verifies a recoverable pre-upgrade backup of `prompt_stash.jsonl`
under the stash lock and fails closed when backup creation fails; recover pre-upgrade
drafts from that backup.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Prompt input](prompt-input.md) — insert mode, alt-brace, search, and macro editing.
- [Prompts overlay](prompts-overlay.md) — History, Stash, and Trash.
- [Run agents in parallel](../../guides/run-agents-in-parallel.md) — splitting work across panes.
