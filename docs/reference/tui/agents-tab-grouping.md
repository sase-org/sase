---
title: Agents tab grouping
description: Group banners, folding, and grouping modes on the Agents tab.
---

# Agents tab grouping

This page describes how the Agents tab groups rows: banners, folding, and grouping
modes.

## Group Banners and Folding

In `STANDARD` mode, agents within each tribe side panel use either a two-tier or
three-tier banner hierarchy depending on whether any agent in the panel targets a Patch:

- **3-level layout** (panel contains at least one Patch-scoped agent): **project → Patch
  → name-root**. Project-scoped agents and agents with no `cl_name` fall into a
  synthetic `(no Patch)` bucket that sorts last.
- **2-level layout** (no Patch anywhere in the panel): **project → name-root**.

Banners are rendered between agent rows and carry a summary chip
(`N agents · K running · M failed`). Workflow children inherit grouping identity from
their parent agent so banners never appear between a parent and its workflow steps.
Optional name-root and dotted-prefix banners appear only when they group at least two
rows.

Labels such as L0, L1, and L2 describe a banner's nesting depth, not a shared fold
setting. Every emitted grouping banner has its own binary expanded/collapsed state, kept
separately for each tribe panel and grouping mode. Three independent folding layers can
therefore be visible at once: grouping banners contain project, Patch, date, status, and
name buckets; structural rows contain clan members, session members, and workflow
descendants; split-panel titles represent whole tribe panels. Their configurable default
keys are listed in the generated [TUI keymaps reference](keymaps.md).

Collapsed grouping banners at any depth are selectable rows; expanded banners remain
visible headings but are skipped by row navigation. When a collapsed banner is focused,
`l` expands only that banner and moves focus to the next visible child banner or first
agent row. When a banner is focused, `m` toggles marks for all top-level agents in that
group; workflow child rows are not marked independently by the banner shortcut. `x`
performs a bulk kill/dismiss on every top-level agent in that group (single confirmation
modal). Marked collapsed banners show `[✓]` when all covered top-level agents are marked
and `[~]` when only some are marked. Marks take priority over the group for bulk
actions, so a non-empty mark set always drives the bulk action regardless of banner
focus. When a fold change hides the previously focused agent, focus snaps to the nearest
visible ancestor banner so navigation context is never lost.

Clan and session rows add an agent-tree hierarchy inside those grouping banners. Their
trailing names are color-coded by kind without an additional icon. A clan is a
selectable synthetic container, never an agent, and ends in an orchid `<name>` after its
rolled-up status and member counts. A real multi-member session root remains a teal
agent row and ends in an azure `<name>`; ordinary agent annotations and lone plan
proposers with only their display-only planner child remain gold. Clan `@tribe` labels
follow the orchid name. A clan row starts with the teal project label of its direct
members in the title slot, for example `bob-cli (RUNNING) [R5 W3] research.35`. A clan
spanning several projects shows the dominant project first, at most two labels, then
`+N`. The CLAN header repeats the label as a `Project:`/`Projects:` field and at the
start of the compact second line. A clan's outer fold is binary: from a collapsed clan
row, press `l` once to reveal its direct agents, session rows, and visible workflow
rows. The clan row's fold count and status chrome count those direct clan agent nodes
once; nested session or workflow members do not inflate them. To reveal descendants
within a session or workflow, move to that row and press `l` there; pressing `l` again
on the clan row itself has no effect. Lowercase `h` moves to the validated parent
without changing fold state. Sequential session members use `--<suffix>` names and run
one after another. Killing or dismissing a clan row cascades to the clan's live members;
acting on one member leaves its siblings alone. Layered clan members sort by dependency
wave and then launch order in every grouping mode; unresolved members trail. One-wave
clans keep the clan-local status priority Failed, Stopped, Running, Queued, Waiting,
Done, with Starting sharing Running's rank and launch recency ordering members in the
same bucket. A session row moves as one unit with its follow-ups and workflow steps,
preserving their adjacency and internal order.

Layered clan rows add compact wave-state pips immediately after the count chip (and any
unknown-wait marker): `✗` failed, `▲` needs you, `◐` in flight, `●` done, `○` not
started, and `·` dismissed-only. A final epic land seal adds a separate `∎` pip with the
seal stage's state. Above twelve numbered waves, the strip becomes the worst state and
completed-wave fraction, such as `◐ 8/14 ∎`. Tribe Summary clan rows and both forms of
the compact clan identity header use the same pips; the 19-cell rail stays unchanged.

Clan rows aggregate member status using the same operational precedence: human-input
questions, pending plan review, failure, and running/starting states outrank queued
work; `QUEUED` then outranks `WAITING`, followed by an all-done result. Consequently, a
clan with queued work and ordinary waiters displays `QUEUED` unless a higher-priority
member state is present. When a clan has exactly one running member (`STARTING`
included) and no asking, reviewing, or failed member, the clan shows that member's exact
status: its label and styling, including the `FINALIZING` word and the `RETRYING (Ns)`
countdown, on both the clan row and the CLAN `Status:` line. For example, a session
running a `TESTING` monitor makes the clan read `TESTING`, while a failed monitor with
an authored stop label can read `TESTED [W1 F1 D9]` and still remain in the Failed
group. The status bucket, precedence, and count chip are unchanged; `TESTED` is only the
authored turn label, not proof that verification passed. When the aggregate is `QUEUED`
and exactly one direct member is queued, the clan row and CLAN `Status:` line also show
that member's admission rank (`QUEUED #3/4`), plus the same `pN` / `held by` extras the
member row shows. Two queued members stay generic `QUEUED` with no rank. The count chip
remains concrete and independent, so `QUEUED #3/4 [Q1 D4]` keeps the rank next to the
chip, and `QUEUED [Q3 W6]` reports three runner-slot waiters and six dependency, bead,
or time waiters without merging the two categories.

A clan row whose waiting members name unknown targets attaches an orange `?N`
immediately after the waiting count inside its count chip, as in `QUEUED [Q1 W3?2]`. `N`
counts distinct unknown agents, clan members, and beads across the clan's direct
`WAITING` members, so a dependency shared by two members counts once. Expand the clan to
see which member's `WAITING ?N` token names the stale target.

The uppercase `H` ladder starts with the selected workflow or sequential-session agent
node when that agent node is still open. The first press retreats that agent node by
exactly one fold level. From a visible hidden step, that press hides hidden steps while
leaving ordinary descendants visible and re-anchors selection to the agent-node owner;
the next press then collapses that still-selected agent node. Clans stay binary and do
not take this two-level path. After the selected agent node is collapsed, later presses
continue through the existing group-scoped remaining-agent-node, selected-clan,
remaining-clans, structural-fallback, and grouping-banner ladder. If the grouping banner
that `H` would collapse next contains any open standalone workflow, agent, or
sequential-session sase agent, and the selection does not own an open workflow or
session fold, the next press drives every such remaining agent node directly to fully
collapsed while leaving the banner open. Once remaining agent nodes are saturated, a
selection inside an open canonical clan makes the next press collapse only that clan. A
selected descendant re-anchors to its visible clan container; selecting the container
itself preserves selection without writing new selection memory. With the collapsed
container still selected, the following press drives every remaining open canonical clan
in the group directly to collapsed. A grouping banner, already-collapsed agent node,
already-collapsed clan, or invalid clan owner falls through to that group-wide sweep
immediately. The footer advertises `H collapse workflow` or `H collapse session` while
the selected agent node is open, then `H collapse sase agents`, then `H collapse clan`,
then `H collapse clans`, and only then `H collapse group`. Equal group names in other
tribe panels are never affected; merged layout intentionally treats the merged panel as
one scope. Ambiguous or malformed clan owners are skipped without blocking valid
siblings.

Whole-panel focus gives `H` a hinted collapse instead of the group-scoped ladder,
because it has no selected row or grouping scope to walk. It enumerates every currently
visible expanded agent node, clan, and top-level grouping banner in the selected panel —
never an owner hidden behind a still-collapsed parent banner, since that owner isn't
emitted as a row at all until its parent is expanded — assigns each one an adaptive hint
key, and shows the chips in place of jump hints. Typing a hint fully collapses that one
fold; an already collapsed fold is never offered, so every hint does something. `H`
never expands and never collapses the panel itself, which stays lowercase `h`'s job. A
panel with no expanded folds warns without arming hint mode; an already collapsed panel
keeps the existing `Panel is already collapsed` warning. The footer shows the configured
`hooks_or_collapse_all` key as `collapse fold` whenever the selected panel has an
expanded agent node, clan, or top-level banner to hint. `L`'s hint mode uses the same
enumeration but is not restricted to collapsible targets, so it also offers currently
collapsed agent nodes, clans, and banners and toggles whichever one you pick.

The `,H` leader chord is always one scope wider than the selection. From a row or banner
it opens the same collapse-only hints as whole-panel `H` for the focused tribe. From a
selected tribe panel — expanded or collapsed — it hints every expanded fold in every
expanded tribe panel and adds a title chip on each of those panels, so one keystroke can
collapse a different panel without navigating to it. Whole-panel focus stays on the
panel you started from, so `,,` repeats the picker against the current selection. The
footer reads `COLLAPSE · ALL TRIBES` in that wider scope. `,H` never expands and never
routes through LLM Calls compaction.

Visual treatment: every row carries a fixed-width tier-guide gutter built from one `│  `
segment per ancestor L0/L1 banner (in the parent tier's dim accent — project blue or
Patch cooler accent), so nesting reads as a tree at a glance. L0 project / bucket
banners use a sky-blue `▌` left bar and a heavy `━` rule. Patch banners, `BY_DATE`
subgroups, and banners that own another dotted-prefix subgroup use a cooler `▎` bar and
lighter `─` rule. Leaf name-root and dotted-prefix banners use a `▸` branch glyph with a
teal label. Singleton name-root groups suppress their banner entirely to reduce visual
noise.

The currently-focused side-panel row is marked with a thick accent-colored left bar,
**bold** text, and a translucent accent tint applied to the row background. The tint is
intentionally light so per-token status colors (running cyan, failed red, waiting
yellow, etc.) remain readable through the highlight — the bar and bold weight do most of
the work of marking the selection.

After a kill or dismiss, focus re-anchors on the visually-next row (rather than the next
row in input order) so the selection always lands somewhere meaningful in the rendered
tree.

## Grouping Modes

Press `o` on the Agents tab to open the grouping picker, then choose `p` Project, `d`
Date, `s` Status, or `m` Machine. The picker's layout row is a three-level ladder —
`Split by tribe`, `Merged`, `All tabs` — walked with `o` (next) and `O` (previous,
wrapping); `h`/`l` and the arrow keys move the highlight while the row is focused, and
the picker closes after a step. `oo` steps forward one rung, `oO` steps back. With fewer
than two agent tabs only `Split by tribe` / `Merged` are offered. Split shows one panel
per tribe titled `@tribe · N`; Merged shows one panel titled with the tab's label and
count (`All agents` while the tab strip is hidden); All tabs shows every tab in one
panel titled `All agents · every tab · N`, with a tab chip on named-tab rows and
`panels: all tabs` in the info row. Merged panels annotate named tribes inline on agent
nodes; the default tribe is implied there, so default nodes do not add `@default`
labels. Transitions keep the selected node: zooming in from All tabs lands on that
node's tab, and choosing a tab at the All-tabs level drills into it. Panel layout and
grouping mode are independent: stepping the ladder preserves the active grouping mode
and does not persist beyond the current session. The Agents tab shows a brief toast
(`Grouping: by project` / `by date` / `by status` / `by machine`) when the chosen mode
changes:

| Mode         | L0 buckets                                                                    | Notes                                                                                                                                                                               |
| ------------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `STANDARD`   | Project (with optional Patch sub-level)                                       | The "by project" default. Uses the 2-/3-level layout described above.                                                                                                               |
| `BY_DATE`    | `Today` / `Yesterday` / `This Week` / `Earlier`                               | Date bucket at L0, then a date-aware L1 subgroup. Sorted newest-first within each bucket.                                                                                           |
| `BY_STATUS`  | `Stopped` / `Failed` / `Running` / `Queued` / `Waiting` / `Done` / `Starting` | Bucketed by shared status semantics; status priority fixes bucket position. Standalone agent nodes precede name subgroups, with launch recency sorting units inside each partition. |
| `BY_MACHINE` | `here`, then remote aliases alphabetically                                    | Machine at L0, status at L1, then name-root/name-prefix groups. Project and Patch levels are omitted.                                                                               |

In `BY_DATE` mode, sase's TUI chooses one L1 subgroup style from the L0 date bucket:
one-hour windows (`09:00`) for `Today` and `Yesterday`, calendar-day labels for
`This Week`, and Monday-start week ranges for `Earlier`. The time anchor is `stop_time`
for terminal agents and `start_time` otherwise. The same anchor selects the L0 date
bucket, so an agent that started Friday evening and finished Saturday morning renders
under Saturday's bucket, matching the finish timestamp on its row. Buckets and their
subgroups sort newest-first. Workflow children inherit the parent's anchor so they stay
adjacent regardless of their own start time, and agents with no usable timestamp fall
into a `(no time)` subgroup that sorts last.

In `BY_STATUS` mode the L0 banner is the status bucket and L1 is the name-root, with the
same singleton-suppression rule as `STANDARD`. Status priority fixes the bucket order:
Stopped, Failed, Running, Queued, Waiting, Done, Starting. Within each bucket,
standalone sase agents render before every visible name-root subgroup; `start_time`
sorts agent nodes newest-first inside the standalone partition and subgroup units
newest-first inside the subgroup partition. The same partitioning rule applies under a
name-root, where directly contained agent nodes precede visible dotted-prefix subgroups.
Units with no launch timestamp sort after timestamped units within their partition, with
structural names and input order providing deterministic tie-breakers. A session, clan,
or workflow subtree uses its outer/root agent's launch time and remains contiguous.
Inside a clan, direct members still use the clan-local Failed, Stopped,
Running/Starting, Queued, Waiting, Done priority described above, with launch recency
breaking same-status ties; that order intentionally differs from this L0 bucket order.
Session follow-ups and workflow steps remain adjacent to their direct-member anchor in
their established internal preorder, including any name-prefix banners. The `Starting`
bucket remains last and its transient rows remain hidden, so startup-only work does not
displace active rows during daemon or launch refreshes. Each mode keeps its own
per-group fold registry, so collapsing buckets in `BY_STATUS` doesn't affect the project
layout you had in `STANDARD`. `BY_STATUS` banners are prefixed with semantic glyphs
(`▲`, `✗`, `▶`, `…`, `⏳`, `✓`, `◐`) so the bucket title still leads visually.

In `BY_MACHINE` mode, local rows use the `here` L0 bucket and remote rows use their
enrolled alias. Every machine is divided into the same priority-ordered status groups as
`BY_STATUS`, and every status banner remains visible even for a singleton because it
communicates lifecycle state. Within a status group, standalone sase agents precede
name-root/name-prefix groups and launch recency supplies the same deterministic
ordering. A status change can therefore move a row between subgroups while keeping it
under the same machine. As in the other nonstandard modes, project and Patch grouping
levels disappear and this mode keeps an independent fold registry.

The active grouping strategy is also surfaced in the Agents tab header via an
unbracketed `group: <label> (o)` element so the current session mode is always visible
after the cycle toast fades. Top-level header elements are joined by a dim `·`
separator: the leading counts group, an optional `filter:` element, an optional `view:`
element, the always-visible `group:` element, and an optional `refresh: <N>s (r)`
countdown. Only the agent status counts and the filter's match count keep square
brackets: an active filter reads `filter: <query> [matched/loaded] (/)`, where the dim
trailing `(/)` names the configured `edit_query` key. After the first scan, the header
starts with the visible sase-agent total `N`. One standalone agent or one sequential
session is one sase agent, regardless of whether the session is folded. A rootless clan
container contributes no sase agent itself; each direct clan member contributes one, and
a direct member that is a sequential session still contributes only one. A hidden
top-level `STARTING` agent contributes one sase agent even though it is not selectable
yet. Grouping mode, tribe ownership, and fold state do not change this projection.

Runner capacity lives at the right of the row as a machine-labelled
`⌂<machine> cap <load>/<limit>` chip, just before the model/project cluster, followed by
a `·` separator. `<load>` is occupied runner capacity units and `<limit>` is the current
effective `max_running_agents` budget (temporary override first, configured value
second). An override appends `*`; a report older than about 25 s appends `⟳<age>`;
invalid accounting renders `?/limit !` (never as free capacity); over-limit load appends
`▲`. The first report is a roster estimate (`~5/8`); later values are authoritative.
Normal agents claim `1.0`; non-default `%queue(weight=...)` / `%q(w=...)` launches claim
their authored capacity units, and a `%q(w=0)` launch claims none. Both numbers render
as integers when possible (`5/8`, not `5.0/8.0`), trimming to 2 decimals otherwise. If
the capacity snapshot is unavailable, sase's TUI renders `—/—` instead of deriving a
fake value from visible rows; when only the occupied value is unknown it renders
`—/<cap>`. Capacity belongs to the machine running this sase's TUI session and does not
change when the Agents list is searched, folded, filtered by tribe/project, or focused
on a remote machine tab. Rows from other enrolled machines never add to this machine's
cap, although they still show their own machine's capacity and weight badges (described
under **Queued** below). The visible running count and the global queued count remain in
the status strip, for example `6 [6 running · 1 queued]` with `⌂athena cap 5/8` at the
right: running counts Running-bucket nodes, while cap is reserved runner capacity.
Serial sessions share one claim; `-w 0` waits hold 0. The chip shares the usage-window
ten-step color gradient, keyed on free-capacity percent, so a given color means the same
headroom in both places; at or over capacity it becomes the inverted red chip, exactly
as an exhausted `0%` usage window. Compact density drops the machine prefix and keeps
the `cap` label (`cap 5/8`), never a bare `5/8`. Hovering the chip spells out headroom,
running-versus-cap, limit provenance, snapshot age, holders, and that `,l` opens the
capacity inspector. A session's running monitor holds its session's claim even when the
session row is under Done (see [Runner slots](../automation/monitors.md#runner-slots)).
The running count keeps its stable green count style. A nonzero queue count is
cornflower blue.

### Capacity inspector

Click the cap chip or press `,l` on the Agents tab to open the keyboard-first
capacity inspector. The command palette also lists it as **Show capacity inspector**.
It shows the latest authoritative machine report, including the limit source, snapshot
age, Running-bucket count, charged claims, shared-claim riders, live records holding
nothing, queued requests with admission's actual blockers, and diagnostics. Select an
agent row and press Enter to jump to it. Idle groups show a bounded preview when they
are long; **Show N more** expands a group and **Show first 10** collapses it. Press `y`
to copy the exact JSON printed by `sase agent load -j`. A new capacity report refreshes
the open inspector automatically.

An optional status strip follows in the form
`[S stopped · T starting · R running · W waiting · F failed · U unread · D done]`, with
numeric counts in place of the letters and zero-count metrics omitted. These buckets
classify the same sase agents as the leading total, using a sequential session's
normalized owner status instead of counting historical members separately. `stopped`
counts agents paused for plan approval, questions, or workflow human-input steps;
`starting` counts just-launched agents that have not yet surfaced as visible rows;
`running` excludes queued, waiting, failed, and stopped agents; `waiting` contains
genuinely blocked dependency, bead, and time waits, while the status strip's `queued`
count contains every live runner-capacity waiter; `failed` is terminal failed work;
`unread` counts terminal sase agents that still need acknowledgement; and `done` is
completed visible work that has already been acknowledged. Nested session/clan member
summaries remain concrete. The position/navigation denominator is a separate count:
rendered selectable roots, where a clan container is one row and a hidden `STARTING`
agent is excluded. During startup the header renders `Agents: …` until the first agent
scan has loaded, avoiding a misleading zero-agent count. Each TUI launch starts in
by-project grouping; cycling only changes the current session.

**Queued** holds `QUEUED` agents that have cleared every dependency, bead, and time wait
and need only runner capacity under their current admission budget. A queued row renders
as `QUEUED #3/12`, followed by `pN` for an explicit queue priority and by
`held by <armer>` while an [agent hold](agent-workflows.md#agent-holds) keeps it from starting. A
sequential session whose next member is queued shows that member's `QUEUED` status and
queue position on the session row. A clan with exactly one queued direct member does the
same on the clan row and CLAN `Status:` line; two queued members stay generic `QUEUED`
with no rank. Authored capacity renders as a quiet `cN` badge beside the existing `wN`
weight badge, and turns gold when the launch's budget exceeds the current effective
global limit. Non-default queue weights render as the same quiet `wN` badge used on
running rows and queue-ladder entries; an explicit zero renders `w0`, including on a
zero-weight monitor row. The detail pane
repeats these values as `Weight:` and `Capacity:` lines. Remote rows show the same
badges and detail lines using the values reported by the machine that owns the agent.
New prompts reject `capacity=0`, but a persisted legacy record with an explicit zero
capacity still renders `c0` and `Capacity: legacy 0 (exact-weight drain budget)`.
**Waiting** holds genuinely blocked but self-progressing agents — `WAITING` with a time
wait (`%wait(time=5m)`, `%wait(time=1430)`), a non-empty `waiting_for` dependency, or a
bead wait. A compact `WAITING` row summarizes named waits as one sequence of independent
tokens: agent counts keep the established status glyphs (`✗1 ▶1 ✓1 ?1`), while bead
counts keep the canonical Beads-tab status glyph (`○` open, `◐` in progress, `●`
closed). When a bead status matches a present agent bucket, the bead token follows that
agent token, for example `WAITING ▶1 ◐2` or `WAITING ✓1 ●1`; unmatched bead tokens trail
in canonical bead order. Zero entries are omitted. When a row waits on exactly one bead
and has no agent, name, or group wait dependency, sase's TUI shows that bead's ID
instead of a count. The ID has no prefix until status resolution; afterward it is
prefixed by the bead's status glyph (or `?` for an unknown status). Multiple or mixed
waits keep the counts. Unknown agents and unknown beads both render as `?N`; when both
are present they appear as adjacent independent counts, as in `WAITING ?1 ?2`. These
tokens sit directly after `WAITING` and before a reserved-tribe `!`, duration, or
countdown annotation. A `%wait(for_epic=)` follow appends teal `↪` tokens after the
counts: `WAITING ↪ epic…` while the epic launch is in flight, `WAITING ↪ ◐ sase-7k`
while following one epic, `WAITING ↪ ◐2` while following several epics, and
`WAITING ↪ !` when the follow is blocked. An armed target with no recorded follow stage
adds no row noise. They are not the trailing gold `◆` linked-bead badge that marks an
agent launched by `sase bead work`. **Stopped** keeps the strict "you need to act"
semantics for plan approval, questions, and workflow input.

## Related

- [TUI hub](index.md) — all Agents tab reference pages.
- [Agent row glyphs](agent-row-glyphs.md) — row glyphs, markers, and badges.
