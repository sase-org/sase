---
title: Agents tab
description: Tabs, keys, lists, and actions on the sase TUI Agents tab.
---

# Agents tab

This page lists the Agents tab keybindings: tabs, navigation, actions, forking, refresh,
the wait modal, artifacts, and reproduction bundles.

## Agent Tabs

The Agents tab shows one agent tab at a time instead of the whole roster. A tab is a
presentation-only placement: it never changes where an agent runs, its identity, clan,
session, or tribe. Tabs come from each root's recorded tab (see
[Tab Directive](../macros/directive-syntax.md#tab-directive)): `%tab:<name>` authors a named tab, and roots
without one land on the default tab. The default tab is labeled `main`, or
`⌂ <machine name>` in machine mode (`ace.agent_tabs.machine_tabs`: `on`, or `auto` when
dispatch machines are configured), where `<machine name>` is the viewer's
`id.machine_name` (`⌂ local` when unset). In machine mode each remote machine gets its
own `⌨ <alias>` tab; `%tab:apollo` is still an ordinary named tab, distinct from
`⌨ apollo`. A remote alias literally named `local`, or equal to the local machine name
(case-insensitive), renders as `⌨ <alias>·remote`.

A tab exists while at least one visible root resolves to it, and the strip beside the
fleet status appears once two or more tabs exist (with a single tab the Agents tab looks
exactly as before). The active tab shows as a pill; inactive tabs show their label,
count, and only the non-zero attention tokens (`S`/`F`/`U`). Machine tabs carry a `⌨`
glyph whose label turns amber when its host is stale and red when it is invalid or
offline. The local machine tab carries a teal `⌂` home glyph instead. An arrival dot
(`•`) marks an inactive tab that gained a new root since you last visited it. At narrow
widths the strip compacts and then windows around the active tab with `‹N` / `N›`
overflow chips that open the tab picker.

`]` / `[` cycle tabs (wrapping, including overflow tabs). The palette entry
`Agents: go to tab…`, the `'` jump hints on strip chips, and clicking a chip or overflow
chip all switch tabs too. Every cross-tab jump switches to the target's tab first and
then reveals it: Node Finder searches all tabs and chips off-tab rows, `,j` / `,J`
consider every tab, and notification, link, monitor, run-log, and Files jumps all land
cross-tab. Choosing a tab while the All-tabs layout level is active drills into that
tab. Selection, folds, and sticky panels are remembered per tab, and the active tab
persists across restarts. If the active tab's last agent leaves, the tab stays selected
with an empty state until you navigate away; other empty states name a hiding query
(with a clear-filter hint) or an unavailable feed.

Bulk confirmations name their scope while the strip is visible: panel-wide actions and
the custom selector read `on <tab>` (for example `on sase`), `across all tabs` only at
the all-tabs scope, and a marked cleanup that spans tabs adds an
`N of M marked agents are on other tabs` line. Marks themselves stay global. Tab
styling, ordering, and machine-mode behavior live under `ace.agent_tabs` (see
`docs/reference/config/ace-prompts.md#aceagenttabs`).

Launching from a named tab inherits it: the prompt bar shows a `tab: <name>` chip and
the submitted prompt gains `%tab:<name>` (opt out with `%tab:main` or
`ace.agent_tabs.launch_from_view: false`). `gb` opens the Launch Tab picker to insert or
replace `%tab`. A launch that lands on another tab toasts its destination
(`blog-fix → blog`) and lights that tab's arrival dot. Move agents between tabs with
`sase agent tab list|set|unset` (see
[Moving agents between tabs](../../agent_sessions.md#moving-agents-between-tabs)) or the `N`
Tribe & Tab modal, which completes known tabs and applies optimistically with rollback;
rows owned by a remote machine cannot be moved. Filter the roster with the `tab:` query
field (exact match, or `main` for the default tab).

## Navigation {#navigation-1}

| Key                       | Action                                                                                                                                                           |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$$` / `$1`-`$9` / `$0`   | Follow the first / numbered artifact link, or open the complete links panel                                                                                      |
| _(palette)_               | Pick an agent tab from the command palette (`Agents: go to tab…`; same strip gating as `]`/`[`)                                                                  |
| `` ` ``                   | Jump to entry across all tabs (see [Jump All Modal](../../ace.md#jump-all-modal))                                                                                            |
| `0`–`9`                   | Jump from a selected clan, agent node, session member, or whole-panel roster to its numbered member or neighbor (live in the jump panel below the detail panels) |
| `o`, then `p`/`d`/`s`/`m` | Choose grouping mode: Project, Date, Status, or Machine                                                                                                          |
| `oo`                      | Step the Agents panel layout ladder forward, then close the grouping picker (see [Grouping Modes](agents-tab-grouping.md#grouping-modes))                                              |

> **Note:** `o` opens a direct grouping picker on the Agents tab. `o`/`O` still cycle
> the L0 grouping bucket forward / reverse on Artifacts panes that have a grouping mode
> (each surface keeps its own in-session mode). Beads has no grouping modes, and a
> provider document pane has them only when it declares `ref.grouping`, so the keys are
> a silent no-op on panes without modes; the same is true on the Services tab. The
> Artifacts open-externally verb moved to `E`; bang-mode `!o` still marks PR origin.
> `g`/`G` keep their conventional vim-style scroll-to-top/bottom meaning on every tab.
> See [Grouping Modes](agents-tab-grouping.md#grouping-modes) below.

The numbered `NEIGHBORS` rows use dotted agent-name relationships rather than Patch
sibling families. Relations are keyed on the name a row presents as its **sase agent**
name, so a session participates under its bare session name rather than its root
member's `--` name. The section shows visible ancestors and descendants plus neighbors
from every dotted hood that contains the selected sase-agent name — including the hood
that matches that name exactly. For example, `foo.bar.worker` lists peers under
`foo.bar` and cousins elsewhere under `foo`, grouped deepest hood first, and a session
`fam` lists `fam.helper` as a descendant while `fam.helper` lists `fam` back as its
ancestor. Dotless names can still have descendants such as `foo.child`. A digit jump
target is resolved by stable identity and revealed through any clan, session, workflow,
or grouping folds before focus moves.

When a clan or a sase agent is selected, its jump panel assigns a fixed number to each
numbered row, up to 100 targets. A sase agent is a multi-member session container or a
single agent; sase-agent panels number their `SESSION TURNS` roster (when present) and
then their `NEIGHBORS` section from one continuous ladder. Clan panels number their
`CLAN MEMBERS` roster and then their `CLAN NEIGHBORS` section from one continuous
ladder. A selected session **turn** row numbers its enclosing session's `SESSION TURNS`
roster the same way, listing every sibling except itself from the same ladder; a turn
row owns no sase agent, so it has no `NEIGHBORS` rows to follow the roster. Documents
with at most ten numbered rows use `0`–`9`; larger documents number the first 100 rows
with two-key values `00`–`99` and show any remaining entries as an unnumbered count.
Every live numbered target lives in the sticky jump panel below the deck panels, so the
digit answers stay on screen while the deck body scrolls. The deck body no longer
contains these roster sections. After the first digit of a two-key jump, the panel
narrows to the matching candidates; press `Esc` to cancel or any non-digit key to cancel
and continue with that key's normal action. A successful jump expands only the target's
ancestor chain, switches tribe panels when needed, and participates in the normal
`Ctrl+O` jump-back history. A digit on a dismissed neighbor opens that agent read-only
in the Archive instead of jumping. If the roster or the neighbor relationship changed
since the panel was drawn, the jump is cancelled with a warning rather than landing
somewhere stale.

Lit `▶`/`◐` targets get a softly tinted number/name/glyph pill in collapsed, narrowed,
and expanded views; `+N` counts hidden targets, with `▶M` for hidden in-flight ones.
Layered clan legends add dim `┊` dividers between same-row neighbors from different wave
groups, never at a row edge, and an `N WAVES` or `N WAVES + LAND` suffix, dropped first
when tight. Expanded `CLAN MEMBERS` entries label wave, land, and unresolved groups with
their dependencies.

## Agent Actions

When `t` opens the **Tmux Workspace** chooser, a displayed selector key opens that one
target immediately, even if other rows are already marked. `m` marks or unmarks the
highlighted row and advances to the next (wrapping around). `Enter` opens every marked
target in the chooser's displayed order, or only the highlighted row when nothing is
marked. `q` / `Esc` cancel without opening anything.

On Artifacts and Services, `r` still runs a Patch workflow or an Axe job/bgcmd, and `R`
still opens the [Refresh panel](#refresh-panel). Only the Agents tab swaps those keys.

### x: how a kill is carried out

`x` on a running agent hides its row at once and sends one SIGTERM from the TUI. The
rest runs in a durable `sase agent persist-cleanup` proc, which keeps going if you quit
the TUI. It publishes the dismissal first, then finds the agent's whole process set: the
runner's process group and session, its `ppid` descendants, and every process that
inherited the agent's launch scratch key (recorded as `launch_scratch_key` in
`agent_meta.json`), including ones that started their own session. It sends SIGTERM,
waits at least six seconds so a `sase tool run` wrapper can finish its own five-second
escalation, sends SIGKILL to whatever remains, and verifies every process is gone. Only
then does it release the workspace claim and delete workflow artifacts. A registered
proc or monitor supervisor found in the set is stopped through its own stop, so its
record settles. A dismissed row that is not success-terminal (for example a `FAILED` row
in retry backoff) is terminated the same way when its recorded runner is still alive.

If a process survives SIGKILL, the row stays dismissed, the workspace claim and
artifacts are kept, and an error toast names the surviving PIDs. `sase agent kill NAME`
runs the same termination in the foreground.

`x` on a running monitor, an active named proc, or a pending gate removes its row in the
same step. A running monitor goes through the ordinary kill confirmation and the durable
proc stops it before the other side effects. An active named proc or pending gate asks
for confirmation, then its row is hidden at once while the same durable bulk transaction
stops the named proc (through the native proc service) or cancels the gate. Clan, panel,
group, and marked cleanups include active named procs and pending gates the same way
instead of skipping them; any selected member the cleanup cannot cover is named in the
confirmation modal. A gate whose decision started executing under the cancel comes back
with an error toast. A gate that is already settling keeps the "waiting for a decision"
warning.

### Enter: act on an agent

`Enter` on an Agents-tab row opens that agent node's pending gate (every gate kind,
including plan, question, sudo, launch, HITL, and custom gates), jumps to its Patch, or
— when more than one target applies — opens a one-keypress chooser. One target runs
directly; two or more open the chooser. Gates come first, newest first, with the Patch
last; the first row is the primary action, so `Enter` then `Enter` always opens the
newest pending gate. The footer names what `Enter` will do: the gate's action (for
example `review plan`), `go to PR` for a lone Patch, or `choose action` when several
targets apply.

What counts as a target depends on the selected row:

- A **gate row** targets its own gate while it is pending. A settled gate toasts
  `This gate already settled (<state>)`.
- A **session container** collects every pending gate across its members, plus the
  session's Patch (or, when the container has none, the Patch of its most recently
  started member). A gate reachable through both a gate turn row and its inbox
  notification counts once, so a session waiting on a single tale plan, with no Patch,
  runs `Enter` directly (footer `review tale plan`); a session that also has a Patch
  shows the `choose action` footer instead.
- A **session member** or standalone agent targets gates it created and gate
  notifications matched to it. An agent stopped on a question, or a workflow step
  waiting for input, falls back to the answer flow when no gate notification matches.
- A **workflow step child** uses its parent workflow's Patch; a child of a project-level
  workflow uses that workflow's meta Patch, if it recorded one.
- A **remote row** answers its pending
  [remote attention](../automation/notifications.md#remote-attention) request.
- A **clan container** toasts `Select an agent inside this clan`. Monitors and named
  procs have no targets, and a grouping banner ignores `Enter`.

With no target, `Enter` toasts `No pending gate or Patch for this agent`. `Enter` works
from the first frame: if the notification inbox has not been polled yet, sase's TUI
reads it once off the UI thread and then acts. It searches every undismissed
notification rather than a bounded page, so older pending decisions stay reachable
regardless of backlog size. Before a gate opens, the target is revalidated; a gate that
settled in the meantime toasts `Gate <id> is no longer pending`.

The chooser is titled `Act on <agent>` and groups rows under `GATE`/`GATES` and `PATCH`
headings, each row showing its key, label, and a status badge (with age for gates). A
guidance line (`⏎ again → <primary action> · or press a key`) names the primary. Chooser
keys: one gate uses `g`; several gates use `1`–`9` in display order with `g` as a hidden
alias for the first; the Patch uses `p`. `Enter` selects the highlighted row (starting
on the primary), `j`/`k` or `Up`/`Down` move, `Esc`/`q` cancel, mouse click selects, and
other printable keys are swallowed. A choice whose target disappeared while the chooser
was open toasts `That action is no longer available` instead of acting.

The retired `,n` leader chord is replaced by `Enter`. The direct Patch jump survives as
the `jump_to_agent_patch` command, unbound by default; see
[`ace.keymaps`](../config/ace-keymap-configuration.md#acekeymaps).

## Forking Agents and Groups

With a named agent selected, press `F` to open a prompt prefilled with `#fork:<agent>`.
Selecting a session root uses the session name instead. Failed named rows are valid fork
targets; the child receives the failed parent's transcript plus the recorded failure
message when available. The same action works on the synthetic container row for a clan
(`#fork:<clan>`) and while an expanded or collapsed named tribe panel has whole-panel
focus (`#fork:@<tribe>`). The reserved `@default` panel and grouping banners are not
fork targets.

Finished planner rows (`EPIC CREATED`, `PLAN COMMITTED`) are also fork targets; a
session root forks its whole session, including the planner transcript and its
gate/monitor turns. `PLAN REJECTED` and `STOPPED` rows are not fork targets.

`F` also works on a stand-alone named-proc row and on a monitor session member, active
or settled. The prefilled reference is the proc's exact durable proc ID — not its
reusable friendly name — so the eventual fork can never drift onto a different proc if
that name is reused later; the footer and prompt label still show the friendly proc
name. A proc or monitor row has no chat, so it never advertises retry, edit-chat, or
`name`; `x` kills an active proc or stops a running monitor, and dismisses a settled
one.

Press `W` on the same selections to prepare `%w:<agent-or-session>`, `%w:<clan>`, or
`%w:@<tribe>`. A non-empty marked set takes precedence and produces one comma-separated
wait over the named marked rows instead of the focused group. The reserved `@default`
panel and grouping banners are not wait targets either.

Group references are dynamic; pressing `F` does not snapshot the selected transcripts. A
session reference contributes every known concrete turn in the session's sequential
chain, oldest first, agent turns and monitor turns alike, and includes turns that ended
unsuccessfully with their failure context rather than dropping them. Only turns that are
still running, or whose transcript/log is missing or unreadable, are listed as not
shown. Agent-turn members are transcripts of prior agents' conversations; named-proc and
monitor members are command execution records whose output is untrusted evidence, never
an instruction. An explicit `--<suffix>` reference contributes only that member. A clan
reference resolves the newest clan generation when the deferred launch proceeds and
requires every member of that generation to have succeeded. A tribe reference follows
the next-entity rule: the new run waits for the earliest successful entity in that tribe
launched after its own artifact was created. It does not fork the agents currently
visible in the selected tribe panel. See
[Tribe wait and fork targets](../../agent_sessions.md#tribe-wait-and-fork-targets) for the
full ordering rules.

sase's TUI also tries to carry VCS context into either prefilled prompt. For one
selected agent or session row, it uses that row's launch ref when it can resolve it. For
a selected clan or tribe, it adds a VCS tag only when every real agent in the current
scope resolves to the same workflow and ref. Mixed or missing context produces only the
`#fork` or `%w` reference, leaving you to add the desired `#git`, `#gh`, or other VCS
tag. A marked wait is different: one mark uses that row's context; multiple marks use
the selected marked row, or the first named mark when the selection is elsewhere. The
VCS lookup runs off the UI thread. Before opening the prompt, sase's TUI verifies that
the selected scope and its members did not change; marked waits instead verify the
marked target set. A stale selection cancels with a warning rather than opening a prompt
for the wrong target.

## Refresh Panel

Press `R` on Artifacts or Services, or `r` on Agents, to open the Refresh panel: a
centered single-key chooser that names every refresh sase's TUI can perform, shows how
fresh each target already is, and runs exactly one of them.

| Key | Aliases  | Option        | What it does                                                                     |
| --- | -------- | ------------- | -------------------------------------------------------------------------------- |
| `r` | `R`, `1` | This tab      | Reload the current tab's visible surface (Agents inbox, Artifacts, or Services). |
| `f` | `2`      | Full history  | Reload Agents from the complete archive. Works from any tab.                     |
| `u` | `3`      | Usage windows | Re-probe provider subscription limits.                                           |
| `a` | `4`      | Everything    | Forced sanity sweep plus full history and usage.                                 |

`R` is an alias for This tab, so a double-tapped `R R` on Artifacts or Services (or
`r r` on Agents) reproduces the old immediate refresh. `j`/`k` (or arrows /
`Ctrl+N`/`Ctrl+P`) move the cursor; `Enter` activates the highlighted row (This tab when
the panel opens); `Esc` or `q` cancels. The `,y` leader chord opens the same panel from
any tab with Full history highlighted and a `,y lives here now — press f` reminder, so
`,y` then `f` (or `Enter`) runs the full-history reload.

Each row shows a freshness chip from a reload requested in this session (`12s ago`,
`2h ago`, `just now`). A surface that has not been reloaded yet shows `—`, never a
guessed age. The usage row shows `checking…` while it looks up how many providers it can
refresh. When auto-refresh is enabled, a header line reports its cadence and the
countdown to the next tick.

If usage metrics are disabled or no providers are eligible, the usage row stays visible
but unavailable: pressing `u` explains why and leaves the panel open so you can pick
something else.

See [feature flags](../config/feature-flags.md#featureflags).

The dismissed projection that hides agents from the visible inbox is rebuilt from the
in-memory dismissed set _unioned with every dismissed-bundle summary_. Reviving an agent
now purges its dismissed bundle, so a revived agent stays visible. For archives that
accumulated stale bundles before that fix, plain `sase agent index gc` is **not** a
repair on its own -- it rebuilds the projection _from_ those lingering bundles and
re-hides the revived agents. Run `sase agent index gc --purge-revived-bundles` (`-r`) to
first delete dismissed-bundle files and summary rows for suffixes that are no longer
present in `dismissed_agents.json`, then rebuild the corrected projection.

When one or more agents are marked, `e` edits the marked set instead of only the focused
row. sase's TUI opens editable completed transcripts in visible row order, deduplicates
repeated paths, skips live marked rows that are still running or have no chat file, and
reports that live skip count. Stale marks are ignored for this action, and marks remain
in place after the editor exits.

## Wait Modal

Press `w` on the Agents tab to open the WaitModal. It has five editable fields —
**Agents**, **Beads**, **Time**, **Capacity**, and **Priority** — each prefilled from
the agent's current wait, plus a focusable **Follow epics** toggle row directly under
Agents. Time, Capacity, Priority, and Beads render a live preview of how the typed value
will be interpreted; an invalid Time, Capacity, or Priority value blocks apply and
focuses the offending field.

The **Follow epics** row is a tri-state toggle: `on` (teal `↪`), `off` (dim), or `mixed`
(each listed target keeps its own policy; newly added agents get the default). It joins
the `Ctrl+J` / `Ctrl+K` field cycle and `Space` toggles it when focused. When every
listed target is a `--plan` row the toggle is disabled with a reason, because `--plan`
rows release when the plan is submitted and never follow epics. Beads prefills with
authored beads only — beads a follow promotion derived are excluded. Applying the modal
writes the follow selection into the wait directive; removing a target, or turning its
follow off, drops its follow stage and its derived bead IDs while keeping the
already-pinned epic beads. Turning follow back on lets the next evaluation re-promote.

Beads completes against every non-closed bead in the agent's project, read from the same
canonical store the wait resolver consults, so a bead offered by the picker is always
one the resolver can see. The agent's own epic/phase bead is excluded from candidates —
an agent can never wait on the bead it exists to close. Candidates are ordered by status
(`in_progress`, `claimed`, `ready`, `open`, `snoozed`), then by most-recently-updated,
then by ID; the filter fragment matches bead ID or title. At most 100 rows render per
keystroke, with a trailing `…N more — keep typing` row when more match. A bead already
present in the field renders with a dim `· selected` suffix.

The Agents and Beads fields each have their own completion list directly beneath them,
but only one is ever visible at a time — whichever of the two fields was focused most
recently (Agents by default). Focusing Time, Capacity, or Priority never changes which
list is shown, and the hidden list is not part of keyboard focus traversal.

The beads preview reports one of: an empty-field neutral message, a loading message
while the bead catalog loads in the background, a neutral "bead store unavailable" state
when the project's store can't be read (IDs are not verified in that case), a valid
summary of up to three typed beads with their status glyphs plus an aggregate count, or
an error when a typed ID isn't in the project's bead store or is the agent's own bead.
Applying an error-state bead wait is a soft, two-step guard rather than a hard block:
the first `Enter` focuses the Beads field and changes the footer instead of dismissing;
a second `Enter` applies the wait as typed. Any edit to the Beads field disarms the
guard. A store that can't be read never arms the guard, since bead stores sync through
git and a locally-missing ID can still be valid upstream.

Behavior depends on the agent's status:

- **WAITING or QUEUED agent**: Edit dependency names, bead gates, a time floor, the
  per-launch `capacity` budget, or the runner-slot `priority`. A runner-slot-parked
  agent applies a capacity- or priority-only edit live on its next poll; changing
  earlier wait stages restarts the agent. Clearing an explicit capacity budget returns
  that launch to the current global `max_running_agents` budget.
- **STARTING or RUNNING agent**: Enter a dependency, bead gate, time floor, capacity
  budget, or priority to kill and restart the current agent with canonical `%wait(...)`
  / `%queue(...)` directives.

The **Capacity** field is this launch's capacity budget, replacing the current global
`max_running_agents` budget for its own admission decision. It is not a count of
individual turns. A serial session — including its monitor and `--next` follow-up —
still occupies one claim of its session weight, so that weight still counts against this
budget. Only a root or a live parallel clan member waits here; a serial session member
rides the session's slot and never parks.

Priority must be a non-negative integer and defaults to `10`; lower values are admitted
first. See [Runner slot waits](../runner-slots.md) for how priority interacts
with FIFO order and the bounded deference window applied to deprioritized waiters.

`Enter` applies, `Tab` accepts a highlighted agent- or bead-name completion and
otherwise moves focus to the next field, `Ctrl+R` runs the agent now by clearing every
wait condition, and `Escape` cancels. The modal supports readline-style keybindings
(`Ctrl+F`/`Ctrl+B`/`Ctrl+A`/`Ctrl+E`) for cursor movement.

`Ctrl+J` and `Ctrl+K` walk forward and backward through the six fields directly, in the
displayed order (Agents, Follow epics, Beads, Time, Capacity, Priority), wrapping around
at either end and placing the cursor at the end of the field's current value. Unlike
`Tab`, they never consume a highlighted completion, so they move focus even while a
completion list is open; when focus is on the Agents or Beads completion list itself,
the step is taken from that list's own field. `Up` / `Down` and `Ctrl+P` / `Ctrl+N` move
within the visible completion list rather than between fields.

## VCS Tag Resolution in Fork/Wait

When forking or waiting on an agent, VCS tags in the prompt (e.g., `#git(ref)`,
`#gh:ref`) are automatically updated to point to the correct branch. For non-project
agents, the ref is replaced with the agent's PR name (branch). For project agents using
`#pr`, the ref is replaced with `@<name>` which resolves to the agent's branch. HITL
suffixes (`!!`, `??`) are stripped during replacement since fork scenarios should not
carry over HITL overrides.

## Workflow Visibility

Workflows launched via `sase run` are visible in the Agents tab alongside sase's
TUI-launched workflows. The TUI scans `artifacts/run/*` directories in addition to
`workflow-*` and `ace-run` directories, and writes an initial `workflow_state.json`
before execution so that step data appears immediately rather than showing a bare
RUNNING entry. Anonymous `tmp_*` workflows are included in the normal visible-inbox
index when their workflow state has `appears_as_agent: true` and does not set
`hidden: true`; explicitly hidden workflow rows are omitted from the default view.
Specialized review runners launched by axe (mentor, CRS, fix-hook, and summarize-hook
review agents) are also visible and are automatically grouped into tribe `@review`,
matching the behavior of a `%id(..., tribe=review)` prompt launch.

## Agent Artifacts

Press `a` on a focused agent to open the artifact panel whenever artifacts are
associated with that agent. The list can include chat transcripts, plan files, generated
Markdown PDFs, generated images, generated videos, prompt-referenced media from saved
prompt artifacts, and explicit files saved with
`sase artifact create -p <path> [-l <label>] [-k <kind>]`. sase's TUI always opens the
panel, even for a single artifact, so the label, kind, and path are visible before
launching the terminal viewer. With agents marked, `a` opens one combined panel listing
every marked agent's artifacts, each row labeled with its agent's name.

The prompt/detail header includes those non-chat entries in the plan-adjacent
`SASE CONTEXT` `ARTIFACTS` lane. Within that lane, `Beads`, `Reads`, `Commits`,
`Deltas`, and `Files` stay in that order when present. `Beads` lists the beads the agent
touched, read, or viewed, plus its assigned beads (see the Main deck description below);
audited `bead:` reads appear there rather than under `Reads`. `Reads` lists audited
`sase artifact read` invocations (newest first, with reasons); prompt citations and
silent `show` / `path` / `open` inspection do not appear. Paths are made
workspace-relative when possible, and hint mode assigns numbers to filesystem-backed
reads and output paths so they can be opened with the normal file-hint flow.

Artifact panel controls:

| Key         | Action                                                               |
| ----------- | -------------------------------------------------------------------- |
| selector    | Open the artifact with that one-key selector (`1`-`0`, then letters) |
| `q` / `Esc` | Close the panel                                                      |

The modal-local file palette offers `@` prompt-form references, `l` Markdown links, `c`
Markdown contents, `p` stored paths, `P` source paths, `J` metadata JSON, and `s`
snapshots. Stored and source paths are separate, anchored answers; an absent source is
labeled “not recorded,” and copying a stale source keeps the “no longer exists” warning.
With marks, the palette copies rows in visible order: references and paths are
newline-separated, links form a Markdown list, metadata is a JSON array, and Markdown
contents use bounded fenced sections. Unavailable rows are skipped with an explicit
count. These modal-local `l`/`J` accelerators are distinct from the Artifacts Files
pane's compatibility-preserving `%L`/`%j` keys. The legacy `y` and `Y` accelerators
remain available and apply to the same marked set.

`Y` shares one helper with the [Files pane](../../ace.md#files-pane), so both copy the same anchored
path: the stored path, except that PDF rows yield the live Markdown source they were
rendered from when the index recorded one. Relative index paths are anchored to the
producing workspace — including legacy rows whose workspace is discoverable only through
the agent's artifact metadata — and the completion toast says when the copied path no
longer exists.

When sase's TUI is running inside tmux, artifact viewing opens in a right-side tmux pane
so the TUI remains visible. The Agents list collapses while the tracked pane is live,
row-changing navigation shows a warning instead of moving to a different agent, `l`
focuses the tracked pane, and lowercase `a` closes it. If the pane was already closed,
lowercase `a` opens the artifact panel normally. Outside tmux, sase's TUI suspends while
the terminal viewer runs in the current pane. The viewer supports image, video,
Markdown, PDF, and text artifacts: images are displayed directly with `kitten icat`,
videos play with `mpv`, Markdown is first rendered to PDF, PDFs are converted to PNG
pages for paging, and unknown file artifacts fall back to a text viewer. The viewer
needs `kitten` for image/PDF/Markdown display, `mpv` for videos, `pdftoppm` for
PDF/Markdown paging, and `pandoc` plus a supported PDF engine for Markdown rendering.
Missing tools produce a warning instead of failing the TUI.

Viewer controls:

Only one plan artifact is shown for an agent. When both an archived plan and an SDD tale
path are present, sase's TUI prefers the committed SDD plan; otherwise it keeps the path
that best matches the run metadata.

During successful-agent finalization, Markdown-to-PDF rendering updates
`workflow_state.json.pdf_status` and a compact activity label. sase's TUI renders that
label only in the prompt/detail header's labeled `Activity:` field, so long conversions
show progress such as `PDF 2/4 <path>` or `PDFs done 3/4 (1 skipped)` instead of looking
idle.

## Agents Tab Reproduction Bundles

Agents-tab reproduction bundles capture the loader/apply sequence that determines which
rows are visible. Use them when the Agents tab briefly drops historical rows, re-adds
them, or shows duplicate workflow parents.

When you see one of these bugs in a live sase's TUI session, switch to the Agents tab
and press `,B` before refreshing again. sase's TUI writes a commit-safe bundle to
`~/.sase/repros/<timestamp>-manual-.../agents_tab_repro.json` and shows a toast with the
path. "Commit-safe" means local names and paths are redacted, and prompt, response,
chat, and diff bodies are omitted. The bundle keeps the row identities, loader state,
app projection state, screen text, and an SVG screenshot needed to replay the row-list
behavior.

Replay a bundle from a checkout of this repository:

```bash
sase repro replay tests/ace/tui/repro/fixtures/agents_tab_disappear_reappear_v1.json --assert-stable --json
```

The current expected verdict for the checked-in fixture is:

```json
{
  "result": "passed",
  "failed_invariants": [],
  "verdict": "current code fixed for the captured Agents-tab bug class"
}
```

Add `--write-artifacts /tmp/sase-agents-tab-repro-artifacts` to write one `.txt` screen
dump and one `.svg` screenshot per replay step. The replay JSON lists those paths in
`screen_paths` and `screenshot_paths`.

Use out-of-band capture only when you need a filesystem baseline and did not have the
live TUI capture running:

```bash
sase repro capture agents-tab --output /tmp/sase-agents-tab-capture --commit-safe --json
```

Out-of-band capture is labeled `capture_mode=out_of_band` because it loads the current
filesystem state and cannot reconstruct transient refreshes that already passed through
the running TUI. The replay harness is scoped to the known Agents-tab
disappearance/reappearance and duplicate-parent bug class; it is not a general proof for
arbitrary rendering races.

For continuous diagnosis, press `,T` on the Agents tab to enable invariant checks after
each load/apply cycle. On the first violation in a burst, sase's TUI auto-captures one
bundle under `~/.sase/repros/<timestamp>-auto-.../` and shows a warning toast. It does
not write a new bundle every refresh while the same violation remains active.

## Related

- [TUI hub](index.md) — all Agents tab reference pages.
- [Agents tab search and modes](agents-tab-modes.md) — search and key modes.
- [Agents tab panels](agents-tab-panels.md) — clan, session, and tribe panels.
