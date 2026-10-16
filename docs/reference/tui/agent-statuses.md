---
title: Agent statuses
description: Agent, wait, and completion statuses on the Agents tab.
---

# Agent statuses

This page lists every agent status shown on the Agents tab, plus decks, cards, and
finalizers.

## Agent Statuses {#agent-statuses-1}

Each row in the Agents tab displays a status label. The sections below separate labels
that represent execution, waiting, review, or a successor handoff from labels that
represent completed work. This is a display-oriented grouping: a gate turn can be
processless or already settled while its label still uses the Running bucket to
represent an in-progress handoff.

### Execution, Waiting, Review, and Handoff Statuses

Gate-turn rows use lifecycle presentation rather than a separate hard-coded color for
every plan or question label: pending/settling labels use the gate's configured or
deterministic accent, answered/completed/stopped labels turn grey, and
failed/timeout/lost labels turn red. Legacy non-turn rows retain their older status
presentation where noted, with specialized lifecycle labels falling back to dim text.
Presentation and bucket are separate: a grey settled gate can still appear in the
Running bucket when it handed off to a successor.

| Status            | Presentation                  | Description                                                                                                      |
| ----------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **RUNNING**       | Gold                          | Agent subprocess is executing                                                                                    |
| **QUEUED**        | Cornflower blue               | Cleared dependency, bead, and time waits; parked for runner capacity                                             |
| **WAITING**       | Amethyst/purple               | Paused on a dependency, bead, or time wait; `?N` marks unknown targets; matching bead tokens follow agent tokens |
| **WAITING INPUT** | Gate accent; legacy dim       | Workflow is paused at a human-in-the-loop (HITL) step                                                            |
| **TALE**          | Gate accent; legacy dim       | An authored tale is waiting for user review                                                                      |
| **EPIC**          | Gate accent; legacy dim       | An authored epic is waiting for user review                                                                      |
| **PLAN**          | Gate accent; legacy dim       | A legacy or unreadable-tier plan is waiting for user review                                                      |
| **PLAN APPROVED** | Grey on the settled gate turn | Plan approval was durably accepted; follow-up execution is being attempted                                       |
| **TALE APPROVED** | Grey on the settled gate turn | Tale approval and commit were durably accepted; follow-up execution is being attempted                           |
| **EPIC APPROVED** | Grey on the settled gate turn | Epic approval was durably accepted; creation is being attempted and no epic ID has been back-filled yet          |
| **QUESTION**      | Gate accent; legacy dim       | Agent is asking the user a question (via `/sase_questions`)                                                      |
| **ANSWERED**      | Grey on the settled gate turn | The answer was accepted and a successor is being launched                                                        |
| **SUDO**          | Gate accent                   | An agent's [sudo request](../automation/sudo.md) is waiting for review; it settles as `SUDOED` or `DENIED`                     |
| **RETRYING**      | Orange                        | Agent hit a retryable error and is in a countdown before retrying                                                |

Modern `/sase_questions` calls hand the session to a processless `QUESTION` gate turn
and end the asking LLM turn. The turn owns the durable question until it is answered,
cancelled, or times out, so dismissing its notification does not dismiss the session
state. An answer settles it as `ANSWERED` and launches the next ordinary session member
with the accumulated Q&A. That successor starts under the serial-session admission
exemption and becomes the session's occupied slot; it does not enter the runner queue.
The `Enter` shortcut can reopen the live question even when no unread notification
remains.

Approval labels are receipt-derived: they appear as soon as the accepted gate decision
is durable, without waiting for the selected command or successor launch to finish. If
that execution fails, the label changes to `PLAN FAILED` or `EPIC FAILED`, so an
accepted decision cannot hide a failed action. Commit-only plans are different:
`PLAN COMMITTED` appears only after the archive succeeds.

Older in-flight runs may still use a `pending_question.json` marker. Those compatibility
runs yield their slot while unanswered, then reacquire capacity in the same process and
can become `QUEUED` after an answer. sase's TUI continues to project that marker as
`QUESTION` until the legacy continuation resumes or terminates.

The keybinding footer renders available conditional actions as non-breaking key/label
chips. When the chips do not fit on one line, the footer switches to a deterministic
grid so narrow terminals and leader-mode action sets do not wrap in the middle of a
binding. Mode labels such as `LEADER` are pinned on the left, and the service status
indicator remains pinned on the right. The status is a segmented badge with a neutral
`SVC` label chip before the colored state chip, so the indicator always identifies the
service host it describes.

#### Service Health Pill

Once the first service-status snapshot loads, the `SVC` pill summarizes service health.
Proc states use the wire vocabulary the core emits (`running`, `unavailable`,
`disabled`, `stopped`, `crash_loop`, `backoff`, `exited`): `crash_loop` and `backoff`
are failures, `exited` is a failure while desired state is running (a clean give-up
reads as a warning), `unavailable` is a warning, and `disabled` or an operator-stopped
proc is muted rather than a failure.

| Pill      | Color  | Description                                                                                                                      |
| --------- | ------ | -------------------------------------------------------------------------------------------------------------------------------- |
| **`N/M`** | Teal   | Healthy: `N` of the `M` counted service procs are running (enabled procs whose desired state is running or that are unavailable) |
| **`!`**   | Red    | Unhealthy: the service host is stopped or stale, or a counted proc is unavailable, crash-looping, backing off, or exited         |
| **`?`**   | Yellow | Unknown: no service-status snapshot could be read (`service status unavailable`)                                                 |

When health is unhealthy, sase's TUI also raises a `Services unhealthy: <reason>`
warning toast (for example `host stopped`, `host stale`, or `gateway unavailable`), and
raises it again whenever the underlying service status changes while health stays
unhealthy. A host that is still `starting` is not a failure; a host whose heartbeat is
`stale` is a failure distinct from `stopped`.

The health pill replaces the host-state labels below as soon as the first status load
finishes. When no snapshot could be read the pill shows a yellow `?` (unknown) instead
of a healthy count. The labels are therefore only visible briefly at startup, between
the startup stopwatch retiring and the first status load; `-R` / `--restart-service`
restarts the host after that load, so the pill keeps showing health rather than
RESTARTING:

| Status         | Color         | Description                      |
| -------------- | ------------- | -------------------------------- |
| **RUNNING**    | Green         | Service host is running normally |
| **STOPPED**    | Red           | Service host is not running      |
| **STARTING**   | Yellow        | Service host is starting up      |
| **STOPPING**   | Yellow        | Service host is shutting down    |
| **RESTARTING** | Deep sky blue | Service host is restarting       |

During TUI startup the footer slot shows a live **starting** stopwatch with a rotating
glyph in place of the host status, ticking at ~10 Hz until the TUI finishes mounting and
the real host status resolves. The background color turns from its normal tone to a
slow-startup tone once the elapsed time crosses the slow threshold, giving immediate
visual feedback on cold-start latency. A safety timeout forcibly retires the stopwatch
if the mount signal never fires.

### Completed Statuses

The ordinary-row renderer reserves green for plain `DONE`; specialized terminal labels
fall back to dim text unless a gate or monitor supplies lifecycle presentation.

| Status             | Presentation                          | Description                                                      |
| ------------------ | ------------------------------------- | ---------------------------------------------------------------- |
| **DONE**           | Green                                 | Agent completed successfully                                     |
| **PLAN DONE**      | Dim                                   | Plan workflow fully completed (all steps)                        |
| **TALE DONE**      | Dim                                   | Tale plan workflow fully completed (all follow-ups)              |
| **PLAN COMMITTED** | Grey on a settled gate; otherwise dim | Commit-only plan was archived successfully                       |
| **EPIC CREATED**   | Dim                                   | A created epic ID is known, or a legacy epic follow-up completed |
| **FAILED**         | Red                                   | Agent exited with an error                                       |
| **PLAN FAILED**    | Red                                   | Accepted plan action or archive failed                           |
| **EPIC FAILED**    | Red                                   | Accepted epic-creation action failed                             |

Monitor turns are the exception to this status table's success-oriented labels: a
gate-approved epic monitor uses `EPIC APPROVED` as its start label and `EPIC CREATED` as
its stop label for every terminal state. A failed, timed-out, stopped, or lost monitor
can therefore display `EPIC CREATED` in its state-dependent color. Inspect the monitor
state, bucket, exit code, and output; on the planner row itself, `EPIC CREATED` means
the created epic ID was successfully back-filled.

Completed agents can be dismissed with `x` on a single row, or through the `X` cleanup
panel for focused-panel, global, tribe, clan, marked, group, and custom planner-backed
selections. `DONE`, `PLAN DONE`, and `TALE DONE` rows with a saved response path are
resumable from the Agents tab.

When a terminal agent becomes unread, sase's TUI marks it with the completed-agent
indicator and includes it in the Agents header unread count. Selecting that row, jumping
to it with `,j`, or toggling it back to read with `U` acknowledges the row and dismisses
the matching user-agent completion notification. Manually marking a row unread with `U`
arms it for normal acknowledgement after you move away and return, so the marker can be
used as a short-lived reminder without leaving stale inbox entries.

If the currently focused row finishes while you are already on the Agents tab, sase's
TUI still marks it unread and keeps the completion notification active until a real
navigation or selection event acknowledges it. A refresh that merely preserves focus
does not silently consume the unread marker.

The `unread` count in the Agents header is drawn as black text on a gold pill so the
"you still have unseen completed work" signal stands out from the rest of the colored
metrics. It uses the same gold as the inbox's `✉` general-notification chip in the top
bar, giving you a single color to scan for.

Switching to the Agents tab does not bulk-dismiss completion notifications. sase's TUI
projects active completion notifications onto unread rows, then acknowledges rows one at
a time when you select or navigate into a terminal unread row. Bulk acknowledgement is
explicit through `,u`. That command marks every loaded unread completed agent read: rows
on every Agents tab, members of collapsed clans and tribes, and rows that belong to a
query which is not the visible tab. Clan containers, session members, workflow children,
monitors, gates, and named procs stay out of the set, and the gold unread pill counts
the same rows, so the toast count matches the header. The toast reads
`Marked N completed agents read · press ,u within 10s to undo`. With no new unread
completions, press `,u` again within those 10 seconds to restore the marked agents that
are still loaded and terminal (`Restored N completed agents unread`). A newly unread
completion cancels the undo; the next `,u` marks the current unread set read instead.
When nothing is unread and no valid undo remains, `,u` reports
`No unread completed agents`. This undo belongs to the current TUI session. Plan
approvals and user questions are never auto-dismissed by this flow; they always require
explicit `y` / `n` confirmation from their respective modals.

### Agent Revival

Press `!R` on the Agents tab to revive previously dismissed work. sase's TUI opens the
saved-group revival modal first, showing newest saved groups with a right-hand preview
of included agents, projects, PRs, statuses, provider/model labels, and revival count.
Select a group and press Enter to revive it, choose **Load more saved groups...** to
page older groups, or choose **Browse the Archive** to read dismissed runs on the Agents
tab. Archive rows open read-only; press Enter on a run when you want to restore it to
the Inbox.

Use `m` to mark related Agents-tab rows and then `s` to save and dismiss them as a
group. The save modal accepts an optional human name. Leaving it blank keeps the
generated display title, such as "3 agents from @review" or "2 agents in auth_retry".
Saving a marked group hides the selected rows from the normal Agents tab without killing
running processes. When a marked top-level workflow row has child rows, sase's TUI also
includes the children in the saved group so revival can restore the original tree.

Dismissed agents are saved as individual bundle files under month shards in
`~/.sase/dismissed_bundles/YYYYMM/` and can be restored later. Saved group metadata
lives under `~/.sase/dismissed_agent_groups/` and stores stable references to those
bundle files plus the optional group name, status counts, projects, PRs, model/provider
metadata, and tribes. There is no limit on the number of dismissed agents or saved
groups that can be stored.

Dismiss operations are O(1) per agent: each agent is saved to its own JSON file rather
than a monolithic store. Parent workflow rows use `<raw_suffix>.json`; workflow children
use `<raw_suffix>__c<step_index>.json`. sase's TUI keeps a SQLite summary index in the
dismissed-bundle directory so Archive restore and internal lookups can list dismissed
agents without opening every bundle. Use `sase agent archive verify` to check that
maintenance index, or `sase agent archive rebuild-index` to rebuild it from bundle
files. The index stores metadata such as status, name, project, model, provider,
workflow, and Patch metadata; it is not a full-text copy of agent chat contents.

Revival removes the agent identity from the dismissed set, restores enough artifact
files for sase's TUI to rediscover the agent, and preserves the dismissed bundle as
historical recovery data. Saved-group revival skips missing bundle references with a
warning and restores the remaining agents. Group metadata is not deleted after revival;
sase's TUI marks the group with `revived_at` and increments `times_revived` so the modal
can show previous use. The reload path forces a full-history scan and can hydrate the
just-revived row directly from the bundle, so agents still appear after revive even if
the persistent artifact index was empty or stale.

Every revival also writes structured events to `~/.sase/logs/events.jsonl` (start,
per-agent success, per-agent failure). Read them back with `sase revive-log` — see
[Agent revive log](../agent-revive-log.md) for the record schema and CLI flags.

#### Legacy Dismissed-Name Prefix

Current dismiss and revive operations preserve stored agent names, per-agent tribes, and
top-level/workflow-child identity. Bare `%wait` (no target) skips dismissal-prefixed
candidates so it anchors on a live, visible agent. See
[TUI migration notes](../upgrading/tui.md#dismissed-name-prefix).

### Agents Deck Picker

On the Agents tab, `p` opens a small centered deck picker for the focused deck panel.
One more keypress picks the deck directly: `m` Main, `f` Files, `t` Tools, `n` FINAL,
`r` RECORD. Pressing the opener again (`pp` with the default binding) switches the
focused panel to the last deck that panel showed, or to the cycle-previous deck when
that panel has no history yet, and closes the picker. The return row names the
destination and badges it `last deck` or `previous`. `Esc` and `q` close without
changing anything. `j`/`k` move the highlight (wrapping across the return row and the
five deck rows) and `Enter` picks the highlighted row; any other printable key is
swallowed so nothing leaks through to the tab. History is one deck deep per panel,
updated by every real deck change (picker letters, palette jumps, `Ctrl+N` / `Ctrl+P`,
and a capital letter that changes the other panel), and restored with the deck layout.
The picker heading names the focused panel (`deck panel` single, `top` / `bottom` or
`left` / `right` in a split, `zoomed` while zoomed), each deck row shows its letter,
glyph, count, and whether it is already showing (or shown in the other split panel), and
the palette offers the same jumps as
`Show <Main|Files|Tools|FINAL|RECORD> deck in focused panel` plus
`Show last deck in focused panel`. The Agents tab always shows
[agent data decks and cards](#agent-data-decks-and-cards); see
[TUI migration notes](../upgrading/tui.md#keymap-moves). The
in-picker deck letters are fixed and not configurable. `p` keeps its unrelated Artifacts
project-scope meaning on the Artifacts tab.

The capital deck letters (`M` / `F` / `T` / `N`) show that deck in the most recently
focused other panel instead of the focused one. When the opener is a single letter, its
capital (`P` by default) shows the same resolved return deck in the other panel, with
the existing split and zoom rules. From a single panel they open a new panel below
(top-bottom) showing the picked deck; in an existing top-bottom or left-right split they
target the MRU other panel and keep the layout as is (a left-right split is never
rotated). While zoomed, the zoom ends first, the way `Z` ends it, and the split comes
back in its original orientation (or a new bottom panel opens when the zoom came from a
single panel). Focus always stays on the panel the picker was opened from, unlike `\`,
which moves focus into the new panel; `Ctrl+F` moves it if you want. A muted hint line
at the bottom of the picker names the MRU target with its position glyph (for example
`show in the ◲ bottom-right panel`) and says where the capital letter will go. Picking a
capital letter for the deck the other panel already shows changes nothing. `Enter` and
mouse clicks keep their focused-panel meaning. The palette offers the same jumps as
`Show <Main|Files|Tools|FINAL|RECORD> deck in other panel` plus
`Show last deck in other panel`.

### Agent Data Decks and Cards

The Agents tab detail column shows one to three deck panels between the sticky header
panel and the jump panel. Each deck panel shows one agent data deck, a named ordered set
of agent data cards about the selected node. `Ctrl+N` / `Ctrl+P` cycle the focused panel
through the Main, Files, Tools, FINAL, and RECORD decks (wrapping, nothing skipped), and
`p` opens the [deck picker](#agents-deck-picker) for a two-key jump to any deck (`pp`
returns to the last deck, or to the cycle-previous deck when the focused panel has no
history); `Ctrl+J` / `Ctrl+K` move to the next / previous card in the focused panel.

- **Main deck.** `Context` (details and prompt; the default card) and `Reply` — titled
  `Output` for named procs, monitors, gates, and workflow steps — plus a leading
  `TRACEBACK` section at the top of Reply when the agent failed. Clan rows and
  whole-panel tribe focus show a single `Summary` card instead. A paged deck keeps the
  card last chosen with `Ctrl+J` / `Ctrl+K` (for example Reply) as the selection moves
  between nodes.
- **Files deck.** One card per file page (commit diffs, the live diff, linked-repo
  diffs, then extra files), titled by file. The default card is the same default page
  the file view always chose.
- **Tools deck.** Two cards: `⚒ Runs` first, then `LLM Calls` (see
  [Agents Tab Tool Runs](agents-deck-panels.md#agents-tab-tool-runs) and
  [Agents Tab LLM Calls Panel](agents-deck-panels.md#agents-tab-llm-calls-panel)). The Runs card exists only
  when the selected node has at least one tool run. The default card is the panel's
  sticky Tools preference when it names a card that exists, otherwise Runs, otherwise
  LLM Calls — so a reader who prefers LLM Calls stays there. Tools is paged-only: it
  never spreads, `P` stays a no-op, and there is no deck-view badge. The border
  subtitle's Tools segment reads `tools ⚒N M` (N runs, M LLM calls; `tools ⚒N` when
  there are no calls), bold accent while a run is live and red while one is silent.
- **FINAL deck.** The `⊛ FINAL` deck shows how the selected node's turns landed: an
  `Overview` card plus one card per finalizer instance (see
  [Finalizers on the Agents tab](#finalizers-on-the-agents-tab)).
- **RECORD deck.** The `≡ RECORD` deck shows the selected agent's recorded facts in four
  cards, always in this order. `Lifecycle` shows its reference or name, location (Inbox
  or Archive), status, recorded times, and Viewable, Restorable, and Restartable
  capabilities. `Provenance` shows the project, workspace, model, agent tab, tribe,
  owner, chat path, artifacts directory, and bundle path when available. `Relations`
  shows session, clan, parent, workflow, retry, and container members as agent
  references, falling back to stored identifiers when names cannot be resolved, or
  `No relations`. `Links` groups artifact links by direction (Outgoing, Incoming,
  Related) **and relation**, showing up to three neighbors for each group plus a
  remaining count, or `No artifact links`. Missing data is omitted or shown as
  unavailable. The deck works for Inbox agents, clan containers, agents with limited
  metadata, readable archived agents, unreadable archive entries, and Archive
  containers. `Ctrl+J` / `Ctrl+K` cycle its cards, and it is reachable only explicitly
  (`p r`, the palette's `agents.show_deck.record`, or `Ctrl+N` / `Ctrl+P`, where it sits
  last in the cycle): new split panels never auto-choose it.

A multi-card deck renders **spread** — every card on one scrollable page separated by
titled rules — when its cards fit within `ace.agent_decks.spread_max_screens` panel
viewport heights (default `1.5`; `0` means always paged), and **paged** — one card at a
time — otherwise. In spread mode `Ctrl+J` / `Ctrl+K` scroll the next / previous card's
header to the top. The deck panel's border title names the deck, its
[deck view](#deck-views) badge (Main and Files decks only), and its cards with the
active card highlighted (and an `N/M` position when there is more than one card); the
border subtitle is a `main · files · tools · final · record` switcher showing each
deck's card, file, run/call, or finalizer count when known, dimming decks with no
content. A deck with no content for the selection shows an empty-state card instead, so
the layout never jumps.

#### Deck Views

Each Main and Files deck panel has a **deck view**: `spread` (every card on one
scrollable page), `page cards` (one whole card per page), or `page blocks` (one card
block per page). The view is normally **automatic** — resolved from the content through
the `ace.agent_decks` spread thresholds — or **fixed** to one layout by you. The Tools,
FINAL, and RECORD decks have no views: they always lay out automatically and show no
badge. Deck views stay a Main-and-Files feature; FINAL's and RECORD's spread/paged and
block paging resolve automatically from the `ace.agent_decks` thresholds like every
other automatic deck.

**The badge.** The top border title shows the effective view right after the deck name,
for example `◆ MAIN  page blocks · auto` or `◆ MAIN  spread · fixed`. The layout word
uses the deck accent; `fixed` is bold accent while `auto` stays muted, so a fixed panel
stands out at a glance. On narrow panels the badge shortens (`cards`, `blocks`, `B·A`)
but never depends on color alone. No badge appears for the Tools, FINAL, or RECORD deck,
an empty deck, or a panel that has never painted a full Main document.

**`P` cycles the view.** `P` steps the focused panel's Main or Files deck wider
(`page blocks` → `page cards` → `spread`, wrapping) and pins the result as a fixed view.
The first press from automatic starts after the effective layout, so it always changes
what is on screen; layouts that would render identically for the current content are
skipped. `P` is unavailable when there is nothing to choose (a one-card deck, the Tools,
FINAL, or RECORD deck, an empty deck, or while a Main document is still partial). The
footer shows a `P view` entry and the help modal an `Agents › Navigation` row only while
the cycle is available. The first press that fixes a view posts one teaching toast
naming the palette reset; routine presses stay silent because the badge changes in
place. The badge and panel chrome repaint on the first frame after `P`; the Main body
for the new layout is built off the event loop and swapped in when ready, so on a very
long Reply the badge can lead the body by a moment.

**Palette.** The command palette offers `Cycle deck view` plus four direct choices:
`Deck view: automatic`, `Deck view: spread (fixed)`, `Deck view: page cards (fixed)`,
and `Deck view: page blocks (fixed)` (Main only — Files never pages blocks). Only
`automatic` returns a panel to automatic; `P` cycles just the three fixed layouts. The
choice equal to the current policy is hidden. A direct choice applies to the focused
panel's deck even when it changes nothing for the current card, since it also covers
future cards.

**Persistence.** Each panel keeps one view per deck (Main and Files), surviving card and
deck switches, splits, zoom, and restarts in `~/.sase/ace_agents_deck_state.json`. New
panels start automatic. A view change keeps the reader's place: the same card, block,
scroll offset, and pin survive in every direction.

**Files specifics.** A fixed `spread` on Files reads every page fully (capped per page,
with truncation hints, so nothing is silently dropped). While that read runs the deck
stays paged and the badge reads `page cards · spreading…`. Files with an image or video
can never spread: the deck stays paged with `page cards · spread unavailable`, keeps the
fixed preference for the next compatible selection, and toasts once when you caused the
change.

#### Card Blocks

Cards gain a third level — **deck → card → card block** — for the session Reply card. An
agent session's Reply card holds one block per concrete session turn (`AGENT (role)`,
`⚙ MONITOR`, `⋔ GATE` phases, matching the `SESSION TURNS` jump-panel roster); the
still-reachable legacy non-session `followup_agents` Reply path gets one block per
followup the same way. Every other card renders exactly as before.

**Newest-block landing and the triage loop.** Selecting a node lands on its newest
block, so the first thing you see is the latest turn's output. The working loop is: read
the newest block, press `(` to step one turn older, repeat, and press `)` to walk back
toward the newest. Block state is ephemeral and panel-local (kept per deck panel for the
current selection); changing nodes, toggling attempts, or losing a vanished block id
re-lands on the newest. While you sit on an older block and a new turn starts, the view
stays put and the newcomer only gains an arrival dot — a following view (sitting on the
newest block) advances to it automatically.

**Block-spread vs block-paged.** Only a card shown alone pages its blocks; a spread deck
always shows every block inline. A lone card renders **block-spread** (all blocks on one
page) when it fits within `ace.agent_decks.block_spread_max_screens` panel viewport
heights (default `1.5`; `0` means always one block per page), and **block-paged** (one
block per page) otherwise. Block navigation never flips the deck's own spread/paged
mode.

**The block rail.** Whenever a paged deck's active card has 2+ blocks, a one-row rail
sits docked under the Main deck panel's top border showing the session timeline:
roster-numbered entries with status colors, an accent pill on the active block, arrival
dots on unseen newcomers, and a `( ) blocks` key hint at wide widths. At its widest tier
the rail names the block mode just before the key hint: `page N/M` when blocks are
paged, `all N` when they are inline. Clicking an entry selects that block; in a spread
deck the rail stays hidden because the phase dividers already mark each turn.

**Keys.** `(` steps to the older block and `)` to the newer block (both wrap); in a
spread deck they top-align the target turn's header, in a block-paged card they swap the
page. The footer shows a `(/)` blocks entry and the help modal a matching
`Older / newer card block` row only while the focused card has 2+ navigable blocks.
`Ctrl+Shift+J` / `Ctrl+Shift+K` are not bound by default: in common terminal chains
(tmux + kitty included) they arrive as plain `Ctrl+J` / `Ctrl+K` and would cycle cards,
not blocks. If your terminal delivers them distinctly, bind them yourself as a personal
override of `prev_card_block` / `next_card_block` (see
[configuration](../config/ace-prompts.md#aceagentdecks) and the keymap settings).

`\` opens a second panel below the first (stacked) and `|` opens one to its right (side
by side); the new panel takes focus and shows the next deck with content, or a duplicate
deck when every other deck is empty or already shown. One rule governs the split keys:
`\` draws a stacked divider and `|` a side-by-side divider. If that kind of divider
already spans the whole area, the key erases it and the side you are on grows to fill
the space. Otherwise, with fewer than three panels, the key draws the divider through
the focused panel — the unfocused panel becomes the full-span main panel without moving
or resizing. With three panels, the key turns the layout instead. There are seven
geometries: single, two two-pane splits, and four three-pane T shapes with a full-span
main panel:

```
 single     R2 stacked    C2 side by side
┌──────┐    ┌──────┐       ┌───┬───┐
│  A   │    │  A   │       │ A │ B │
│      │    ├──────┤       │   │   │
└──────┘    │  B   │       └───┴───┘
            └──────┘
 R3 main-top  R3 main-bottom  C3 main-left   C3 main-right
┌──────┐     ┌───┬───┐       ┌───┬───┐      ┌───┬───┐
│  A   │     │ B │ C │       │   │ B │      │ B │   │
├───┬──┤     ├───┴───┤       │ A ├───┤      ├───┤ A │
│ B │C │     │   A   │       │   │ C │      │ C │   │
└───┴──┘     └───────┘       └───┴───┘      └───┴───┘
```

`Ctrl+T` turns any split, `Ctrl+Shift+D` (alias `Ctrl+X`) closes the focused panel, and
`Ctrl+Shift+F` / `Ctrl+Shift+B` (aliases `>` / `<`) swap the focused panel's session
with the next / previous panel in reading order. `p` plus a capital deck letter (`M` /
`F` / `T` / `N`) opens or fills the most recently focused other panel with a chosen deck
without moving focus (see the [deck picker](#agents-deck-picker)). `Ctrl+F` / `Ctrl+B`
move focus to the next / previous panel in reading order (split layouts only) and every
deck, card, scroll, search, and fold key acts on the focused panel. `}` / `{` grow /
shrink the focused panel (split layouts only). A new three-pane geometry needs about 8
rows by 40 columns per panel or the key is refused with a toast; shrinking the terminal
never closes a panel.

The `Ctrl+Shift` chords need the kitty → tmux CSI-u chain (kitty plus tmux with
`extended-keys-format csi-u`, and SASE requesting modifyOtherKeys mode 2 inside tmux);
in mode 2, tmux re-encodes pasted control characters (newlines arrive as `CSI 106;5u`),
and SASE's input driver decodes them inside bracketed pastes so pasted text arrives
intact. `>` / `<` / `Ctrl+X` always work.

The layout, split ratio, focus, node-rail preference, and each panel's deck, preferred
card, and deck views persist across restarts in `~/.sase/ace_agents_deck_state.json`.
See the [key tables](artifacts-tab.md#navigation) for the full deck keymap and
[configuration](../config/ace-prompts.md#aceagentdecks) for the spread setting.

### Finalizers on the Agents Tab

Host-owned finalizers (commit, check, tasks, plugin finalizers) run after the model
turn, and the Agents tab shows them at four zoom levels over one shared state
vocabulary: at a glance on the row, in context in Reply, to diagnose in the ⊛ FINAL
deck, and for authorship in the Overview card and `sase final status`. Every surface
agrees because glyph, word, and color for each state live in one mapping. The view is
read-only: there are no retry, cancel, or bypass controls.

**At a glance: FINALIZING rows and ⊛ chips.** While a node's finalizers run, its row
status word reads `FINALIZING` in the Running bucket. This is a presentation overlay
only: `agent.status`, buckets, ordering, filters, capacity, and row actions are
untouched. A `⊛` chip names the most severe finalizer state. On a session container the
chip considers only runs after the newest successful settled run, picks the highest
severity (failed > refused > interrupted > deferred > running), and appends
`k of n runs` when more than one run is in play. The collapsed header panel carries the
same signal as an activity chip (`⊛ finalizing · <id> · <label>`, or `⊛ declaration`
while the declaration turn runs). A clan whose lone running member is finalizing also
reads `FINALIZING`, while the `⊛` chip stays on the member row.

**In context: the ⊛ FINAL receipt.** Each turn's Reply phase ends with a short `⊛ FINAL`
receipt: one line per finalizer instance with its state glyph, per-instance detail (step
or op label, `attempt n/m` when retries are budgeted, failure reason or headline), and
duration. Success lines stay quiet; success with warnings gains a dim `⚠N` suffix
(detail lives in FINAL, never on the row), and failed or refused instances add a dim
reason line. When anything needs attention the receipt ends with a
`p n  open FINAL deck` hint. There is no receipt before finalization begins (the
`planned` phase), none for turns skipped by a plan handoff, and none for legacy runs
with no finalizer summary.

**To diagnose: the ⊛ FINAL deck.** Press `p n` (`p N` opens it in the other panel) or
cycle with `Ctrl+N` / `Ctrl+P`. The deck accent is rose `#FF87D7`; the count noun is
`finalizer`/`finalizers`. Cards are `Overview` plus one per selected finalizer instance,
and FINAL cards stick while `j`/`k` move (the status strip and subtitle carry the signal
instead). Every FINAL card on a session container holds one card block per turn that ran
finalizers, with the same roster-matched ids Reply uses; skipped and not-triggered turns
appear only in the ledger. The rail, `(` / `)`, and newest-block landing all work as on
Reply.

- **Overview card.** The run plan in DAG order with per-instance selection reasons,
  configured-but-unselected instances dimmed with their reason (`%final:!lint`,
  `%final:none`, not default), the declaration timeline, controller cycles (only when
  above one), drift, run-level diagnostics, the runs ledger, and pointers to
  `sase final status`.
- **Instance cards.** Why, trigger, and declared lines; one section per finalizer
  attempt with the latest (or failing) attempt expanded; operations with outcomes;
  structured steps; typed evidence (`sha`, `url`, `bead`); deduped diagnostics; and log
  and protocol hint targets for export and search.
- **States.** Planned `◌`, declaration/running `▶` (gold), success `✓` (green, plus a
  dim amber `⚠N` in deck and receipt only), failed `✗` (red), refused `⊘` (purple),
  deferred `⏸` (amber), not triggered / handoff-skipped `○` (dim), blocked / not reached
  `–` (dim), interrupted `!` (amber), unavailable `⚠` (dim amber). An interrupted or
  unavailable state never spins.
- **Live tails.** A running op shows a sanitized in-card tail of at most 12 lines, but
  only once the op has run longer than `ace.agent_decks.final_tail_delay_seconds`
  (default `5.0`; `0` renders immediately). The tail follows the newest run and latest
  attempt with an arrival marker, pauses while scrolled up, and refreshes on a 1 Hz tick
  that runs only while FINAL shows the selected agent's active finalization. Fast ops go
  straight from `▶` to `✓` with no tail.

**For authors: `sase final status`.** `sase final status [<agent>]` projects the same
run view the FINAL deck renders — reconciling the sealed plan, progress journal,
operation records, steps, and typed evidence — and prints it pretty (colored, default)
or as JSON (`-f json`). With `-d/--artifacts-dir` it reads finalizer artifacts directly.
Inside a SASE turn it defaults to the calling agent. See the generated
[`sase final`](../cli/final.md) page.

## Related

- [TUI hub](index.md) — all Agents tab reference pages.
- [Agents tab main deck](agents-main-deck.md) — main deck, zoom, and node rail.
- [Agent workflows](agent-workflows.md) — plans, approvals, holds, and retries.
- [TUI migration notes](../upgrading/tui.md) — dismissed-name prefix and keymap moves.
