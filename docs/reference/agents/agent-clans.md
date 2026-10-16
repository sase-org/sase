---
title: Agent clans
description: Look up how parallel agent sessions are grouped and displayed.
---

# Agent clans

This page describes the grouping and display behavior of agents working in parallel.

## Parallel Agent Clans

An agent clan is a container, never an agent. A `%clan` prompt spells its full
hood-qualified `%id`; other members can use `%id(<id>, clan=<name>)` to derive that name
and join the same clan:

```text
%id:release.build
%clan:release
Compile the release.
---
%id(test, clan=release)
Test the release.
---
%id(land, clan=release)
%wait:release.build,release.test
Publish the release after both members finish.
```

The short form is `%c:release`. `%clan` is create-only: exactly one prompt may declare a
clan, and declaring a clan that already exists is an error. Use
`%clan(<name>, tribe=<tribe>)` (or the `%c(...)` alias) to assign the declaration's
tribe to the entire clan generation; `tribe=` on `%id` cannot be combined with clan
membership. Every other member uses `clan=`. That form joins an existing clan or creates
it implicitly without a tribe, takes exactly one member id, allows dotted ids, and
accepts a leading `!` for forced reuse. Static names and templates such as
`%id(cld, clan=research.{@1})` work; the derived `research.{@1}.cld` name flows through
normal template allocation. In macro swarms, prefer keyed markers like `{@1}` so every
clan member, wait, fork/resume target, and prose reference is substituted in the parent
dispatch before any member starts. Bare templates such as `research.@` still work, but
their references use latest-wins lookup and are unsafe for late-starting swarm members.
See [Macro template directives](../macros/directive-syntax.md#directives) for `{@<id>}`
and `{@<id>!}`.

### Launch-time clan summaries

The declaring member can attach a short description to its clan generation. sase's TUI
displays this description near the top of the clan's `CLAN` panel; it is metadata and is
not sent to the member as work instructions. When the clan belongs to a tribe, the
tribe's `TRIBE` document (shown when the whole tribe panel is focused) also indexes this
description in its `CLAN SUMMARIES` section (see
[Tribe Side Panels](../tui/agents-tab-panels.md#tribe-side-panels)). Use a literal for
stable context, the double-colon shorthand for a larger text block, or an executable
when the description depends on state available as the runner starts. A literal keeps
the work prompt immediately below the declaration:

```text
%id:research.lead
%clan(research, tribe=study, summary="Audit authentication and authorization")
Review the security boundary.
```

The text-block shorthand ends when the next top-level directive or macro reference
begins:

```text
%id:release.lead
%clan:release:: Coordinate the release checks and summarize blockers.
#release_work
```

For a computed description, name an executable instead:

```text
%id:triage.lead
%clan(triage, summary_script=./describe-triage)
Triage the current failures.
```

The value may also contain shell-style quoted arguments. Use the directive text-block
form when the command itself contains spaces or quotes:

```text
%id:release.lead
%clan(release, summary_script=[[sase_clan_summary_plan "plans/release plan.md"]])
Coordinate the release.
```

`sase_clan_summary_plan` renders any valid tale or epic plan with the same logical
PLAN-lane presentation used by sase's TUI. Its first argument is the plan reference;
when that argument is omitted, it reads `SASE_EPIC_PLAN_REF` instead.

`summary=` accepts the usual directive values: a bare token, a quoted string for text
containing spaces or special characters, or a multiline `[[...]]` text block. The `::`
shorthand requires a following space or end of line and captures everything until the
next top-level line that starts a directive (`%`) or macro reference (`#`). That
captured text becomes only the summary, so use `summary=` when ordinary work
instructions follow the declaration directly. `summary=` and `summary_script=` are
mutually exclusive, and both belong only on the create-only `%clan` declaration;
`%id(..., clan=...)` joiners cannot declare or replace a summary.

A summary executable may run synchronously twice: first while SASE extracts launch
directives, before dependency waits, runner-slot admission, and workspace preparation,
and again after the primary workspace and every applicable sidecar and linked-repository
workspace have been prepared. The first attempt uses the workspace path with which the
runner started; for a deferred-workspace launch, that is the placeholder workspace. The
second attempt uses the real prepared workspace claimed after the wait. A waiting runner
that re-execs to load updated SASE code can repeat this sequence, so summary executables
must be read-only and idempotent.

A bare executable name is resolved next to the running Python interpreter and then on
`PATH`; a value containing `/` is resolved as an executable absolute path or a path
relative to that initial workspace. SASE first probes the complete value as a literal
executable, preserving executable filenames that contain spaces. If that fails, it
applies shell-style quoting, resolves the first token by the same rules, and passes the
remaining tokens directly as argv; it never invokes a shell.

Each attempt inherits the runner environment available at that point. The
post-preparation attempt therefore sees environment updates made while preparing the
workspace and linked repositories. SASE gives both attempts the same identity contract:
it overrides `SASE_CLAN_NAME`, `SASE_CLAN_GENERATION`, and, when the declaration has
one, `SASE_CLAN_TRIBE` (otherwise an ambient clan-tribe value is removed). Epic work
also provides `SASE_EPIC_PLAN_REF`, `SASE_EPIC_PLAN_SNAPSHOT`, `SASE_EPIC_BEAD_ID`,
`SASE_PHASE_BEAD_ID`, and `SASE_EPIC_CLAN_TRIBE`; SASE reconstructs these values from
persisted agent metadata after launch-only variables have been consumed. The snapshot is
an absolute, project-scoped, guaranteed-local best-effort copy used by the built-in epic
summary script after ordinary checkout candidates. The original plan reference remains
the displayed and persisted association.

Standard output becomes the summary and standard error is appended to the agent log.
Every attempt has the same 20-second timeout and non-fatal failure handling, and the
stored summary is capped at 32 KiB of UTF-8. Missing executables, malformed quoting,
timeouts, nonzero exits, and empty output are logged without blocking the agent launch.
SASE uses the last successful non-empty output: a successful post-preparation attempt
replaces the extraction-time value, while a later failed or empty attempt leaves the
newest successful summary untouched.

SASE trims trailing whitespace and records the result in the clan's durable record under
`<sase_home>/agent_clans/<clan>.json`, keyed by clan generation. What is recorded and
when: a `%clan` declarer records its declared `tribe=` and either its literal `summary=`
(source `declared`) or its `summary_script=` (source `declared`) plus the script's
non-empty output (source `script`); an epic-nominated joiner records its script output
(source `script`) and script (source `propagated`); any member carrying the epic
environment tribe records that tribe (source `propagated`, fill-only); every
post-preparation summary refresh records the fresh non-empty output (source `script`);
and just before any artifact directory is deleted, its clan attributes are captured into
the record (source `captured`, fill-only).

Precedence: for a `(clan, generation)` key, an attribute present in the record
(including an explicit edited-unset tombstone) wins over member-derived values, so
member artifacts that predate the record — legacy, imported, or remote artifacts — still
resolve, but never override it. `declared`, `script`, `edited`, and `inherited`
overwrites beat member values; `propagated` and `captured` only fill missing attributes,
so a clan-level tribe edit sticks even when newer epic members carry `clan_tribe=epic`.
An empty or failed summary never erases a recorded one. The scan contract therefore
resolves summaries and tribes within one clan generation from the record first, falling
back to the newest explicit member declaration only when the record is silent. Rich
markup is rendered when valid and shown as literal text when invalid.

Because the record outlives any single member, clan summaries and tribes survive kills,
dismissals, relaunches, and full restarts: deleting the declaring agent's artifacts
captures its attributes first, and later scans — full, bounded, and delta alike — apply
the record over whatever member artifacts remain. The saved description is distinct from
the foldable sections that sase's TUI synthesizes below it from member artifacts and
activity.

Pressing `N` on a clan row or on any clan member sets the whole clan generation's
recorded tribe through the same durable path, and clearing it writes an explicit
edited-unset tombstone. The unset sticks even when members still carry an epic tribe,
because fill-only `propagated` values never overwrite the record. Member edits also keep
their `agent_meta.json` and `%clan` prompt rewrites so older readers still see the new
tribe.

Re-creating a clan: when a launch creates a new generation of a previously recorded clan
without an explicit `tribe=` (and without an epic environment tribe), the new member
inherits the remembered tribe; without an explicit `summary=`/`summary_script=` (and
without an epic nomination), it re-runs the remembered summary script through the usual
launch-time summary path, falling back to the remembered text when the script is missing
or produces no output. Inherited values are stored in the new member's metadata,
recorded under the new generation with source `inherited`, and named with their source
generations in one agent-log line. Explicit values always win, tombstoned tribes are
never inherited, joining an existing generation changes nothing, and a runner re-exec
does not re-apply values already in preserved metadata.

Clan membership is execution-neutral. It does not add wait edges, change launch order,
choose a workspace or model, or otherwise rewrite launch behavior. Use `%wait`
explicitly where ordering is required; waits between members of one clan generation are
shown as derived dependency waves in the Agents tab. A wave is a layer, not a barrier,
so a later wave may start while earlier work is still running. The `clan=`, `session=`,
and `tribe=` keywords on `%id` are mutually exclusive, and none can be combined with
`%clan` in the same segment.

The retired family keyword on `%id` is always accepted as `session=`. The retired
`family` and `kind` agent-query values, the `--next-fork` family value, a gate
`"fork": "family"`, and the `SASE_AGENT_FAMILY_ATTACH` environment variable are always
accepted as their session replacements. New prompts should use the session spellings. A
record that was already stored still reads. The retired family keyword and `session=`
together are an error. See [feature_flags](../config/feature-flags.md#featureflags).

The clan name is permanently reserved as a container name and cannot also belong to an
agent. Each member must be named `<clan>.<suffix>`; launch planning rejects an
out-of-hood name before spawning it. A clan may contain ordinary agents, workflow steps,
and sequential sessions whose names stay inside the same hood.

`%wait:<clan>` waits for every member of the newest clan generation. An exact member
name targets only that member. Killing or dismissing the synthetic clan row cascades to
its live members, while acting on one member leaves the rest of the clan alone.

Retrying a clan member from sase's TUI keeps it in the same named clan. sase's TUI
rewrites the prompt into `%id(<new-member-id>, clan=<clan>)`, where the member id
carries the retry suffix. It does not repeat the create-only `%clan` declaration. If the
original prompt used a clan template such as `research.@` or `research.{@1}`, sase's TUI
first substitutes the member's concrete clan, such as `research.2`.

sase's TUI renders every grouping row with a trailing color-coded name and no kind icon.
A clan is synthetic and ends with an orchid `<name>` after its rolled-up status counts;
its `@tribe` labels follow the name. A real multi-member session root ends with its bare
azure container `<name>`, while its concrete member rows retain their exact `--<suffix>`
names. Plain agent annotations and a lone plan proposer with only its display-only
planner child remain gold. Press `l` once on a collapsed clan to reveal its direct
members. The clan's outer fold is binary, so move to a session or workflow row and press
`l` there to reveal that row's descendants. Lowercase `h` moves from any agent, Bash,
Python, parallel, embedded, or compatibility workflow step to its validated immediate
workflow, session, clan, or tribe parent without changing fold state. Uppercase `H`
first retreats a selected open workflow or sequential-session agent node by one fold
level. After that agent node is collapsed, the next press fully collapses every
remaining open agent node in the next grouping scope, then collapses only the open
canonical clan enclosing the selection. The next press from that collapsed clan
container collapses every remaining open canonical clan in the group, and only then does
a later press fall back to selected-row structural handling and grouping collapse. A
selection without an open enclosing workflow, session, or clan proceeds directly to the
group-wide remaining-agent-node sweep. Selecting the clan row shows an aggregate `CLAN`
header and a navigable summary of every section represented across its members. In the
Agents list, one-wave clans keep status priority — Failed, Stopped, Running/Starting,
Queued, Waiting, Done — and then launch recency within a bucket. Layered clans use
dependency wave order, with launch order breaking ties and unresolved members trailing.
The `CLAN MEMBERS` jump-panel roster uses wave order for layered clans, matching the
tree; one-wave clans keep chronological launch order. These numbers stay stable while
statuses change. The runtime is the union of member run intervals, with human-wait
windows excluded — including a gate turn's pending and settling window — so concurrent
members are not double-counted. When a sequential session has a concrete agent or
monitor turn currently executing, the collapsed and expanded session container row shows
`🏃‍♂️ <current-turn-runtime> / <session-total-runtime>` so the active turn duration is
visible without opening the session. A clan container's live suffix collapses its
parallel lanes with a minimum instead, since more than one lane can be live at once:
`<lowest-running-lane-runtime> / <clan-total-runtime>`, where a sequential-session lane
contributes its own total runtime -- the same value its own row shows to the right of
its suffix.

### Clan summary folding

Clan summaries collect member errors, output and workflow variables, replies, SASE
context, slow tool calls, and prompts below the saved clan summary in the metadata body;
the numbered `CLAN MEMBERS` roster lives in the jump panel, followed by `CLAN NEIGHBORS`
when another clan shares its dotted hood. Two clans are neighbors when their presented
names share the same root hood (`foo`, `foo.bar`, `foo.baz`, and `foo.bar.deep` share
`foo`), compared case-insensitively at dot boundaries and excluding the selected clan,
ordinary rows, malformed names, and unrelated prefixes such as `foobar`. Neighbor rows
show full clan names and keep each target's stable identity including its generation.
Known-empty section kinds are omitted. If required disk-backed content is not known yet,
the document ends with one dim `⋯ scanning member data…` tail instead of showing a
placeholder for each section. Members and neighbors share one continuous number ladder
up to 100 targets: `0`–`9` for documents with at most ten entries, or `00`–`99` for the
first 100 entries in a larger document. Additional entries appear only in an unnumbered
remainder count. Press a number while the clan is selected to expand only that member's
ancestor chain and jump to its row, or to reveal a neighboring clan through folds and
panels; with `sase-1ao.3` selected the neighbor digit lands on `sase-1ao` and back
again, and `Ctrl+O` returns to the previous selection. `Esc` cancels a pending first
digit. Use `Ctrl+J` and `Ctrl+K` to move between the visible section headings; numbered
roster rows live in the jump panel, so they are neither `Ctrl+J`/`Ctrl+K` stops nor
`za`/`zA` targets.

The summary has three session-only fold levels:

| Level | Clan summary content                                                                                                  |
| ----- | --------------------------------------------------------------------------------------------------------------------- |
| 1     | Up to 100 numbered member and neighbor rows (in the jump panel) plus a heading and count for each represented section |
| 2     | Bounded triage digests, such as one-line error and reply previews, variable values, and context-lane summaries        |
| 3     | Full section bodies grouped by member for detailed investigation                                                      |

Press `zz` to cycle levels 1 → 2 → 3 → 1. Press `zZ` below level 3 to open every fold to
level 3, or press it at level 3 to close every fold to level 1. Use `z1`-`z3` to select
an exact level. `za` cycles only the section at the top of the metadata viewport; `zA`
toggles that section between collapsed and fully expanded. A valid panel-level cycle,
extreme toggle, or direct selection clears these per-section overrides. The `Fold: N/3`
field in the `CLAN` header always shows the current panel level, while the `▸`/`▾`/`▼`
heading glyph shows each section's effective level. Unknown disk-backed sections stay
hidden during enrichment behind one `scanning member data…` tail; represented sections
appear when known, and known-empty sections remain omitted. The compact roster and its
numeric jumps remain available at every level.

The fold prefix is available only while the Agents tab is active. Press uppercase `Z` to
zoom an agent row's detail panel or the selected tribe panel's metadata document, `=` to
isolate or restore a tribe panel from whole-panel focus or a row selection inside a
panel, and `-` to sweep every open agent node and clan (never a grouping banner) in the
focused tribe panel closed in one press (or restore the last sweep) from whole-panel
focus, a row selection, or merged layout; lowercase `z` starts fold mode. Fold state is
panel-wide and applies when a clan or a sase agent is selected. Using a fold chord on a
regular sase agent folds its `NEIGHBORS` and `SLOW TOOL CALLS` sections across that
agent's own three-level scale, leaves its other sections unchanged, and updates the
session state for the next container selection.

### Epic bead-work example

`sase bead work <epic-id>` puts every phase worker and the final land agent in clan
`<epic-id>` and tribe `@epic`. `%wait(for_epic=)` follows epics an agent launches and is
unrelated to tribe `@epic`. For an epic named `sase-6g`, the generated prompt has this
shape:

```text
%id(!sase-6g.1, bead=sase-6g.1)
%clan(sase-6g, tribe=epic, summary_script=sase_clan_summary_epic)
#bd/work_phase_bead:sase-6g.1
---
%id(!land, clan=sase-6g, bead=sase-6g)
%wait(sase-6g.1, for_epic=false)
%wait(bead=sase-6g.1)
#bd/land_epic:sase-6g
```

Generated phase and land waits use `for_epic=false` on their agent dependency and also
require phase-bead closure. A user-authored `%wait:worker` normally follows any epics
that worker launches, but this generated schedule already uses its phase beads as the
completion condition. The clan container itself is not a land agent or other executable
process. The `bead=` association lets each runner claim its phase or epic only after
those waits and workspace preparation. If the epic clan already exists during a re-work,
every phase and land segment uses the `clan=` join form. The built-in
`sase_clan_summary_epic` script renders the epic's
[launch-time clan summary](#launch-time-clan-summaries).

## Related

- [Agents and workspaces](index.md) — the section hub.
