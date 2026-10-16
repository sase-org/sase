---
title: TUI rendering
description:
  Tab bar display, file panel rendering, and the image preview foundation in the sase
  TUI.
---

# TUI rendering

Tab bar display, file panel rendering, and the image preview foundation used by the sase
TUI.

## Tab Bar Display

The tab bar renders plain tab labels (`Agents`, `Artifacts`, `Services`). Per-bucket
counts live inside each tab's body — for example the per-panel count summaries on the
Agents tab — rather than as suffixes on the tab title itself.

### Top-Bar Indicators

The right-aligned indicator cluster speaks the same visual language as the status-row
cluster beneath it (`load: 5/8 · model: opus@high · project: +sase`): every group
renders as a `<type>: <body>` group where only the `<type>:` label is dim, so a group's
value looks the same in full and compact modes, and visible groups are joined by a dim
`·`. The left-to-right order runs from activity to system state to launch routing to
personal queues: `tools`, `bg`, `updates`, `overrides`, `priority`, `disabled`, `stash`,
`inbox`. The always-visible `inbox` anchors the right edge directly above `project:`.
Labels are fixed strings that never pluralize. Count chips carry their identity glyph
inside the fill — `⚒` for tool runs (sky blue, red with `⚠` while silent), `⚙` for
background procs (blue) and bare monitors (orange), `⬆` for updates, `≡` for the stash,
`★` for priority — so compact mode (labels dropped together when the full cluster does
not fit in the cells left over after the tab strip and a 2-cell minimum gap; separators
kept) still identifies each group; widening restores full labels without oscillation.
Every group is clickable: tools opens Admin Center › Tools › Runs with all projects, bg
opens the Admin Center Procs tab, updates opens the Updates tab (or the Procs tab on the
running update while SASE is updating, when the badge shows its green gear inset, or the
Procs tab on the first restart blocker while a restart is queued, when the badge shows
its yellow gear inset), overrides, priority, and disabled open Launch settings, stash
opens the Prompts overlay on Stash, and inbox opens the notification modal. While SASE
is updating itself, the `updates` group shows a green `⚙` gear inset at its left edge.
While installed code waits for TUI-local tasks, submissions, or installation changes
before restarting ACE and the SASE service, it shows a yellow `⚙` gear inset instead
(green outranks yellow). Independent commands keep running. Durable operations started
from this TUI still finish their result handling first, within the same 60-second wait.
The yellow tooltip names the actual blockers and the time ACE restarts anyway; clicking
it opens the Procs tab on the first blocker. Feature-flag restarts never show the yellow
gear.

### Tools and Background Indicators

The `tools:` group shows every live `sase tool` run on the machine: a sky-blue `⚒ N`
chip for healthy runs, a red `⚒⚠ M` chip for silent runs (no activity for 60 s or more),
and an orange `⚙ K` chip for monitor turns not currently carrying a run. The `⚒` count
comes from the ToolRun ledger, so it covers every mode (escalated, detached, catalog,
monitor adopt/join, foreground) on every tab, ignoring the project filter, tribe
selection, and session; a live child folds into its live parent. An execution is drawn
exactly once: a proc that carries a live run is never drawn as a gear. Each chip hides
at zero and the group hides only when all chips are zero. Before the first glance load
the `⚒` chips stay hidden rather than showing a false zero; if loads keep failing the
last snapshot renders dim with a trailing `?`. Hover lists up to five runs (silent
first, then oldest) plus bare monitors; click to open Admin Center › Tools › Runs with
all projects.

The `bg:` group shows a filled blue `⚙ N` chip while sase's TUI own background procs are
running (e.g., sync, mail, accept, and notification-gate operations) — the same count
the Procs tab header shows in blue. Tool-run carriers never count here; they live under
`tools:`. Procs that are updating SASE move to the green `⚙` gear in `updates:` and no
longer count in the blue chip. The chip hides at zero. The group excludes service-host
rows — service procs and oneshots — which the Services tab reports instead. Hover for
the proc labels; click to open the Procs tab.

### Current Project Indicator

The uniquely colored `+<project>` chip is not in the tab bar: it is the project half of
the launch-context cluster at the right of each tab's status row
(`model: <launch default> · project: +<name>`). Clicking it opens the `+` launch picker.
See [Current project](../reference/tui/projects-tab.md#current-project) for what the
chip means, what it seeds, and how to turn each part off.

### Runners Modal

Press `,R` (leader + `R`) to open the runners modal. It shows concurrency information
including hook runners, agent runners, and a **Procs** section listing active and
recently completed TUI procs from the current sase's TUI session. These include Patch
actions, agent launch and cleanup work, `monitor-stop`, and notification updates. Each
row shows the target, proc type and status, and elapsed or total duration; a failed row
also shows its error message. This modal does not show proc output. Use the Admin
Center's [Procs tab](../reference/tui/procs-tab.md#procs-tab-1) or `sase proc show ID`
for durable records and captured output. Press `j` to paint hint keys over the rows and
jump to the matching agent or Patch; `Ctrl+D` / `Ctrl+U` scroll, and `r`, `q`, or `Esc`
closes the modal.

## File Panel Rendering

Agent files render in full and scroll natively in the file panel. Syntax highlighting
falls back to plain text for large content. Pathological outputs above the file-panel
safety limit show the first 5,000 lines and an explicit editor notice; press `E` to open
the complete content.

## Image Preview Foundation

sase's TUI renders PNG, JPEG, WebP, and GIF attachments with a Pillow-backed Rich cell
preview. The renderer decodes the first image frame, preserves aspect ratio within the
visible panel bounds, composites transparency, and paints colored half-block cells using
truecolor when the terminal advertises it and 256-color approximations otherwise.

Generated images are already attached to successful agent completion notifications and
recorded in `done.json` as `image_paths`. The Agents tab file panel and notification
modal route supported raster image attachments through this preview layer before
attempting text decoding. See [Agent attachments](../reference/agent-attachments.md) for
supported image extensions, guardrails, and current preview behavior.

## Related

- [TUI hub](../reference/tui/index.md) — all TUI reference pages.
- [Artifacts visual grammar](artifacts-pane-visual-grammar.md) — pane visuals.
- [Agent attachments](../reference/agent-attachments.md) — image attachments and
  preview.
- [TUI keymaps](../reference/tui/keymaps.md) — generated keymap defaults.
