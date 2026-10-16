---
title: Bead CLI queries
description: Commands for listing, searching, and checking SASE bead records.
---

# Bead CLI queries

This page describes commands for finding and checking bead records.

## `sase bead blocked`

Show all issues that have at least one active (non-closed) blocker. Rows use the same
plain status/size gutter as compact list rows, including the collapsed size column when
no blocked bead has a stored size.

## `sase bead doctor`

Run health checks on the beads database. Checks for:

- Missing `config.json`, event store, compatibility projection, or compatibility cache
- Projection drift between canonical events and `issues.jsonl`
- Redundant close events, including how many landed in the recent diagnostic window
- Invalid events or unreduced orphan phase records
- Uncommitted bead-state changes
- Orphan children (phase or nested-plan beads whose parent is missing)
- Plan-archive sidecar drift: bead-linked plans missing from the sidecar, orphaned
  compatibility plan-link indexes, and canonical plans found only in local plan roots
- Old-format or unresolved `design` plan references
- Issue prefix leaked as the project's ProjectSpec directory key instead of its
  `PROJECT_NAME` (reported; automatically repaired before the next top-level bead is
  minted, or repair on demand with `sase bead doctor --fix-issue-prefix`)
- Artifact references with unknown namespaces, missing targets, or ambiguous targets
- `claimed` beads whose assignee resolves to no agent artifact (reported only; run
  `sase bead open <id>` to clear them)
- `open` beads owned by a live agent that has not started work yet (reported only; it
  means the `bead_claim_checks` job is not running or is failing, since it should have
  claimed them)

If bead commands fail before opening a store, run `sase core health` first. It verifies
that the required `sase_core_rs` extension is importable and exposes the representative
bead CLI binding used by the fast path.

`--fix-projection` previews rows where `issues.jsonl` differs from replaying the
canonical event streams, then rewrites the projection from the streams after
confirmation. The repair refuses unexpected diffs: row additions or removals, status
changes, fields outside `closed_at`, `close_reason`, `close_history`, and `updated_at`,
or any `closed_at` move later. `close_history` is allowed because the first repair after
upgrading to a sase-core release with close history legitimately materializes archived
records for beads whose close reasons were destroyed by a reopen before sase-core
started archiving them — see [Close History](bead-triage.md#close-history). A successful
repair regenerates the local git-ignored export and commits nothing; a second clean run
writes nothing. Use `--yes` for non-interactive repair after reviewing the preview
through an external approval gate.

`--fix-issue-prefix` previews and, after confirmation, resets a store's issue prefix on
demand when it was leaked as the project's ProjectSpec directory key (e.g.
`gh_bobs-org__bob-cli`) instead of its `PROJECT_NAME` (e.g. `bob-cli`). The same repair
also runs automatically before the next top-level bead is minted. A deliberately
customized prefix is never flagged. The repair is forward-only: existing bead IDs keep
the old prefix, and only new top-level beads use the corrected one.

`--fix-plan-archive` previews recoverable plan-sidecar gaps and separates them from
entries that cannot be repaired safely on this machine. A candidate is recoverable only
when its canonical source exists in a resolved local plan root and passes committed-plan
validation. For a bead-owned gap, source frontmatter may omit `bead_id` or name the
expected bead; naming a different bead makes the candidate unrecoverable. Local-only
canonical plans are reported as drift but are explicitly “not necessarily approved”;
review the preview before applying.

After confirmation, the repair rechecks the complete finding set to catch races, adds a
missing `bead_id` to a bead-owned local source when required, archives the plan without
overwriting an existing canonical copy, and commits the plans sidecar as
`Backfill missing plan archives`. When that sidecar has a push remote, success also
requires the commit to be published. Missing, conflicting, or invalid source content is
reported as unrecoverable and is never fabricated. Use `--yes` only after reviewing the
same preview in automation.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-doctor) for this
command's options.

## `sase bead epic-symbols [<id>]`

List `--epic-symbol` whitelist entries from the working tree's Justfile (for a full ID
owned by another enabled project, that project's primary-workspace Justfile). With no
ID, every entry is printed. With an ID, only entries keyed to that bead or a descendant
suffix (`<bead-id>` matches `<bead-id>` and `<bead-id>.2`) are shown. Land and phase
agents should run this before closing: leftover entries go stale the instant the bead
closes, and `sase bead close` refuses while any remain.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-epic-symbols) for
this command's options.

## `sase bead list`

List issues with optional filtering. Without `--status`, the command lists `open`,
`claimed`, `ready`, `snoozed`, and `in_progress` issues; pass `--status=closed` when you
need closed history. When the default active query is empty and no explicit `--status`
was given, the command falls back to listing closed beads. `--status`, `--type`, and
`--tier` are repeatable.

Compact rows lead with aligned, colored type, task-type, and size indicators ahead of
the ID:

```
{type_glyph}<pad> {task_type_glyph}<pad> {status_glyph} {size_token}<pad> {id} · {title}{ ← parent_id}{  ⧖ age}
```

```
▸   ◐    <bead-id> · Attribute beads to the agent that created them  ⧖ 1d
◆ ≈ ◐  S <bead-id> · Fix xdist flake in artifact modal copy shortcut  ⧖ 1d
↳   ◐  M <bead-id>.3 · Record the creator on every bead creation path ← <bead-id>  ⧖ 1d
```

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-list) for this
command's options.

The fixed first column is the bead type. The second column is the task-type glyph for
task beads (`≈` flake, `⨯` bug, `·` untyped, and so on) and is blank-padded for non-task
beads so columns stay aligned. Status follows, then the stored phase/task size. The size
column appears only when at least one listed bead has a stored size, stays blank for
unsized rows, and collapses entirely for listings where no bead is sized. Type,
task-type, and size color are controlled by the same `-c, --color` option as the status
and ID styles, and the icons and size tokens remain distinct without color. Tier (`plan`
vs. `epic`) stays out of this column; it remains visible through `--tier`,
`--format full`, and `--format json`.

| Type    | Icon | Description                                          |
| ------- | ---- | ---------------------------------------------------- |
| `plan`  | `▸`  | Plan-like container with a tier; may be a child epic |
| `phase` | `↳`  | Sized executable child within an epic/plan bead      |
| `task`  | `◆`  | Independent work item; new tasks require a size      |

| Size Token | Stored Size |
| ---------- | ----------- |
| `XS`       | `xsmall`    |
| `S`        | `small`     |
| `M`        | `medium`    |
| `L`        | `large`     |
| `XL`       | `xlarge`    |

### Summary line

Non-empty `compact` and `full` listings end with a blank line and one summary line:

```
{shown}[ {status-adjective}] {type-noun}[ · {type counts}][ · {status counts}][ · {hidden}]
```

Every count in the summary describes the rows printed above it, except the explicit
`hidden` clause, which counts matching beads not printed because a limit was active. If
all printed rows share one type, the head folds that type into `plan`/`plans`,
`phase`/`phases`, or `task`/`tasks` and omits the type-count group. If all printed rows
share one status, the head folds that status into `open`, `claimed`, `ready`, `snoozed`,
`in-progress`, or `closed` and omits the status-count group. Mixed listings use the
neutral `bead`/`beads` noun and include the needed groups:

```
6 beads · ▸ 3  ↳ 3 · ○ 5  ◐ 1
2 open beads · ▸ 1  ↳ 1 · 4 hidden
20 closed plans · 5 hidden (--limit 0 shows all)
```

The hidden clause is `N hidden` when `--limit` was explicit. When SASE applied the
default closed-list limit, it is `N hidden (--limit 0 shows all)`. With color enabled,
summary glyphs reuse the row type/status accents, folded type and status words use their
matching accents, counts stay plain, and the hidden clause is dim. `--format json` does
not print the prose line; its envelope carries the same printed-row counts in `by_type`
and `by_status`, including zero buckets for every known type and status.

Active (`open`/`claimed`/`ready`/`snoozed`/`in_progress`) listings are unlimited by
default. Whenever the final status scope includes `closed` and `--limit` is omitted,
only the newest 20 beads print; pass `--limit 0` for the full closed history. When
`--since` or `--until` is present, the newest-20 closed default does not apply; an
explicit `--limit` still wins.

Creation-date filters accept `Nh`/`Nd`/`Nw`, `today`, `yesterday`, `YYYY-MM-DD`, and
`YYYY-MM-DDTHH:MM`; day-granular `--until` bounds include the full named day. These CLI
flags bound bead creation time, unlike sase's TUI `since:` and `until:` filter tokens,
which bound last activity. A bead with no usable creation timestamp is omitted whenever
a creation-date bound is present.

## `sase bead ready`

Show task beads whose explicit status is `ready` and whose dependencies are all
`closed`. Epic work does not appear: phase beads are preassigned at epic launch rather
than entering a derived ready queue. When no rows qualify, the command prints
`No ready task beads (epic work is preassigned at launch).` A ready task with an active
blocker remains stored as `ready` but is omitted until the blocker closes. Rows use the
same plain status/size gutter as compact list rows, including the collapsed size column
when no ready bead has a stored size.

## `sase bead search <query>`

Find beads whose indexed text fields contain a case-insensitive literal substring by
default. Pass `-e`/`--regex` to interpret the query as a regular expression; regex
search is case-insensitive unless the pattern starts with `(?-i)`. Regex matching is
unanchored, and `^`/`$` anchor the whole field unless the pattern uses `(?m)`. A pattern
that starts with `-` needs the `--` separator, such as
`sase bead search --regex -- '-x'`. Current indexed fields include ID, title,
description, the filing reason (`creation_reason`), notes, design/plan path, artifact
references, external issue reference, owner, assignee, model, phase/task size, Patch
name/bug ID, status, type, and tier; timestamps are not searched. Compact output prints
a field-labeled snippet for matches outside the title and description when the renderer
has that field's text. A match that hits only `creation_reason` still returns the bead,
and `--format json` lists `creation_reason` in `matched_fields`, but the compact snippet
line for that field is omitted. Unlike `sase bead list`, search includes `open`,
`claimed`, `ready`, `snoozed`, `in_progress`, and `closed` beads by default, so it is
the quickest way to recover older context.

Compact output prints each matching bead with the same type/status/size gutter as
`sase bead list`, followed by a short snippet. For multi-line fields such as
descriptions or notes, the snippet uses the line that matched the query when possible
instead of always showing the first line. JSON output exposes the exact `matched_fields`
list for each result.

```bash
sase bead search auth
sase bead search '^work-' --regex
sase bead search auth --format json
sase bead search auth --format full --limit 3
sase bead search auth --status open --type phase
sase bead search auth --type plan --tier epic
```

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-search) for this
command's options.

## `sase bead stats`

Show project statistics: total, open, claimed, ready, snoozed, in-progress, and closed
counts, plus plan, phase, task, flag, and due-flag counts.

## `sase bead task-type`

Inspect the effective task-type catalog assembled from builtins, plugins, and project
config. With no subcommand, `sase bead task-type` delegates to
`sase bead task-type list`.

```bash
sase bead task-type
sase bead task-type list
sase bead task-type list -a
sase bead task-type list -j
sase bead task-type show flake
sase bead task-type show flake -j
```

`list` prints a colored table of slug, label, summary, source, and whether agents may
file the type. Agent-uncreatable types such as `github` are hidden unless `-a/--all` is
passed. `show <slug>` prints the label, `when_to_use`, every field with type,
requirement, role, help, and validators, the body template, the triage threshold, and
provenance. Reads are not audited.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-task-type) for
this command's options.

## `sase bead touched <agent>`

List the beads one agent touched, newest touch first, one row per bead with verb chips,
title, and relative age. Durable index rows merge with `viewed` entries from the
`sase bead show` view log (which is neither written nor synced) and audited `bead:`
reads (`read`), matching the Agents-tab `Beads:` sub-section row for row for touched
beads. `read` comes from `sase bead read` / `sase artifact read bead:` with reasons;
agents are now refused at `show`, so `viewed` rows predate that guard. Automation
running inside agents (symvision, flag checks, commit hooks) sets
`SASE_BEAD_SKIP_VIEW_LOG=1` and bypasses the guard. The CLI lists touched beads only;
the panel also marks assigned but untouched beads `own`. A bead with read reasons prints
one extra indented line with the newest reason (`  ↳ <reason>`); JSON rows carry
`read_reasons`.

```bash
sase bead touched <agent-name>
sase bead touched 0oa -l 10
sase bead touched 0oa -v noted -v closed
sase bead touched 0oa -v viewed
sase bead touched 0oa -v read -j
```

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-touched) for this
command's options.

When the agent has no touched beads, or none match the `-v` filter, the command prints
`No beads touched by <agent>.` (`-j` prints an empty `touches` list instead).

Each row leads with one glyph for its strongest verb, shared with the Agents-tab
`Beads:` rows. The table lists glyphs from strongest to weakest, so a bead that was both
viewed and removed shows `◇`:

| Glyph | Verb(s)                                                              |
| ----- | -------------------------------------------------------------------- |
| `✚`   | `created`                                                            |
| `✓`   | `closed`                                                             |
| `↻`   | `reopened`                                                           |
| `✎`   | `updated`, `noted`, `ready`, `snoozed`, `dep`, `linked`, `ref`, `+1` |
| `←`   | `read`                                                               |
| `◇`   | `viewed` (also an `own`-only panel row)                              |
| `⌫`   | `removed`                                                            |

Durable verbs come from a derived per-project touch index
(`~/.sase/projects/<project>/agent_bead_touches.json`) that is rebuilt from the bead
event streams after `sase bead sync`, by the periodic artifact-link backfill job, and
after bead mutations that run through SASE's Python mutation path (for example
`sase bead create`, `sase bead close`, note-style updates, and bead actions taken from
sase's TUI or gates). Mutations that the Rust fast path handles directly (typically
plain `sase bead update`, `+1`, or `snooze`) do not refresh it. Reading the index never
refreshes it, so rows reflect the last refresh; a missing index lists no durable verbs,
though `read` and `viewed` rows still appear. Run `sase doctor -C beads.touch_index` to
check it: a fresh or not-yet-built index reports OK, a stale index warns and lists the
changed and vanished streams, and an unreadable or wrong-schema index warns that the
next refresh rebuilds it. `sase bead sync` is a reliable way to refresh it on demand.

## Related

- [Bead CLI](bead-cli.md)
- [Reading beads](bead-cli-inspection.md)
