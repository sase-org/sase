---
title: Query system
description: Editing, saving, and recalling queries in the sase TUI.
---

# Query system

This page lists how the sase TUI edits, saves, and recalls queries.

## Query System {#query-system-1}

### Editing Queries

`/` is the app-level query key on every Artifacts pane and on the top-level Agents tab.
Every pane with a filter session keeps a persistent idle filter row; `/` (or the local
`f`) focuses it for editing. On Agents, `/` (or `f`) opens the auto-hiding filter bar,
and `,/` starts forward inline deck search. Help is the app-level `?` on every tab.

| Context            | Default query key  |
| ------------------ | ------------------ |
| Patches            | `/` (or local `f`) |
| Stitches           | `/` (or local `f`) |
| Beads              | `/` (or local `f`) |
| Provider documents | `/` (or local `f`) |
| Files              | `/` (or local `f`) |
| Agents tab query   | `/` or `f`         |

The Services tab has no query editor. Its `?` help modal and the command palette both
still offer "Edit search query" there, but the action currently does nothing on
Services; use the tab's own filtering and navigation keys instead.

To save a query, prefix with `#`:

- `#3 "myproject"` -- save to slot 3
- `# "myproject"` -- save to next available slot
- `#3` (no query) -- delete slot 3

On Patches and the top-level Agents tab, these commands run inside the inline filter and
leave both the active query and editor session in place.

On first open, when `ace.current_project.seed_filters` is on and the Patches query
carries no `project:` / `+name` term of any polarity or depth, sase's TUI appends a
visible `project:<name>` token for the current project (the configured project name,
never the ProjectSpec key). An explicit term wins, including `NOT project:…` and a term
nested inside parentheses. The seeded token is session-only: it is not written to
`last_query.txt`. Press `p` and choose **All projects** to remove it. Submitting the
query from the filter bar keeps the token as yours and persists it.

### Saved Queries

Saved-query slots are kept separately for each Artifacts pane. On the Artifacts tab,
press `0` followed by a slot digit (`1`-`9`, then `0` again for slot 0) to load that
slot from the active pane's saved queries -- e.g. `02` loads slot 2. The active pane is
not switched; a slot saved for a different query dialect is refused with an error
instead of being applied. `Esc` or any other non-digit key after `0` cancels without
changing the query. Bare digits still select the corresponding visible Artifacts
sub-tab; the saved-query slot keys live behind the `0` prefix so the two never collide.

Press `*` on an Artifacts pane that supports saved queries to open the saved-query
chooser instead. Press a populated slot (`1`–`9`, then `0`), move with `j`/`k` or the
arrow keys and press `Enter`, or click a row. `q`/`Esc` closes the chooser without
changing the query. The chooser shows the saved query text and marks the active query;
an empty chooser also repeats the save syntax. The chooser is unavailable from the
Agents and Services tabs.

### Query History

| Key | Action                                |
| --- | ------------------------------------- |
| `^` | Navigate to previous query in history |
| `_` | Navigate to next query in history     |

Query history is available on every Artifacts sub-tab whose pane contract enables
`query_history`, including provider-backed document panes, and inside the top-level
Agents tab filter bar. Each pane has its own durable previous/next stack, and Help shows
the active pane's stack with the configured previous/next key labels.

See [`docs/reference/query-language.md`](../query-language.md) for the full query
syntax reference, including boolean expressions, status shorthands, property filters,
and searchable fields.

The live Agents query also has `stranded:true`, which matches owner rows whose bead
work is stranded. It is computed from the warm stranded-work view and stays on the
client side of query evaluation.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Filtering](filtering.md) — pane filters for Agents, Patches, Commits, Beads, Plans.
- [Global controls](global-controls.md) — keys, palette, command line, refresh.
