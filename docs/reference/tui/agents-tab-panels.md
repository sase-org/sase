---
title: Agents tab panels
description: Clan, session, neighbor, and tribe panels on the Agents tab.
---

# Agents tab panels

This page describes the Agents tab detail panels: clan and session panels, neighbors,
and tribe side panels.

## Clan and Session Detail Panels

Selecting a clan container shows a `CLAN` summary. Selecting a real multi-member session
root titles the sticky [header panel](agents-main-deck.md#agents-tab-main-deck-1) `SESSION` (cyan, matching
the name), then shows the session's normal Main deck cards, with its `SESSION TURNS`
roster in the jump panel. A selected agent turn — standalone or session member — titles
the header panel `AGENT TURN` (gold, matching the name). Both rosters use the numbered
member jumps described above. Layered clan members in the Agents list follow dependency
wave order, with launch order breaking ties inside each wave; unresolved members trail.
One-wave clans keep the existing status priority — Failed, Stopped, Running/Starting,
Queued, Waiting, Done — with launch recency breaking ties. The clan's `CLAN MEMBERS`
jump-panel roster follows the same wave order for layered clans, so its numbers match
the tree and remain stable as statuses change. A nested session remains one direct entry
with its chain indented beneath it. Session rosters retain sequential chain order.

Selecting a session **turn** row (not the container) also shows its `SESSION TURNS`
roster in the jump panel: the same enclosing session's members, in the same chain order,
minus the selected member itself. The heading carries a dim ` · <session name>` suffix
naming the session, since the count shown is one less than the session's full size.
Unlike a container panel, a member panel folds this roster (and the rest of its own
sections) using the selected member's own three-level agent scale rather than the
session's two-level scale, so no `Fold: N/M` header line appears.

Clan metadata has three session-only detail levels. Session metadata uses the last two
effective states as its two-level scale for fold-aware metadata: session level 1 is
expanded and level 2 is fully expanded.

| Level | Content                                                                                                        |
| ----- | -------------------------------------------------------------------------------------------------------------- |
| 1     | Core member rows plus headings and counts; expensive disk-backed bodies remain deferred                        |
| 2     | Bounded triage detail such as activity, wait/retry state, context summaries, and compact member metadata       |
| 3     | Full available sections and the richest member annotations, including workspace, timestamps, and attempt count |

The compact clan roster and its fixed numeric member jumps remain available at all three
levels. Clan sections appear only when their content is known to exist: known-empty
sections are omitted, while unknown required disk-backed content produces one dim
`⋯ scanning member data…` tail for the document instead of a placeholder for each
section. Session rosters and their numeric jumps likewise remain available at both
effective levels. Session macro and prompt sections are omitted when absent, while an
unfinished reply remains visible as pending rather than disappearing as empty.
`AGENT PROMPT` and the consolidated `AGENT REPLY` are plain navigation anchors whose
available conversation bodies stay fully visible at both session levels.

`v` annotates a clan document in place rather than replacing it: the panel keeps its
current sections and fold level and gains inline `[N]` markers. Clan hints come from the
clan summary, member-attributed `ERRORS`, variable, `REPLIES`, and `PROMPTS` bodies,
per-entry `SASE CONTEXT` rows, `SLOW TOOL CALLS` rows, and the `COMMITS` lane; each path
resolves against the workspace of the member that produced it, and summary paths that
name a plan, artifact, or delta resolve through an index computed during clan enrichment
rather than a blind workspace join. A logical `plan:` reference stays one hint token and
opens when selected through the agent workspace, project primary, and machine plan
archive; it is never joined to a workspace path. Ordinary agent prompt and reply text
uses the same plan lookup, and archived `prompts/<YYYYMM>/<name>.md` references can open
from the agents sidecar before clan enrichment finishes. Hints exist only where text is
actually visible, so availability follows the active fold level — level 1 hints the clan
summary only, level 2 adds the bounded triage lines, and level 3 adds full bodies and
per-entry context, tool-call, and commit rows.
Markers are numbered in document order. The jump panel is hidden while hint mode is
active and returns with the same fixed member numbers when it ends. While clan
enrichment is still in flight the hint bar stays open and the document is re-annotated
when the deferred sections land.

The default fold chords are:

| Key       | Action                                                 |
| --------- | ------------------------------------------------------ |
| `z1`-`z2` | Set a session directly to level 1 or 2                 |
| `z1`-`z3` | Set a clan or single-agent scope directly to level 1-3 |
| `z1`-`z4` | Set a selected whole tribe panel directly to level 1-4 |

The `Fold: N/M` header field reports the position within the active scale, while glyphs
on foldable headings show their effective per-section levels. Only session panels print
that header line; a single sase agent relies on the `SLOW TOOL CALLS` heading glyph
(and, with the jump panel expanded, the `NEIGHBORS` heading glyph) instead. On a session
conversation heading, `za` and `zA` refresh normally but do not create or change a
section override. A valid panel-level cycle, extreme toggle, or direct selection clears
real per-section overrides. Fold state is shared by the Agents detail documents: an
ordinary agent's own three-level scale shapes its `NEIGHBORS` and `SLOW TOOL CALLS`
sections, so `z*` chords have a visible effect on a regular sase agent, and the same
clan/agent scope carries over to the next selected clan or session container. Most other
sections on a regular-agent panel stay fold-inert, except the `SASE CONTEXT / BEAD`
lane's multi-line values: at scale position 1 (`z1`, Collapsed), a task or phase
worker's `Notes`, and a task worker's `+1 Evidence`, collapse to a one-line digest,
`N lines (zz to show)`; single-line values never fold, and at positions 2-3 the full
value renders. A selected whole tribe panel adds level 4 for exhaustive detail. These
keys are configurable; see [Agent Clans, Sessions, and Tribes](../agents/index.md) for
the grouping model.

When sase's TUI knows a planner/author or epic lander's associated plan, the metadata
panel adds a `PLAN` lane in `SASE CONTEXT`. A task worker that authored a plan in the
same run also shows a `PLAN` lane beside its task `BEAD` lane. The lane order is `PLAN`,
`BEAD`, `ARTIFACTS`, the audited `MEMORY`, `GLOSSARY`, `SKILLS`, and `WORKSPACES`, with
absent lanes omitted once they have resolved. A plan or any recorded output is enough to
show the context section. An epic phase worker never shows its parent epic as a `PLAN`
lane. Instead, its launch metadata identifies the epic plan and exact phase bead, and
sase's TUI derives one phase-local `BEAD` lane from that phase's validated,
frontmatter-ordered entry. The lane shows `Phase Title`, `Description`, `Size`,
`Epic Plan`, and `Epic Title`; `Size` uses the literal `xsmall`, `small`, `medium`,
`large`, or `xlarge` label and the same accessible chip palette as epic summaries. The
phase title comes from the same validated entry, is normalized to one line, and wraps
losslessly like the other values. Authored descriptions are also normalized to one line;
a missing description uses the same stable plan-and-phase pointer generated during
deterministic bead creation. This modern path does not read the bead store, and missing,
unreadable, damaged, explicitly invalid, or out-of-range metadata keeps the known
identity/path fallbacks while rendering optional fields as `unavailable`, without
exposing the epic goal, dependencies, or any peer phase.

`SASE CONTEXT` **streams**: its lanes are resolved cheapest-first in batches and each
batch is published as it lands, so the section appears almost immediately instead of
waiting for the slowest lane. A lane that has not resolved yet is not the same as a lane
that resolved to nothing — while a lane is still in flight it renders a dim,
non-interactive `resolving…` row that holds its position in the order above, so the
section fills in rather than reshuffling as the remaining lanes arrive. `PLAN` and
`BEAD` share one backing lane, so both show their own `resolving…` row until it lands
and the panel can tell which of the two actually has content. Repaints coalesce through
the same debouncer that drives the rest of the header, leaving hint mode and scroll
position undisturbed.

Within `SASE CONTEXT / ARTIFACTS / Beads`, a selected agent's newest current structured
bead note appears beneath its bead row with its original author and append time. The
card shows at most three wrapped note-text lines, then points to the existing numbered
bead detail for the full note and any earlier notes. Edits retain the original author,
retracted notes disappear, and an audited read reason remains as a separate `read:`
continuation. The cached touch index supplies these previews off the interactive render
path; it never opens bead streams or resolves bead detail while navigating.

For planner/author and lander rows, the lane body contains the complete normalized
`Title`, `Goal`, and canonical `Path`; a tale additionally gets a `Size` row between
`Goal` and `Path`, showing the authored `xsmall`/`small`/`medium` chip, or the `medium`
chip plus a `(default)` marker when the tale's `size` was missing or an over-sized
legacy `large`/`xlarge` normalized at launch (see
[Plan Frontmatter Schema and Validation](../work-units/plan-format.md#plan-frontmatter-schema-and-validation));
epics never show a `Size` row here. The lane header shows the effective user-facing tier
(`plan`, `tale`, or `epic`) and, for epics, the phase count. The tier records how the
user approved the plan: `approve` means a plan approved without an SDD commit, `tale`
(and the legacy commit-only action) means a committed tale, and `epic` means a committed
or launched epic. That displayed choice survives a later commit or launch failure. When
action metadata is absent, sase's TUI falls back to a valid authored `tier: tale` or
`tier: epic`; a legacy committed record without a readable authored tier falls back to
`tale`, while a genuinely unresolved tier renders `tier unavailable`. Path selection is
independent: committed paths are relative to the agent workspace (including SDD sidecars
such as `sase/repos/plans/...`), while pending and explicitly uncommitted archives use
`~/.sase/plans/...`.

Validated authored epics add a phase roadmap beneath those three rows. sase's TUI
validates this display as a launch consumer: modern phases retain their authored
`xsmall`, `small`, `medium`, `large`, or `xlarge` size, while historical phases with an
omitted size normalize to `small`; an explicit invalid size or other schema damage makes
all phase metadata unavailable. Each entry shows its one-based authored order and
diamond, title, fixed-width literal size chip, canonical ID, `no dependencies` or
`after <id>, ...`, plus an authored phase model when present. Optional descriptions get
their own hanging-indented line. The order and diamond glyph describe static plan
structure, not execution state or live bead progress. Tales retain the compact four-row
form (`Title`, `Goal`, `Size`, `Path`). The chip remains visible while the title and
other long ASCII or wide-Unicode values fold completely without ellipses; the lane caps
content at 80 terminal cells on wide panels and reflows to the normal deck panel or
zoomed deck width. Logical header text contains the same size labels for search, copy,
and style inspection. In hint mode only `Path` receives a numbered file hint, allocated
in the plan's visual reading order. Missing or damaged plans keep their known lane and
path visible; when epic context is known, validation failure renders one quiet
`phases unavailable` header state rather than partial phase data.

sase's TUI separates fast visible-inbox loads from full-history scans. The visible inbox
is the normal Agents-tab working set: every active row plus every non-hidden completed
row, subject only to a first-paint safety cap (about 6x the measured inbox). The first
load for a committed query reads that whole inbox as a baseline; refreshes after a
baseline stay windowed patches over it. Startup, manual This-tab refresh (`r` then `r`
on Agents), and active agent search use that path through the persistent artifact index
when it is available.

If the index is missing or unhealthy, sase's TUI falls back to a bounded source-artifact
scan for the first paint and shows a repair warning with the reason. That repair state
can arm a deferred full-history reconcile after input has been quiet, but normal Agents
This-tab refreshes still stay on the visible-inbox path. Use
`sase agent index status --json` for a lightweight check that does not scan source
artifacts, `sase agent index verify` to compare the index with source artifacts, and
`sase agent index gc` to rebuild the index and dismissed projection. Use `r` then `f`
(or `,y`) when you want an immediate full-history refresh: it revalidates and reads the
whole archive through the artifact index, and falls back to a full source-artifact scan
only when the index is missing, busy, or fails. Normal SQLite deletes never reclaim disk
space; `sase agent index vacuum` reports freelist pages and dismissed row counts, and
`-a`/`--apply` compacts the index file with `VACUUM` (dry run by default; this never
removes or alters a row).

## Sase Agent Neighbors Section

Every sase agent panel carries a numbered `NEIGHBORS` roster in the jump panel. The
section appears on session container panels after their `SESSION TURNS` roster when both
exist, and on ordinary agent panels. Tribe panel summaries, session member child rows,
and workflow aggregate rows have no `NEIGHBORS` section. Clan containers carry a
distinct `CLAN NEIGHBORS` roster instead (see below). A selected session turn row owns
no sase agent, so its panel carries only the `SESSION TURNS` roster (siblings, minus
itself) and never a `NEIGHBORS` section.

A selected clan container shows `CLAN NEIGHBORS` after its `CLAN MEMBERS` roster when
another clan shares its dotted hood. Two clans are neighbors when their presented clan
names share the same root hood: `foo`, `foo.bar`, `foo.baz`, and `foo.bar.deep` all
share the `foo` hood. Names compare case-insensitively at dot boundaries; the selected
clan itself, ordinary agent rows, malformed names, and unrelated prefixes such as
`foobar` are excluded. Each target keeps its full stable clan identity including its
generation, and rows render under their full clan names. The section appears only when
another eligible clan is visible under the current query and fold state. Numbering draws
from one continuous ladder shared with `CLAN MEMBERS`, so eleven combined entries use
two digits and entries beyond the shared 100 slots appear as an unnumbered
`… +N more clan neighbors (not numbered)` count. A digit jump reveals the target clan
through folds and tribe panels and participates in `Ctrl+O` jump-back history; a stale
relation or missing target cancels without moving selection.

The rows for that sase agent are ancestors, descendants including same-session dismissed
descendants, then hood neighbors grouped by hood, nearest hood first — under dim
`ancestors`, `descendants`, and `<hood> hood` group labels. A sase agent joins the hood
that matches its own name, and a session uses its bare session name for that match, so a
session `visual.worker` and a single agent `visual.worker.notes` relate as ancestor and
descendant exactly as two single agents with those names would. Row labels are shortened
relative to their group, so a `myclan` hood neighbor reads `.code` and a descendant
reads `--impl.helper`. A `⊘` glyph and a `dismissed` annotation mark dismissed rows, and
`folded` marks a prospective row that currently lives inside a collapsed clan. In the
jump panel the section sits after `SESSION TURNS` when both exist, so a sase agent's
numbered neighbors stay reachable without scrolling the Main deck body.

Every neighbor always renders and gets a digit whatever the fold level. The fold level
only changes the heading glyph and each row's annotation detail, both visible once the
jump panel is expanded with `.`. Numbering is stable across fold levels and JUMP-panel
toggles: the collapsed legend, the expanded roster, and the published jump map all share
one continuous ladder. The heading count is always the sase agent's total neighbor
count. The only hidden-row tail is the shared 100-slot numbering capacity, which reports
`… +N more neighbors (not numbered)`. On a session, siblings that already appear under
`SESSION TURNS` are not repeated; they are reported by a dim
`… +N also listed under SESSION TURNS` tail instead. The heading count still includes
the suppressed rows.

## Tribe Side Panels

The Agents tab is laid out as a series of vertically-stacked side panels, one per
effective agent **tribe**. Agents without a stored tribe live in the reserved `@default`
panel; an explicit `default` assignment converges on the same panel, so the UI never
creates a duplicate default bucket. `@default` is derived for presentation and is not
backfilled into `agent_meta.json` or `agent_tribes.json`; clearing a user-managed tribe
returns the agent to this panel. Pressing `N` on a clan row or on any clan member
instead sets the whole clan generation's recorded tribe, and clearing it writes an
explicit unset that sticks even when members still carry an epic tribe (see
[clan records](../agents/index.md)). Every tribe renders as `@<tribe>` with a sase-agent
count in the panel title. One standalone agent or one sequential session is one sase
agent, and a rootless clan contributes one sase agent per direct member rather than one
for its synthetic container. Per-tribe icons, identity colors, and initial expansion are
configurable through [`ace.tribes`](../config/ace-behavior.md#acetribes); the special `default`
entry styles the reserved panel. Agents launched by AXE jobs land in the built-in `@job`
panel. SASE still stores that tribe under the name `chop`, but `@job` wait and
fork targets, `tribe:job` filters, and an `ace.tribes.job` entry all address it (an
explicit `ace.tribes.chop` entry still wins for styling). See
[Automation migration notes](../upgrading/automation.md#scheduler-routine-and-job-names). A manual panel fold lasts for
that panel's current lifetime, and the configured initial state is applied again when
the panel appears after a restart or after the tribe disappears and returns. Once a
panel has shown rows under the current Agents query, it stays mounted for the session
even if a bounded or incomplete load briefly omits them; it retires only when every node
it showed is authoritatively gone — dismissed, killed, a dismissed named proc, moved to
another tribe, or absent from a complete history load — including a clan whose members
are all gone. Changing the Agents query starts that bookkeeping over. Across structured
sase's TUI surfaces, identity colors apply only to an existing configured icon and the
`@tribe` name; they do not recolor free-form `@...` text or selection, fold, count,
heading, and status chrome. Configured icons remain limited to surfaces that already
show an icon. Each panel title can also show compact scoped metrics in the form
`[S1 R2 W1 F1 U1 D3]`: `S` is stopped for human input, `R` is running, `W` is waiting to
start, `F` is failed, `U` is unread terminal work, and `D` is done/read terminal work.
Zero-count metrics are omitted. The status metrics use the same sase-agent projection as
the adjacent total and classify a sequential session once from its normalized owner
status. The selected whole-panel `TRIBE` header uses that same projection, while its
nested count and per-session/per-clan member summaries preserve the concrete-member
distinction. On the selected whole panel, the title marker, total, brackets, and metric
letters use the focus accent; each numeric metric count retains its semantic status
color. The title can end with an amber `⚙N` badge for running monitors followed by a
grey `⚙N` badge for finished ones, in that order, after the metric chip (or after the
total when the chip is empty); the two counts partition the tribe's monitors exactly.
Each badge is fold- and collapse-independent — it still reports on a fully collapsed
panel — and is omitted entirely when its own count is zero. Both badges keep their
semantic hue on a selected panel while the brackets and metric letters take the focus
accent. Panel heights are sized to their content and separated by a one-row gap. When
the panels fit, the first panel grows to absorb leftover vertical space while later
panels stay pinned to their natural height; when the panels overflow, space is weighted
by each panel's rendered row count.

A selected tribe panel's `TRIBE` identity fields (`Name`, `Status`, `Composition`,
`Runtime`, `Fold`) render in the sticky [header panel](agents-main-deck.md#agents-tab-main-deck-1) above the
Main deck; collapsed, it shows the tribe name, status, and counts on one row and the
composition, runtime, and fold on the next. The scrolling Main deck opens with an
unlabeled description row only when the tribe has a configured
[`description`](../config/ace-behavior.md#acetribes). That row is set off by a blank line and
wrapped at a fixed 80-cell measure (no hanging indent — there is no label to indent
past). A tribe with no configured description renders no row there at all, including
unconfigured ad-hoc tribes with no `ace.tribes` entry. To find configured tribes that
are missing a description, run `sase doctor -C config.tribes`.

Use `J` / `K` to move across expanded panels (forward / reverse) and enter the first or
last selectable row in the destination; collapsed panels are skipped entirely, and the
keymaps do nothing when no other panel is expanded. Collapsed grouping banners count as
rows. When the focused panel's only selectable row is already selected — or it renders
none — lowercase `j` / `k` select the adjacent whole panel, wrapping across every panel
including collapsed ones; `l` or `Esc` then descends into the newly selected panel's
remembered row. This differs from `J` / `K`, which skip collapsed panels and land
directly on a row. Whole-panel focus is available only in the split layout. Lowercase
`h` walks from any agent or workflow-step row to its validated immediate workflow,
session, clan, and finally tribe parent without changing structural or grouping folds.
It also selects a lone split panel after the structural chain is exhausted. A selected
panel has a `❖` title and shows a fold-aware `TRIBE` summary in the Main deck. While it
is selected, `j` / `k` cycle whole panels without descending; `l` or `Esc` returns to
the remembered row. A second `h` collapses the selected panel when another panel remains
visible. On a collapsed panel, the first `l` expands it while keeping whole-panel focus
and the second returns to the remembered row; `L` on a collapsed panel does not expand
it — it warns `Selected tribe panel is collapsed` instead (see uppercase `H`/`L` below).
Lowercase `h` on a collapsed panel selects the visually bottom-most expanded panel
without changing any panel folds, and `Ctrl+O` returns to the collapsed origin. When
every live panel is collapsed, `h` remains a no-op and shows the existing
`Panel is already collapsed` warning. Apostrophe jump hints include every split-panel
title, even a lone expanded panel, as well as collapsed titles, and support the normal
`Ctrl+O` jump back.

Selection is the source of truth across refreshes: when a status change or roster reload
moves the selected agent into another panel, panel focus moves with it. Focus stays put
only when you parked it deliberately — whole-panel focus, a selected grouping banner, or
a collapsed focused panel — or when the agent's new panel is collapsed, in which case
the cursor returns to the focused panel instead. If the selected agent disappears, the
cursor lands on the neighboring visible row.

Lowercase `l` only advances a real fold owned by the selected row or its immediate
workflow/session owner, so a visible hidden leaf under an already fully expanded
workflow is a no-op. Uppercase `H` is the structural mutation key. When the selected row
owns an open workflow or sequential-session agent node, the first press retreats that
agent node one fold level. From a visible hidden step that hides the selected row,
selection re-anchors to the agent-node owner. After the selected agent node is
collapsed, later presses fully collapse every remaining open agent node in the next
grouping scope, then only the open canonical clan enclosing the selected row. With that
now-collapsed clan container still selected, another press collapses every remaining
open canonical clan in the group; only a later press collapses the grouping banner. A
banner, already-collapsed agent node, or already-collapsed clan selection proceeds
directly to that remaining-agent-node or group-wide clan sweep. LLM Calls detail still
takes priority. On a selected expanded whole panel, `H` hints every currently expanded
agent node, clan, and top-level grouping banner in that panel — the same `L` hint
affordance restricted to collapsible targets — and fully collapses whichever one you
pick; it never expands and never touches the panel itself, which stays lowercase `h`'s
job. A panel with nothing expanded warns without arming hint mode; an already collapsed
panel keeps the usual already-collapsed notification. The merged layout has no
whole-panel focus and keeps the row-focused group scope across the merged roster.

Press `Z` with a whole tribe panel selected to zoom that tribe's Summary card in place.
Press `=` to isolate the focused tribe panel: it keeps that panel expanded and collapses
every sibling panel. If that changes the layout, sase's TUI remembers the prior
collapsed-panel set for one session-local restore. Panels whose state would change back
show `↺` in their titles, the footer changes to `= restore panels`, and the next `=`
restores the remembered layout. A separate sibling-panel or layout mutation invalidates
the pending restore. An already isolated panel is an idempotent no-op and does not arm a
restore. `=` works from whole-panel focus and from a row selection inside a panel alike
— from a row, it isolates the panel that holds the cursor without changing the selected
row. This action preserves the selected panel's remembered row and is available only in
the split layout.

Press `-` to sweep every open structural fold — agent nodes and clans, never grouping
banners such as `Done` or `Running` — closed in the tribe panel that holds focus, in one
press. It resolves scope the same way `=` does: from whole-panel focus, from a row or
banner selection inside a panel, and in the merged layout, where it treats the merged
roster as one scope. `-` never collapses the panel itself; that stays lowercase `h`'s
job, and it never touches an open grouping banner either — use `H` for that. When the
focused panel has nothing left to collapse, `-` reverses itself: it re-expands exactly
the folds its own last sweep in that panel closed, restoring each structural fold to the
level it held before (a fully expanded agent node comes back fully expanded, not merely
expanded). The restore is filtered at press time to folds that are still live in that
panel and still collapsed, so it is forgiving of folds the user re-expanded by hand or
owners that disappeared, and it never resurrects a fold that does not exist. Each
panel remembers at most one sweep; a fresh sweep replaces that panel's record, and a
panel that stops being live drops it. While a restore is armed, the panel marks every
fold `-` would re-expand with a gold `▿` on the owner row and `▿N` in the panel title;
those markers clear as soon as the next `-` press would sweep instead of restore. The
footer shows `- collapse folds` when the focused panel has an open agent-node or clan
fold to sweep, or `- restore folds` when nothing is left to collapse but a prior sweep's
reverse is still armed. A panel with only open grouping banners and no open agent node
or clan reports nothing to collapse or restore.

Press `_` for the all-panels sibling of `-`: in one press it sweeps every open
agent-node and clan fold in **every** tribe panel, not just the focused one, and shares
`-`'s per-panel sweep records, so the two compose — sweeping one panel with `-` and the
rest with `_` still restores everything in the reverse order. A panel that is
effectively collapsed is skipped in both directions, exactly like `-` refuses to sweep a
collapsed panel, though its record stays live and reachable once it is expanded again.
`_` works identically from any selection — a row, a group banner, whole-panel focus on
an expanded panel, or whole-panel focus on a collapsed panel — sweeping or restoring the
other panels either way. When nothing is left to collapse anywhere, it re-expands every
fold every panel's last sweep closed, restoring each to its exact prior level. The
footer shows `_ collapse all folds` / `_ restore all folds`, but only once at least two
tribe panels are eligible; with a single panel it would be a redundant duplicate of `-`.

Per-panel actions (kill, dismiss, expand, etc.) operate on whichever panel currently
holds focus. Press `X` to open the cleanup panel: `d` dismisses completed agents in the
focused panel, `D` dismisses completed agents across loaded panels, `k` cleans the
focused panel, `K` cleans all loaded panels, `m` cleans marked agents, `g` cleans the
focused group, `t` opens the tribe chooser, and `c` opens the custom selector. `Enter`
runs the highlighted row, and `Esc` or `q` closes the panel. Each row is disabled when
the loaded roster contributes no candidates. Its detail line is a candidate count, not a
promise that every candidate can complete that action; the confirmation or planner may
narrow the final set.

There is no separate clan chooser. A synthetic clan container row is never a cleanup
target itself: every scope above expands it into the live members of its generation, so
members folded away behind a collapsed clan are still reached by a panel, tribe, group,
or marked cleanup. Loaded workflow children are pulled in when their parent is a
candidate, and identities are de-duplicated in Agents-tab order. Named-proc handling
depends on the chosen scope: panel/global and marked/group bulk actions can dismiss a
terminal named proc but skip an active one with a warning, while tribe-planner and
custom-selector cleanup omit named procs. To stop an active stand-alone named proc,
select its row in the Agents tab and press `x`. Every scope then continues through its
normal bulk-cleanup confirmation or planner flow.

The `TRIBE` summary has four metadata detail levels, controlled by the same `zz`, `zZ`,
`za`, and `zA` chords used for clan and session detail. From levels 1-3, `zZ` opens
every fold to level 4; at level 4, it closes every fold to level 1:

| Level | Name      | Tribe summary content                                                                                                                                                                                                                             |
| ----- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | Glance    | Header, compact numbered top-level roster, attention previews, clan summary headline index (up to 8 clans), prompt headline digest (up to 8 distinct prompts), and headings/counts for non-empty sections                                         |
| 2     | Triage    | Bounded previews for every represented section; every clan summary (up to 24) with styled ledes, and every distinct prompt (up to 24) with labels, macro chips, and sizes                                                                         |
| 3     | Inspect   | Nested roster detail and grouped full section bodies, still with protective bounds; 16-line clan summary previews and 10-line prompt previews                                                                                                     |
| 4     | Forensics | Unbounded bodies, tracebacks, the richest member annotations, full clan summary bodies (500-line safety cap per clan), full prompt bodies (500-line safety cap per prompt) and launch directives, and all-time runtime statistics and percentiles |

The compact roster and its fixed numeric jump targets exist at all four levels. Number
keys jump to a top-level clan, session, workflow, or agent, expanding the required panel
and ancestor folds first. These metadata-member numbers are separate from ordinary
apostrophe entry hints, whose adaptive target keys may use two characters in a large
list.

`PROMPTS` sits after `CLAN SUMMARIES` in the Main deck body (the `TRIBE MEMBERS` roster
itself lives in the jump panel): it maps what each agent in the tribe was asked to do.
Its number chips are the same digits as the roster jump targets. Identical prompt bodies
are listed once with a `×N` badge and a shared-by list. `za`/`zA` on a prompt entry
opens just that prompt. It is the level-1 exception: unlike most sections, it shows
prompt headlines at Glance instead of only a heading. Entries also carry green macro
chips and, for multi-line prompts, a dim line count, separated by dim `·` dividers. When
the tribe's prompts target more than one known project, each entry ends with that
project's accent-colored `+<project>` chip (or its `#<workflow>:<name>` spelling when
the name is not tag-shaped); unknown targets and Patch refs get no chip.

`CLAN SUMMARIES` sits before `PROMPTS` in the Main deck body (the `TRIBE MEMBERS` roster
itself lives in the jump panel): it maps the curated summary of every clan in the tribe,
because clan intent reads before raw prompts. Each entry line carries the clan's roster
digit as a number chip, the clan label, a banner-kind kicker (`EPIC`, …) when present, a
headline truncated at 120 characters, and a line count for multi-line summaries.
`za`/`zA` on an entry opens just that clan's summary. Like `PROMPTS`, it is a level-1
exception: Glance shows the headline index, Triage adds a styled lede of up to four
lines, Inspect shows 16-line previews, and Forensics shows full bodies behind a 500-line
per-clan safety cap.

Reply, slow-call, prompt, and clan-summary presence enrichment is requested off-thread
at every tribe level so known-empty sections can remain absent. Full bodies still follow
the level-specific bounds above, and all-time runtime statistics remain level-4-only.
When required disk-backed content is not known yet, the document ends with one dim
`⋯ scanning member data…` tail; known-empty content produces no section or placeholder.
Section-level overrides inherit from the panel level and are cleared by a valid
panel-level cycle, `zZ` extreme toggle, or direct `z1`-`z4` selection.

Tribes are set or cleared with `N` (see [Agent Actions](agents-tab.md#agent-actions)). When opening
the modal on an agent without a tribe the input is pre-seeded with `pinned` so a single
Enter promotes the agent into the standard "pinned" panel; that default makes tribe
removal discoverable too — opening the modal on an assigned agent and submitting an
empty string clears the tribe. The `tribe=<name>` keyword on `%id` assigns the tribe at
launch, and `#tribe:<name>` combines it with an automatic id; `sase agent tribe` manages
it from the CLI.

## Related

- [TUI hub](index.md) — all Agents tab reference pages.
- [Agents tab](agents-tab.md) — tabs, keys, lists, and actions.
- [Agent statuses](agent-statuses.md) — agent, wait, and completion statuses.
