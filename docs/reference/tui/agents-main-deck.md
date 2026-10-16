---
title: Agents tab main deck
description: The main deck view, detail zoom, and the node rail.
---

# Agents tab main deck

This page describes the Agents tab main deck, detail zoom, and the node rail.

## Agents Zoom and Node Rail

The left column has three presentations, derived from deck-area state: `EXPANDED` by
default, `RAIL` when the persisted `Ctrl+S` preference is set, and `HIDDEN` while a deck
is zoomed (`HIDDEN` wins over `RAIL`). The persisted preference only ever means rail;
zoom never writes it.

`Ctrl+S` toggles the node rail: the same tribe panels and the same visible rows at a
fixed 22-cell width, row for row, so a row never moves vertically. Each agent row
carries its glyph plus its name: the glyph cell (`?` needs you, `✗` failed, `▶` running,
`◐` starting, `○` queued, `◷` waiting, `✓` done, `Ø` user-stopped, plus kind glyphs for
monitors, gates, workflows, steps, and Patches) followed by the expanded row's identity
token. Nested names render relative to their parent (`.cld`, `--plan`), long names use a
middle ellipsis, and the width never fits to content, so the deck edge stays stable.
Color means urgency; the rail shows no runtimes, badges, or emoji. Settled-and-read
names render dim. Tribe titles are left-aligned (up to 18 cells), and the bottom border
counts off-screen rows (`▴N ▾M`).

Position is identity: rail row _k_ is expanded row _k_. Hovering a rail row shows that
row's full expanded text as a tooltip, the identity header always names the selection
(so `j` / `k` is never blind), and `'` jump hints plus the `"` node finder reach every
node. Focus stays on the list in rail mode, so every key works unchanged; runtime ticks
pause and catch up on expand. The footer shows `Ctrl+S expand nodes` while railed, and
the info row's `nodes i/N · Ctrl+S` chip is clickable. The `?` help modal's Node Rail
box lists the full glyph legend.

Each rail agent row ends with a right-aligned `×N` count in the shared count column and
a pip at the edge. `×N` means "folded, N inside": it shows only when the expanded row
shows `×N`, capped at `×99`. The trailing pip cell shows the marked `▪` pip when marked,
the unread `•` pip when unread and unmarked, and blank otherwise — marked always wins
over unread. Tree guides (`│` continuing, `└` terminal) prefix child rows and clamp at
depth 3. Banners keep the expanded prefix vocabulary with the label and a heavy (L0) or
light rule that is always at least 1 cell; folded banners add the `×N` count and a
1-cell urgency roll-up (`?` needs-you beats red `✗` failed beats gold `•` unread, else
blank). Collapsed tribe titles add their `×N` lane roll-up the same way.

`Z` zooms the focused deck panel in place: it snapshots the deck-area state (layout,
panels, focus, ratio), then shows only the focused panel with the node column hidden
entirely — no rail. The zoomed panel gets a heavy border in its own deck accent, a
reverse-gold `ZOOM` chip leading its title, and a restore hint (`◧ 1 of 2 · Z restore`
from a split, `Z restore` from a single deck) leading its subtitle. The info row shows
the same clickable `ZOOM` chip, then `Z restore`, then `node i/N` (`j` / `k` still moves
the selection); the footer shows `Z restore` while zoomed. The panel keeps its widget,
card, and scroll position, and search, `E`, cards, and decks all work normally while
zoomed.

A second `Z` restores the snapshot exactly, as does `Ctrl+S` while zoomed ("in zoom, any
sidebar key gives your layout back"). Using a layout key (`\`, `|`) while zoomed only
restores the snapshot, keeping deck and card edits made while zoomed, so no split is
ever silently lost.

## Agents Tab Main Deck {#agents-tab-main-deck-1}

The Agents tab Main deck shows structured information about the selected agent as
`Context` and `Reply` cards (see
[Agent data decks and cards](agent-statuses.md#agent-data-decks-and-cards)):

Pressing `V` on any local Agents-tab row (running or done) opens that same agent's
metadata full-screen in the [pager](pager.md) instead, as a sectioned document —
IDENTITY, MODEL, WORKSPACE, TIMELINE, CONTENT, SASE CONTEXT, and BEAD (skipping any that
would be empty) — with `/` search, `;` goto, `Ctrl+N`/`Ctrl+P` section jumps, and `y`
copy. `r` inside the pager re-snapshots the agent, which matters for a still-running
one. The pager also supports split panes (`\` below, `|` beside) — see
[Split panes](pager.md#split-panes). `V` is unavailable for remote fleet rows and when
no agent is selected; other tabs keep `V` bound to the Agent Run Log modal.

`Ctrl+J` and `Ctrl+K` move to the next / previous card in the focused deck panel
(wrapping). In a paged Main deck this swaps the visible card; in a spread Main deck it
scrolls the next / previous card's header to the top. The chosen card is the panel's
preferred card: on a new selection the panel shows the preferred card when the node has
it, otherwise the default card (`Context`, or `Summary` for clan and tribe documents),
while the preference itself is kept. Numbered roster rows (`SESSION TURNS`,
`CLAN MEMBERS`, `TRIBE MEMBERS`, `NEIGHBORS`) live in the jump panel and are not cards;
within a session container's `SASE CONTEXT` region, its lane sub-headings (`BEAD`,
`PLAN`, `ARTIFACTS`, `MEMORY`, `GLOSSARY`, `SKILLS`, `WORKSPACES`) are fold anchors, not
cards — `za`/`zA` still reach them when they own the viewport's top row. Roster rows are
also not `za`/`zA` targets and are not covered by `,/` search. The shortcuts act on the
focused deck panel, and changing agents or entering/leaving a pinned attempt view keeps
the preferred card.

- **Agent details**: Name, status, model, provider, Patch association, and
  chronologically sorted timestamps:
  - `Bead` — shown for agents launched by `sase bead work`; modern phase and task rows
    use explicit bead launch metadata, phase rows also use epic/plan metadata and
    validated plan frontmatter, and exact epic plus legacy phase/`.land` rows retain
    compatibility inference
  - `WAIT` — when the agent was spawned (waiting for a slot)
  - `BEGIN` — when runner admission completed, before workspace preparation for
    slot-participating user agents
  - `PLAN` — each plan proposal round (multiple entries when re-planning occurs)
  - `FBACK` — each time the agent requested feedback from the user
  - `QUEST` — each time the agent asked the user a question
  - `RETRY` — each time the agent entered retry state (retryable error)
  - `CODE` — when the agent began writing code
  - `EPIC` — when an epic follow-up agent was launched after plan approval
  - `DONE` — when execution completed
- **CLAN / MEMBERS**: Selecting a synthetic clan shows the orchid `CLAN` identity in the
  header and its `CLAN MEMBERS` roster in the jump panel. Layered clans follow
  dependency wave order as in the Agents tree; one-wave clans use launch order. Their
  foldable `WAVES` ladder shows one row per wave at every fold: collapsed rows carry
  label, pip, and members; expanded adds the `after` column with the same phrases as the
  roster group labels; fully expanded adds per-member `waits on` lines. It appears
  before the roster, or before the frozen summary in a detached live layout. Member
  numbers stay stable across status changes; rows show suffix, kind, status, model, and
  duration, with sequential session members indented. `Ctrl+J` / `Ctrl+K` move between
  Main cards, and row numbers jump to Agents-list members. At most 100 members are
  numbered.
- **SESSION**: Shown when a real multi-member session root is selected. The collapsed
  identity includes a `Models:` strip with each distinct recorded provider/model pair
  once, in first-use order. It uses one row normally and a second row before omitting
  entries; `+N more` counts hidden distinct models, and `d` expands to the complete
  uncapped list. Missing model facts have a separate unknown count. The share budget
  gives model rows space before the optional RAW PROMPT preview, including when the
  preview setting is `0`. The cyan kind label renders as the header panel title and the
  cyan `Name:` value matches the session row's identity block. The title is header
  chrome, not a card; the `SESSION TURNS` roster lives in the jump panel and is not a
  navigable section. On a session container, its `SASE CONTEXT` heading opens the
  Context card region; its per-lane sub-headings (`BEAD`, `PLAN`, `ARTIFACTS`, `MEMORY`,
  `GLOSSARY`, `SKILLS`, `WORKSPACES`) stay fold anchors only.
- **AGENT TURN**: Shown when a standalone sase agent or session member row is selected.
  The gold kind label renders as the header panel title and the gold `Name:` value
  matches the list-row name annotation. The title is header chrome, not a card. Monitor
  members and workflow step children (`bash` / `python` / `parallel`) do not get this
  heading.
- **Header panel**: The selected node's identity header (every field from the kind line
  through Timestamps, plus Fold where present) renders in its own always-visible panel
  at the top of the detail column, above the deck panels in every deck layout.
  Collapsed, it keeps the two chip rows — who and how on row 1, what and state on row 2
  — and previews the agent's `RAW PROMPT` below them as a card: a `RAW PROMPT` tab row
  over a rectangle on the Monokai code surface, so the prompt reads as one block apart
  from the metadata chips. Every card row carries the `▎` quote bar in the MACRO accent,
  which acts as the card's accent edge; hard-wrapped prose reflows into wrapped rows,
  hard breaks render as a dim `¶`, and the highlighting matches the expanded prompt. The
  card fills the panel width and shows at most three rows
  (`ace.agent_header.collapsed_preview_max_rows`), fewer when the
  `ace.agent_header.collapsed_max_share` height budget of a short column is tighter (`0`
  still turns the preview off and shows no tab). Session model rows count against the
  target before optional preview rows, and the tab appears only when at least one body
  row fits. On overflow the last prompt row ends in `…` and the border subtitle becomes
  `+N lines · ▾ d more` (`+1 line` when one line is hidden). `d` expands the panel to
  the full field list, complete model list, and `RAW PROMPT` under its own heading (or
  collapses it back). The kind label moves into the panel's border title in the node's
  accent color — `AGENT`, `AGENT TURN`, `SESSION`, `CLAN`, `WORKFLOW`, `STEP`,
  `GATE TURN`, `MONITOR TURN`, `NAMED PROC`, or, for a selected whole tribe panel,
  `TRIBE` — and the border subtitle shows what `d` will do (`▾ d more` / `▴ d less`,
  naming the configured `toggle_agent_header` key). The panel is hidden only for "No
  agent selected". `AGENT MACRO` no longer renders in the scrolling body and is not a
  `Ctrl+J`/`Ctrl+K` stop; `,/` still finds the user's words through `AGENT PROMPT`. A
  clan's collapsed rows mirror the tribe layout: name, status, and count chip on row 1;
  tribes, member totals, runtime, and the fold chip on row 2. Collapsed/expanded state
  is per session and holds across row moves, tribe focus, and layout changes. Hint mode
  never changes the panel's state: expanded, its fields and `AGENT MACRO` carry hint
  markers numbered first; collapsed, it keeps its normal preview, header content gets no
  markers, and numbering starts in the deck body. Attempt-pinned views never rendered
  `AGENT MACRO` and show no preview, and nodes without a macro show exactly the two chip
  rows inside the border. Deck search (`,/`) covers the focused panel's deck only, since
  header fields stay on screen.
- **Jump panel**: Every live numbered roster target (session turns, neighbors, clan
  members, tribe members) lives in its own always-visible panel at the bottom of the
  detail column, below the deck panels in every deck layout; the Main deck body does not
  contain these sections. The panel is shown only while the current document has
  numbered targets — never for "No agent selected", nodes without rosters, fully
  unnumbered rosters, or file-hint documents — and it stays visible during deck search
  (`,/`), since the digits keep working there. It is collapsed by default to at most two
  packed rows, where each visible number carries its roster label, shortened with a
  middle ellipsis only as far as it stays distinct from every other label (the packer
  shows fewer targets rather than ambiguous ones). When targets do not fit, the last
  cell is a dim `+N` count (with a lit `▶M` when `M` in-flight targets stay hidden);
  digits still reach every numbered target, including those counted in `+N`. In-flight
  targets fill the visible slots first, still in number order, and render lit in every
  view (see above). `.` expands the panel to the full roster sections, with their
  fold-driven annotations; expanded, it grows to at most 40% of the detail column,
  scrolls, and returns to its top when you select a different row. The border title is
  the color legend (`JUMP`, then one entry per section with its number range), and the
  border subtitle names the configured `toggle_agent_jump_panel` key (`▴ . more` /
  `▾ . less`). Each collapsed cell echoes its roster row: the number chip in the roster
  style, the label, and the status glyph; a dismissed neighbor renders dim with a `⊘`
  prefix (and an `archive` note when narrowed), since its digit opens the agent
  read-only in the Archive. After the first digit of a two-key jump, the panel narrows
  to the matching candidates (`JUMP · 1▁`, `esc cancel`), or shows
  `no targets start with <digit>`; completing or cancelling the jump restores the
  collapsed or expanded view. Collapsed/expanded state is per session and holds across
  row moves, tribe focus, and layout changes. Toggling never rebuilds the document, and
  a bottom-pinned body stays pinned. Roster headings are not cards; `za`/`zA` cannot
  target a roster section or roster row (rosters follow the global panel fold keys `zz`,
  `zZ`, and the direct level keys); and `,/` deck search does not cover roster rows.
- **SASE CONTEXT / BEAD**: Shown for epic phase workers and task workers. For an epic
  phase worker, the lane is limited to its selected phase. Its fields are `Phase Title`,
  `Description`, `Size`, `Epic Plan`, and `Epic Title`, in that order. The phase title
  comes from the same validated, frontmatter-ordered phase entry, is normalized to one
  line, wraps losslessly, and renders a quiet `unavailable` for missing, unreadable,
  damaged, or out-of-range entries. Exact validated sizes use literal blue `small`, gold
  `medium`, or rose `large` chips; missing/unreadable/damaged plans, explicit invalid
  sizes, and out-of-range phase ordinals also show a quiet `unavailable` size. Modern
  explicit phase metadata avoids bead-store reads. The parent goal, dependencies, and
  peer phases are never rendered, and the parent plan does not become a generic
  artifact. For a task worker, the fields are `Task Title`, `Description`, optional
  `Notes`, `Size`, optional `+1 Reports` / `+1 Evidence`, and `Created`. A multi-line
  `Notes` value (both bead types) or `+1 Evidence` value (task only) collapses to a
  one-line `N lines (zz to show)` digest at metadata fold level 1 and renders in full at
  levels 2-3; single-line values never fold.
- **SASE CONTEXT / PLAN**: Shown for the epic-authoring planner, epic lander, and task
  workers with a distinct authored plan when direct metadata or a confirmed legacy epic
  association resolves a plan. Phase workers deliberately omit the parent epic lane; no
  goal or peer roadmap phase is rendered. A task bead's own `design` field is never
  rendered as the task worker's `PLAN` lane. For plan-bearing roles, the body rows are
  `Title`, `Goal`, and canonical `Path`, in that order; a tale additionally gets a
  `Size` row between `Goal` and `Path` (the authored `xsmall`/`small`/`medium` chip, or
  a defaulted `medium` chip when the tale's `size` was missing or an over-sized legacy
  `large`/`xlarge` normalized at launch). The lane header carries the effective tier
  (`plan`, `tale`, or `epic`) and an epic's phase count. An `approve` action displays
  `plan`, `tale` and legacy commit-only actions display `tale`, and an `epic` action
  displays `epic`, even when the corresponding commit or launch later fails. Without
  action metadata, a valid authored tale or epic supplies the tier; legacy committed
  plans without a readable authored tier display `tale`, and unresolved values display
  `tier unavailable`. Canonical path selection remains separate: committed paths are
  workspace-relative, while pending or explicitly uncommitted paths use the
  home-shortened machine-local archive. Valid authored epics then show every phase in
  authored order with its title, fixed-width literal size chip, ID, dependency IDs,
  optional model, and optional description; these are static roadmap ordinals, not
  progress indicators. Launch-consumption validation normalizes only an omitted
  historical size to `small`; explicit invalid sizes remain unavailable. The chip stays
  visible while the title and every other value wrap without truncation in the normal
  panel and zoomed deck view, and logical text exposes the same labels to deck search
  and copy. Only the path participates in file hint mode. Invalid known epics show
  `phases unavailable` in the lane header without leaking partial entries; tales do not
  show a phase roadmap. A plan alone renders `SASE CONTEXT`; across every combination of
  present lanes, the full order is `PLAN`, `BEAD`, `ARTIFACTS`, `MEMORY`, `GLOSSARY`,
  `SKILLS`, then `WORKSPACES`, with absent lanes omitted once they resolve and
  still-resolving lanes holding their slot with a dim `resolving…` row.
- **SASE CONTEXT / GLOSSARY**: Shown directly after `MEMORY` whenever the selected agent
  or session has at least one audited event under the retired, pre-web
  `sase glossary read` command's legacy log. Current
  `sase memory read glossary:<keyword>` reads are not legacy events, so they surface in
  the `MEMORY` lane like any other memory read; this lane is purely historical (see
  [Memory Webs](../memory/memory.md#memory-webs)). That lane's hints open the requested memory
  files (see [Audited Reads](../memory/memory.md#audited-reads)). The lane header counts reads and
  distinct requested terms, adding the agent count for a multi-agent session. Each row
  shows the read's requested terms (truncated the same way `MEMORY` truncates paths),
  with a `+N related` suffix when the closure expanded past the requested terms, and the
  recorded reason on its own indented line. A numbered hint pages a generated report of
  that read's output — the reproduced command line, recorded metadata, and the resolved
  term closure. `@` opens the report and `%` copies its path; the report names the
  recorded `sase/sase.yml` source, since that legacy format predates the strand
  migration. Loading, attribution, and the mtime/size snapshot cache mirror `MEMORY`'s
  reference implementation; the lane is skipped rather than rendered empty when there
  are no reads to show.
- **SASE CONTEXT / ARTIFACTS**: The plan-adjacent lane groups `Beads`, `Reads`,
  `Commits`, `Deltas`, and `Files` as compact fields, preserves that internal order, and
  summarizes only the present fields in its header. `Beads` comes first and lists every
  bead the agent interacted with, newest first: each row shows the local time, one verb
  glyph, the full bead ID, an amber `▐CREATED▌` pill for beads the agent created (a
  standing close keeps its green/grey `▐CLOSED▌` pill priority and adds a compact
  `created` chip instead), and verb chips (`assigned` first for assignment-only rows,
  then durable verbs such as `noted` or `closed`, then `read`, then `viewed`; repeats
  render `×N`). Indented `↳` lines show the bead title when available, then a labeled
  `why:` filing-reason line for created rows (the bead's
  [creation reason](../work-units/beads.md#creation-reason)), then the standing-close reason and the
  newest audited read reason with explicit `closed:`/`read:` labels; rows with none of
  these omit `↳` lines. `assigned` marks the agent's assigned phase, epic, or
  `sase bead work` bead even when it was never touched (such rows show the
  already-resolved title when available, have no timestamp, and sort last); it never
  claims the agent created the bead. At most the newest five rows render; when there are
  more, a dim `+ N more · HH:MM earliest` footer reports the rest. A numbered hint opens
  the bead's live detail (the `sase bead show` view) in sase's pager, `%` copies the
  bead ID, and `@` is not supported for bead rows. Session rows add the producer label
  when every contributor to that bead shares one producer, and clan rows include their
  members' beads (de-duplicated and labeled per member). Audited `bead:` reads live here
  and are excluded from `Reads`. The data and glyphs match
  [`sase bead touched`](../work-units/bead-cli-query.md#sase-bead-touched-agent). `Reads` is the input side of
  the lane: each retained audited `sase artifact read` (including when artifact links
  are disabled) appears newest-first with local time, the canonical reference, the
  recorded reason on a wrapped continuation line, and — on a session row — the compact
  producer label. The header counts every retained read event; the newest five rows
  render and a dim `+ N more · HH:MM earliest` footer reports overflow. Repeated reads
  of the same reference stay separate. Prompt citations and silent `show` / `path` /
  `open` commands never appear. A read with a recorded resolved path participates in
  hint mode; a pathless or legacy row still renders its reference and reason, consumes
  no hint number, and never triggers live reference resolution. Commits persisted by the
  selected agent's post-run steps are grouped by repository; primary workspace,
  linked-repo, sidecar, and external-repo commits retain their repository identity.
  Deltas preserve their green `+`, gold `~`, and red `-` change glyphs and group linked
  or external files by repository. Artifact type remains visible through its icon shape,
  while every artifact icon, read row, and path uses the shared blue
  output-lane/file-path palette. This lane starts painting on the very first navigation
  frame: `Commits` is derived from the selected agent's in-memory step metadata and
  needs no disk reads, so it renders immediately, while `Reads`, `Deltas`, and `Files` —
  which do need store reads — fill in when the debounced enrichment resolves the lane.
  The immediate commit-only view is deliberately not cached, so the full lane still
  resolves on its normal schedule. An agent whose only artifact context is a read still
  gets `SASE CONTEXT` and an `ARTIFACTS` lane.
- **Slow tool calls**: The metadata header lists tool calls that took 20 seconds or
  longer, ordered by start time and capped at 8 rows (an overflow line points to the
  full [LLM Calls panel](agents-deck-panels.md#agents-tab-llm-calls-panel) timeline via `p` then `t`). Level
  1 is a compact triage table: every row keeps its timestamp, state, tool, duration, and
  a short path-, query-, or command-aware digest, while a dim tail reports that full
  commands are hidden. From position 2 upward, each row adds the complete command or
  target in an indented block that wraps with a hanging indent, plus start/end and
  outcome facts and any error. The lane's last position also adds output previews,
  subagent tool/token statistics, and each call's rank and share of selected slow time.
  These tiers are positional: an ordinary agent uses compact/detail/full across its
  three levels, while a session uses compact/full across its two. `za` and `zA` can
  change only this section. For a root agent the list aggregates calls across its
  children while attributing each call to the child that made it.
- **Wait state**: For a `WAITING` agent gated by `%wait`, a duration wait, or an
  absolute-time wait, the detail view shows a tagged `Wait:` block with one lane per
  active dimension: `[agents]`, `[beads]`, `[time]`, then `[capacity]`. Present tags
  occupy a padded gutter, so every value begins in one aligned column and long
  dependency lists wrap with a hanging indent beneath that value column. The `[agents]`
  lane lists the dependency names recorded on the waiting agent, adds per-name status
  badges for currently known agents, clan containers, or session containers, and marks
  unknown names with `?` so typos and stale references are obvious. When a waited-on
  target is followed into an epic it launched, the `[agents]` lane narrates the hand-off
  in place with a teal `↪`:
  `planner ✓ ↪ sase-7k ◐ in progress · 2/5 phases · since 14:32` while following,
  `↪ epic launching…` while the launch is in flight, or
  `↪ ! epic launch ended without an epic · resume: …` when blocked. A canceled or
  superseded followed epic shows its resolution in place of the status word. Followed
  epics are never repeated in `[beads]`; that lane lists only authored bead waits. The
  `[beads]` lane uses the same status-bearing token as the compact row, without a count:
  `run-bead ◐`, `done-bead ●`, and `bead-id ?` for an unknown bead. A WAITING list row
  keeps agent and bead counts independent while placing matching bead statuses after
  their present agent status (`▶1 ◐2`, `✓1 ●1`); unmatched bead tokens trail in bead
  order. Unknown targets can render as adjacent independent counts (`?1 ?2`). Timed-only
  and capacity-only waits do not receive those markers. Timed waits add compact
  duration, target time, and countdown text when available. An authored capacity on a
  `QUEUED` row shows as the same `cN` badge used elsewhere, and its detail context
  reports occupied capacity against that row's own admission budget. A `QUEUED` detail
  uses a separate `Queue:` line led by its rank and elapsed time since
  `slot_requested_at`, followed by cap context. It deliberately suppresses the marker's
  stale dependency, bead, and time-wait fields.
- **OUTPUT VARIABLES**: Small JSON-shaped values written by the selected agent session
  with `sase var set` and by `sase artifact create` (the SASE-managed `artifacts` list).
  Strings, numbers, booleans, null, lists, and nested maps retain their types. A single
  contributing agent renders as a flat sorted key/value block; multiple session members
  render with compact role labels so root, planner, coder, tester, and follow-up values
  stay attributable. Lists, maps, and multi-line strings use an indented YAML-shaped
  block with type-specific colors. The section is omitted when the session has not
  published variables. These values are stored in `agent_meta.json`, so they are visible
  metadata rather than secret storage.
- **TRACEBACK**: When an agent or workflow step recorded an error traceback, it renders
  under its own `TRACEBACK` heading after the prompt, directly above the reply heading
  (`AGENT REPLY` while running, `AGENT CHAT` once done or failed, or `STEP OUTPUT` for a
  workflow step), and is a `Ctrl+J`/`Ctrl+K` stop.
- **AGENT REPLY**: The agent's live or completed reply content, streamed from
  `live_reply.md` during execution and read from the artifacts directory after
  completion. When per-turn reply timestamps are available (recorded in
  `live_reply_timestamps.jsonl`), the reply is displayed with timestamp dividers between
  each agent turn. While the Agents tab stays on that row, one in-flight reply follows
  those two files in place. The Reply card replaces only that live reply body; the rest
  of the detail document stays put, and a change to those two files does not refresh the
  agent list. The followed row is a selected running agent that is still executing. On a
  sequential session, that is only the current in-flight turn, and only when that turn
  itself qualifies; otherwise nothing in that session is followed. A row that is not a
  sequential session follows the row itself, or the latest of its follow-up agents, when
  that candidate qualifies. Bash and Python workflow steps are never followed. The first
  paint of an empty solo reply says `Waiting for agent response...`. An empty session
  phase first says `No response content yet.`. The follow leaves that first-paint text
  in place until a timestamp chunk or reply text exists. If a reply that was already
  followed is cleared, the body becomes `Waiting for agent response...`. Hint mode keeps
  the first-paint text because the follow stays off. A change to either file schedules
  an update, and a status check of both files about once a second is the backstop. While
  the follow is idle, later updates are at least 0.3 seconds apart; the first update can
  be immediate. The follow waits while you are navigating or the prompt bar is open, and
  retries every 0.25 seconds. It stops for this row when you leave the Agents tab, when
  the detail view is pinned to one prior attempt number, or while hint mode is showing.
  Changing the selection cancels this follow; the newly selected row starts its own when
  it qualifies. `D` switches between the merged history and the current attempt only.
  That switch ends the current follow, and the view you land on starts its own when it
  still qualifies and no attempt number is pinned. If either file changes while it is
  being read, that snapshot is discarded and the follow tries again. For agents with
  follow-up phases (planner, feedback rounds, coder), the AGENT REPLY section
  consolidates replies from all phases into a single view with phase dividers showing
  each phase's label and start time. Phases follow the session's chain order: a monitor
  phase renders immediately after the turn that started it, including a monitor started
  by the session root, which renders after the root's own phase. Agent-turn members
  follow one rule, `AGENT (<role>)`, derived from the member's session role: `--plan`
  renders as `AGENT (plan)`, `--code` as `AGENT (code)`, `--epic` as `AGENT (epic)`,
  `--commit` as `AGENT (commit)`, and numeric feedback suffixes such as `--2` as
  `AGENT (plan round 2)`. Custom session members render the same way with their suffix
  token, e.g. `AGENT (bar)`. A monitor member is a named proc, so its phase renders as
  an amber `⚙ MONITOR` divider followed by the monitor's command, its recorded detail
  fields, and its full captured output — the same block the monitor's own panel shows. A
  gate-turn member renders as a lifecycle-colored `⋔ GATE` divider with its decision,
  kind, state, deadline, reason, request identity, branch policy, follow-up disposition,
  and captured command output. Its phase remains in the consolidated session reply after
  settlement, including terminal branches that intentionally launch no successor. Legacy
  dotted and single-dash suffixes render the same way.
- **WORKFLOW VARIABLES**: macro workflow output variables from step outputs with
  additional `meta_*` keys are grouped under a dedicated header. The special routing
  keys `meta_project`, `meta_patch`, and `meta_workspace` are promoted into the normal
  header fields; `meta_changespec` remains accepted as a legacy alias for `meta_patch`.
  Other metadata keys are title-cased and shown in this section.
- **PROMPT**: For agents launched from a multi-agent (`---`-separated) prompt, the
  final, planner, and question transcripts include a `PROMPT:` row linking the saved
  original launch prompt (stored under `~/.sase/.../multi_prompts/`), so the exact text
  that fanned out into every segment stays recoverable.

`g` / `G`, `Ctrl+D` / `Ctrl+U`, and the bottom pin act on the focused deck panel.

## Related

- [TUI hub](index.md) — all Agents tab reference pages.
- [Agents tab LLM calls and tool runs](agents-deck-panels.md) — call and run panels.
- [Agent statuses](agent-statuses.md) — agent, wait, and completion statuses.
