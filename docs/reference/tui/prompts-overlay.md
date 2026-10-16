---
title: Prompts overlay
description: History, stash, and trash in the sase TUI Prompts overlay (the prompt-history modal).
---

# Prompts overlay

This page lists History, Stash, and Trash keys in the sase TUI Prompts overlay.

## Prompts Overlay {#prompt-history-modal}

Stash and History live in one **Prompts** overlay: a single frame with a split-button
Stash tab (`≡ Stash N` plus a 🗑️ chip) and a `↺ History` tab, a consistent list/preview
split, and one contextual footer per view. Trash is the Stash tab's Trash view, opened
with `t` or the 🗑️ chip; `t` or `Esc` there returns to the Stash list, and `q` closes
the overlay. `@` on Stash restores the newest draft, so `@@` pops the most recently
stashed prompt when several are stashed. `[` and `]` cycle the two top-level tabs with
wraparound (even from the focused History filter). From Trash, either bracket opens
History, and coming back restores Trash because the Stash tab remembers its view.
Clicking the Stash label shows the list, while clicking the 🗑️ chip shows Trash. `Esc`
on the Stash list or on History closes the overlay, and `q` closes when focus is outside
a text input. Each tab keeps its highlight, scroll, filter, loaded pages, preview
position, and staged marks across switches, the Stash tab remembers its last view, and
History loads lazily on first activation so opening Stash performs no history disk I/O.

For a goal-based workflow to search and replay an old prompt, see
[Find and replay an old prompt](../../guides/find-and-replay-prompt.md).

Press `Ctrl+K` from the prompt input to open the overlay on the History tab. That
shortcut is available when the current prompt is a single logical line; that line's
first active workspace reference (e.g. `+sase`) becomes an initial `project:<name>`
filter scope once the project-identity snapshot resolves, with the remaining text
preserved as a literal search (see Filtering below). A `+<project>` tag counts when it
names a known project or leads the line, a `#` VCS reference always counts, whichever
comes first wins, and references inside code spans are skipped. A blank prompt opens
History with no project filter. Press `,` then `.` (written `,.`) from a main tab, when
you are not typing in a text field, to open that same unfiltered History tab. `,.` reads
the most recently launched workspace prefix other than the built-in `#git:home` default.
Submitting or editing a row replaces that row's workspace prefix with that recorded
prefix. A `+home` launch does not create a qualifying prefix. When none is recorded,
sase warns `No previously launched VCS macro` and opens nothing. `,>` opens History with
cancelled prompts visible, and `,Ctrl+G` skips the overlay and opens the newest history
entry in `$EDITOR`. Both use that same prefix check and the same prefix replacement, so
with no qualifying prefix they warn and open nothing. `Space` on a main tab is separate:
it prefills the prompt input with that same non-home prefix, or opens a blank home
prompt when none is recorded. The History tab loads prompts previously launched from
sase's TUI or `sase run` in recency pages of `ace.page_size` rows (default 100). Normal
launch writes skip prompts shorter than five words (e.g. `y`, `ok`) so they do not
clutter the list, while failed-launch recovery can still preserve a short submitted
prompt. The same history is available from the shell through [`sase prompt`](../prompt-history.md).

Bare prompts are stored after launch normalization, so a prompt without an explicit
workspace reference appears with the default `#git:home` prefix. Explicit workspace
prefixes also feed the prompt-input MRU controls. In the prompt input, the MRU ring is
ordered from most recent to oldest: `Ctrl+P` moves toward older launchable workspace
prefixes, while `Ctrl+N` moves toward newer prefixes. Each edge has a no-prefix stop
that removes the first launchable workspace tag from the prompt without touching the
remaining prompt text, then wraps. When no workspace tag is present, `Ctrl+P` starts at
the most recent entry and `Ctrl+N` starts at the oldest one.

### Keybindings {#keybindings-1}

| Key              | Action                                                    |
| ---------------- | --------------------------------------------------------- |
| `↑` / `↓`        | Move the highlight (also `Ctrl+P` / `Ctrl+N`)             |
| `Enter`          | Submit the highlighted prompt directly                    |
| `Ctrl+G`         | Open the highlighted prompt in `$EDITOR`                  |
| `Tab` / `Ctrl+I` | Load prompt into the input widget for editing             |
| `Ctrl+J`         | Load older prompts (`+ace.page_size`, default +100)       |
| `Ctrl+K`         | Unload the last page, never dropping below the first page |
| `Ctrl+X`         | Toggle visibility of cancelled prompts                    |
| `Ctrl+Y`         | Copy prompt to clipboard and close the overlay            |
| `[` / `]`        | Cycle the Stash tab and History; Trash is remembered      |
| `Esc`            | Trash: back to the Stash list. Otherwise: close           |
| `q`              | Close the overlay when focus is outside a text input      |

`Enter` submits directly only when the overlay was opened from a History entry point
(`Ctrl+K`, `,.`, `,>`). When it was opened from a Stash entry point (`@`, `,@`,
`Ctrl+G p`, or the `stash:` chip) and you switch to History, nothing launches: `Enter`
and `Tab` load the prompt into the prompt bar as a draft, and `Ctrl+G` opens it in
`$EDITOR` and then loads the edited text into the bar.

### Filtering

Type in the search box to filter the prompts that have already been loaded. The grammar
is deliberately small: one optional **leading** `project:<value>` qualifier, followed by
an optional literal text substring matched case-insensitively against the prompt's
canonical or humanized text — the plain-substring behavior is unchanged when no
qualifier is typed. `project:` and its value are case-insensitive; a value ends at
whitespace, or use a double-quoted value (with `\"`/`\\` escapes) to include spaces. A
`project:` written anywhere other than the leading position is treated as ordinary
search text, not a qualifier. Write `\project:...` to search for literal text that
starts with `project:`.

The value resolves against every loaded project's canonical key, configured display
name, and registered aliases (including disabled projects and `home`) — never by
splitting a displayed basename or guessing from a Patch name prefix. A resolved scope
matches complete project identity (`project:sase` excludes `sase-core` and prose that
merely mentions "sase"); for a multi-prompt entry, any segment belonging to the project
is enough. An unknown value still matches a prompt whose own historical reference is
that exact unresolved text, so a deleted or renamed project stays searchable. A label
shared by more than one project is ambiguous and is reported in the helper line below
the filter box instead of matching either one silently; an empty or unterminated quoted
value is also reported there and selects nothing until fixed. The current scope (or the
ambiguous/malformed hint) is shown on that helper line; clearing the `project:` prefix
returns to searching every loaded prompt.

Press `Ctrl+J` to load older pages, `Ctrl+K` to unload the last page, and `Ctrl+X` to
toggle cancelled prompts on or off — when enabled, cancelled prompts appear in the
results with an `x` marker. The `project:` scope only ever considers prompts already
loaded into the overlay; it does not search the whole history archive.

Prompt-history rows are compact single-line entries: cancelled marker, last-used
timestamp (`MM-DD HH:MM` when parseable), a project column in the project's accent
color, macro/directive chips, and a first-line prompt preview. The preview panel shows
the full prompt, with `+<project>` tags in their project accent colors, and timestamp
metadata. History writes use a sidecar lock plus atomic tempfile replacement of monthly
shard files under `~/.sase/prompt_history/`, so concurrent agent launches do not
truncate prompt history. See
[TUI migration notes](../upgrading/tui.md#prompt-history-store) for the older
single-file store.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Prompt input](prompt-input.md) — insert mode, alt-brace, search, and macro editing.
- [Prompt stacks](prompt-stacks.md) — multi-agent panes, stash, and trash.
- [Find and replay a prompt](../../guides/find-and-replay-prompt.md) — History workflow.
- [TUI migration notes](../upgrading/tui.md) — prompt-history store.
