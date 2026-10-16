---
title: Finders
description: The Jump All modal, jump back, and the Node Finder in the sase TUI.
---

# Finders

This page lists the Jump All modal, jump back, and the Node Finder.

## Jump All Modal

Press `` ` `` (backtick) on any tab to open the Jump All Modal. It displays all entries
across Agents, Artifacts, and Services tabs with the same adaptive one- or two-character
hints used by current-tab entry jump. Completing an entry's hint switches to the
appropriate tab and focuses it.

Up to 62 entries use `0`–`9`, `a`–`z`, `A`–`Z`. Larger result sets use fixed-width pairs
from `00` through `ZZ`; a first character is consumed without closing the modal, and
uppercase characters remain case-sensitive.

| Key                 | Action                                                   |
| ------------------- | -------------------------------------------------------- |
| Hint                | Jump to the corresponding entry                          |
| `` ` ``             | Jump back to the previous position (see below)           |
| `Ctrl+D` / `Ctrl+U` | Scroll the entry list down / up                          |
| `Esc`               | Close modal (any other key that is not a hint also does) |

The modal groups entries by tab (Agents, Artifacts, Services) and shows contextual
information for each: PR names and statuses, agent names with running indicators, and
Axe routine/command labels.

### Jump Back

Both jump modals support a jump-back feature for toggling between two entries:

- **Backtick jump-back**: Pressing `` ` `` inside the Jump All Modal returns to the
  previous position, enabling quick toggling between two entries across tabs.
- **Apostrophe jump-back**: Pressing `'` twice (`''`) in the single-tab entry jump mode
  jumps back to the previously jumped-from entry. The footer shows a "JUMP" mode
  indicator with `' back` when a target exists.
- **Fast jump**: `Ctrl+O` runs the same current-tab jump-back path without painting
  hints first; when no jump-back target exists, it selects the first current-tab hint.
- **Forward jump**: After walking backward, `Ctrl+Shift+O` walks forward through that
  current tab's jump stack. Agents, Artifacts/Patches, and Services keep independent
  back and forward positions.

The single-tab variant (`'` apostrophe) shows entries only from the current tab with the
same hint-character navigation.

## Node Finder

Press `"` (quotation mark) on the Agents tab to open the Node Finder modal. It lists
every reachable sase node as a tree — clans, agent nodes, session turns (including
monitors and gates), workflow roots, workflow `agent` steps, and stand-alone named procs
— including rows hidden by collapsed folds, collapsed grouping banners, collapsed or
isolated tribe panels, and the Agents query. Jumpable live node rows carry jump hints;
Archive results below them use selection and `Enter`.

| Key                          | HINTS mode (default)                              | SEARCH mode (query focused)   |
| ---------------------------- | ------------------------------------------------- | ----------------------------- |
| `0-9a-zA-Z`                  | Complete a hint and jump, or set a pending prefix | Edit the query; live refilter |
| `Tab` / `Shift+Tab`          | Focus the query                                   | Back to HINTS, query kept     |
| `/`                          | Focus the query                                   | Types `/`                     |
| `Enter`                      | Jump to the highlighted node                      | Jump to the highlighted node  |
| `Ctrl+N` / `Ctrl+P`, `↓`/`↑` | Next / previous jumpable row (wraps)              | Same                          |
| `"`                          | Jump back (same as `Ctrl+O`)                      | Types `"`                     |
| `Backspace`                  | Cancel a pending prefix; otherwise swallow        | Delete a character            |
| `Esc`                        | Cancel a pending prefix; otherwise close          | Back to HINTS, query kept     |
| `PgUp` / `PgDn`              | Scroll the preview pane                           | Scroll the preview pane       |
| Any other key                | Swallow; the footer flashes `no hint ‹x›`         | Types                         |

The why-hidden glyph legend: blank means visible, `◆` you are here, `⊘` hidden by the
Agents query, `◌` hidden by `I` (until listed, shown as an `I hides K` chip), `▭` inside
a collapsed or isolated-away tribe panel, `≡` inside a collapsed grouping banner, `▸`
inside a collapsed fold.

"Hidden" covers folds, banners, panels, and rows the Agents query hides. Jumping to a
query-hidden node clears the Agents query (recorded in query history, announced with a
toast); restore it with the query-history keys. The one-line jobs of the sibling
surfaces: `'` jumps by hint on the current tab, `` ` `` jumps across all tabs, digits
jump roster members, and `"` in the finder jumps back.

A `◷ In Archive` section follows the live rows. It lists up to five dismissed runs from
this machine: the first five names in the Archive's day order when the query is empty,
or the five best fuzzy name matches once you type. While that list is loading the
section reads `Archive warming…` or `Searching Archive…`; an empty search result reads
`No archived name matches.`, and a loading or search error reads `Archive unavailable.`
The finder searches an already-warm Archive snapshot; if none is available when it
opens, the section fills in once the Archive warms while the finder stays open (it
rechecks on each keystroke and for about 15 seconds after opening). Select a result with
the arrow keys or `Ctrl+N` / `Ctrl+P`. Its preview reads `ARCHIVED RUN`,
`Dismissed on this machine · read-only`, and `⏎ opens the run in the Archive`. `Enter`
switches to the Archive and selects the run without restoring it. This replaces the
Archive query with `in:archive`; it does not add a name filter. The toast reads
`Node Finder · opening archived run · read-only`. Archive results carry no jump hints.

The preview sits beside the list. On a terminal at least 140 columns wide the list also
keeps a status column. From 100 columns up to that width the two panes split evenly and
the status column is hidden. Below 100 columns the preview stacks under the list. `PgUp`
and `PgDn` scroll the preview in both modes.

The preview paints from the snapshot taken when the finder opened. The highlighted row
shows its kind and name, a compact identity block, and a breadcrumb from the tribe panel
through ancestor names to the row (`@default ▸ parent ▸ name`). It also says whether the
row is visible, and what `Enter` will do: `⏎ selects it` when the row is already
visible, or the reveals it will perform first (clearing the Agents query, opening a
hidden panel, opening a collapsed group, expanding folds) and then selecting it. A
session row lists its turns. A clan lists a status tally and up to twelve members, then
`… N more members` when the clan is larger. A monitor or named proc shows its command
and an output tail. A gate turn shows its label and state. A workflow root shows a
step-status tally. A non-node row says `Select a node to inspect it.`

Agent turns then fill two more sections from that turn's artifacts: a `PROMPT` head and
a `REPLY · tail`. A session container uses its newest agent turn for those sections and
labels the prompt with that turn's name. Clans, monitors, gates, and named procs stop
after the in-memory preview. The prompt and reply slots read `⋯ loading` until that read
finishes, then `(no prompt recorded)` or `(no reply recorded)` when the artifact is
empty. The reply tail names how many earlier lines were left off.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Tabs and panes](tabs-and-panes.md) — tab system and Artifacts panes.
- [Global controls](global-controls.md) — keys, palette, command line, refresh.
