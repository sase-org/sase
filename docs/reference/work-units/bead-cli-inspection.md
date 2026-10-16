---
title: Reading beads
description: Commands for adding notes and reading detailed bead records.
---

# Reading beads

This page describes commands for reading bead records and their history.

## `sase bead history [<id>]`

Replay one bead's canonical event stream as an ordered, field-level timeline. Compact
output prints the timestamp, actor, operation, and changed field names for each event.
Full output prints every prior and new value, including earlier note revisions that
later updates replaced. JSON emits one envelope with `issue_id`, `schema_version`, and
`entries`. A duplicate close that the reducer treated as inert is labeled as redundant
instead of rendering as an empty change row.

`--lost-notes` is a historical repair for stores that predate the append-only note log:
it reports notes snapshots whose nonblank text is absent from the current notes, the
pattern only the old whole-field `sase bead update --notes` replacement could produce.
Since notes are structured, append-only records now — appending, editing, and retracting
each keep their own event and never overwrite another record's bytes — new data cannot
lose a note this way; the check exists to find and fix damage already done to older
stores. With no positional ID it scans the whole store; with an ID it checks only that
bead. Findings are sorted by bead ID. Add `--restore` to preview provenance-tagged
appends, prompt once, and restore every finding through the same atomic append mutation
used by `sase bead note`. Restoration is idempotent: restored text is retained by later
append snapshots, so a second scan reports nothing. Non-interactive restoration declines
safely unless `--yes` is supplied, and `--restore` without `--lost-notes` is a usage
error. See the
[bead note recovery migration note](../upgrading/work-units.md#bead-note-recovery).

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-history) for this
command's options.

## `sase bead note <id> [<text>]`

Append, edit, or retract one entry in an issue's note log. A bead's notes are a list of
records, not one free-text field: each record carries its own `timestamp`, `author`,
`text`, and (once edited) `edited_at`/`edited_by`. `sase bead show` renders one dated,
attributed block per record, addressed by a 1-based ordinal (`#1`, `#2`, …) that shifts
whenever an earlier record is removed — re-read `show` after any edit or removal before
addressing another one by ordinal.

With no `--edit`/`--remove`, `text` is required and the mutation records a
`note_appended` event containing only the new entry text; the reducer builds the
timestamped, attributed record from the event's own metadata. The mutation runs
atomically in the Rust bead store, and concurrent note writers merge as separate records
rather than replacing each other. `--edit N` rewrites record `#N`'s text and stamps
`edited_at`/`edited_by`, keeping the original `timestamp`/`author`; `sase bead show`
renders the edit marker alongside the record. `--remove N` retracts record `#N`; the
rendered log drops it, but `sase bead history` still replays the original. `--edit` and
`--remove` resolve the ordinal to the record's stable ID before writing any event,
reject an out-of-range ordinal without writing, and are mutually exclusive; `--edit`
requires `text`, `--remove` forbids it.

For the flattened text projection used by search indexes, bead pages, and
`--field notes`, see `notes_text` under [`sase bead show`](#sase-bead-show-id-id2).

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-note) for this
command's options.

## `sase bead read <id> [<id2> ...]`

Read one or more beads with output identical to
[`sase bead show`](#sase-bead-show-id-id2). Agents consulting beads to do work must use
this command; `show` is the unaudited human command.

```bash
sase bead read <bead-id> -r "Need the epic scope"
sase bead read <bead-id> <another-bead-id> -r "Need both designs" --format json
```

`-r/--reason` is required and must be non-empty. Before printing, the command appends
one audited, agent-attributed read row per resolved bead to `artifact_reads.jsonl` with
ref `bead:<full-id>` (shorthand input still stores the full ID) and the trimmed reason —
the same row shape as `sase artifact read bead:<id>`. `..` expansion audits each
expanded bead once, duplicates collapse after resolution so each bead is audited once
per invocation, and unresolved IDs audit only the beads that did resolve. An
audit-append failure prints the error, prints no bead output, and exits 1.

Inside a SASE agent run with an identity, the command also queues one
`agent:<name> -read-> bead:<id>` graph-edge row per bead; outside an agent run it prints
the one-line "not recorded as a graph edge" note on stderr instead. Link queueing is
best-effort: a failure prints `Error: could not record read link: ...` but the beads
still print.

## `sase bead show <id> [<id2> ...]`

Display complete details for one or more issues including status, type, task type, tier,
parent lineage, dependencies, blockers, typed artifact links, the filing reason when one
was stored, description, the rendered task-type body block, notes, Patch metadata,
model, linked plan path, artifact references, external issue reference, creator, and the
hosted page URL when one resolves locally. See
[Creation Reason](beads.md#creation-reason). Full IDs and shorthand suffixes are
accepted. Multiple IDs render in the order given, and duplicates collapse after
resolution, so a full ID and its shorthand render one block. If one ID in a batch is
missing, the beads that resolved still print first; after output or the pager exits,
stderr gets one `Error: issue not found: <id>` line per miss and the command exits 1.

Run inside a SASE agent run with an identity (and without `SASE_BEAD_SKIP_VIEW_LOG=1`),
`show` refuses before printing anything: it exits `2`, prints nothing to stdout, records
no rows, and names the matching `sase bead read ... -r "<why>"` command on stderr.
Automation running inside agents (symvision, flag checks, commit hooks) sets
`SASE_BEAD_SKIP_VIEW_LOG=1`, so its `show` probes bypass the guard. `viewed` rows
written to `~/.sase/projects/<project>/bead_views.jsonl` before this guard still surface
as the weaker `viewed` verb in
[`sase bead touched`](bead-cli-query.md#sase-bead-touched-agent) and the Agents-tab
`Beads:` rows; the log is neither written nor synced, so another machine's agent views
are not visible here. Use [`sase bead read`](#sase-bead-read-id-id2) when the
consultation should be audited.

An ID ending in `..` expands to that bead plus its direct children in one argv token:
`sase bead show <epic-id>..` is exactly
`sase bead show <epic-id> <epic-id>.1 <epic-id>.2 ... <epic-id>.8`. Expansion is not
recursive — only the target's direct children (phase beads and child epics, one level)
are included, sorted by the integer suffix after the final dot when it parses as digits,
with any unnumbered children kept after those in the order the store returned. A target
with no children is not an error; it renders alone. Expansion happens before the
existing positional dedup, so `sase bead show tt.3 tt..` renders `<epic-id>.3`, then
`<epic-id>`, then its remaining children — `<epic-id>.3` is not repeated. A malformed
token such as `..` or `tt...` reports
`Error: invalid ID expansion: '<token>' (expected <epic-id>.., for example <epic-id>..)`
and exits 1. A stem that does not resolve reports `Error: issue not found: <stem>` and
exits 1, the same as any other missing ID, while beads that did resolve still print.

Full IDs follow the same cross-project contract described in
[Bead ID Arguments](beads.md#bead-id-arguments): `show` first asks the current project's
bead store, so a local bead always wins when the same full ID also exists elsewhere. If
the local store misses and the ID has a full project prefix, SASE looks for the exact ID
in enabled projects' canonical bead stores. The fallback is read-only and only runs
after a local miss, so an all-local invocation does not scan the project registry.
Shorthand suffixes such as `1e` remain local-only because they carry no prefix to route
on.

Use `-P/--project PROJECT` to pin the entire invocation to one enabled project by
canonical key, display name, or alias. With a pinned project, shorthand suffixes resolve
inside that project's store and prefix routing is skipped:

```bash
sase bead show bob-cli-1e          # works from another enabled project
sase bead show 1e --project bob-cli
```

If no enabled project's store holds a full ID, the error remains
`Error: issue not found: <id>`. If the exact ID exists in more than one enabled
project's store, `show` reports an ambiguous bead ID with the candidate projects; pin
one with `-P/--project`. Two projects that merely share a prefix are not ambiguous when
only one of them holds the ID. If the project that looks like the owner (by name, alias,
or stored prefix) has no materialized or readable bead store on this machine, `show`
names that project and says its store is not available.

`show` never creates a bead store in the current directory. From a directory with no
store, full IDs still route, but a shorthand suffix needs `-P/--project`; without it the
command reports `Error: no local bead store is available`. A multi-ID batch may mix
projects: each bead renders with its own project's plan paths and page URL, and an
`<epic-id>..` expansion reads the children from the epic's own store. Aggregate read
commands (`list`, `search`, `ready`, `blocked`, and `stats`) stay project-local.

With `--format full`, a multi-bead batch prints one detail block per bead. Each block is
preceded by a left-aligned ordinal divider such as `── 1/3 ───`, styled with the same
additive palette as the rest of the detail view. Single-ID output has no divider and
keeps the same bytes as before. `--format compact` prints one aligned compact table in
argv order. `--format json` preserves the existing single-bead envelope for one ID; two
or more IDs emit an array of those envelopes, omitting any misses from the array while
using exit 1 to report that the array is incomplete. An expansion token (`<epic-id>..`)
always emits the array form too, even when the epic has exactly one child or none, so a
script never has to inspect the store to learn which shape it is parsing.

A typed task prints a `Task type` row and appends the spec's body template below the
description. When the type is unknown on this machine, the raw field pairs print under a
`(not installed on this machine)` header instead. An `EXTERNAL` section (`Ref: <value>`)
appears only when the bead has an external reference set via `-x/--external-ref`. The
`CREATED BY` block localizes an agent's durable global name and links to its hosted
agents-sidecar page when that URL resolves. A human-created bead shows the creator's
email without a link. `sase bead list --format full` and
`sase bead search --format full` share the same `CREATED BY` block but never resolve or
print the hosted-agent link — only `sase bead show` does. Compact `sase bead list`/
`sase bead search` rows never show the creator at all. Closed beads include their
resolution, close reason, and close timestamp; closures without a resolution show
`(unrecorded)`. Phase and task detail views always print a size: they use the stored
value when present and `small (default)` when it is absent. Task launches without a
stored size use the same `@small` fallback. Any bead's children are grouped as phases
(with status and size) and child epics (with tier and status), including child epics
owned by a phase bead. Nested beads show their complete lineage back to the root plan. A
`claimed` bead also prints `Claimed by: <assignee> (agent has not started working yet)`.
A task bead of type `flag` additionally prints a `FLAG` section with the registry key,
both `remove_by` thresholds, and derived due state, plus the typed body block for the
three authored prose fields.

Detail resolution — the target issue plus its ancestors, children, dependencies, and
blockers — comes from a single Rust-side store read instead of the three independent
reductions earlier versions performed. Combined with a narrowed CLI parser (only the
`bead` subcommand tree is built, not every `sase` subcommand) and memoized
repo-inventory lookups (the creator-URL and artifact-reference-context resolvers no
longer each re-probe `git remote` and re-merge sidecar config from scratch), this keeps
`sase bead show` fast regardless of store size or how many other beads reference the
target — including beads with `refs`, without paying the repo-inventory cost twice.

Typed artifact relationships appear after parent/children/dependency blocks and before
description and notes. They are not scheduling edges: `DEPENDS ON` and `BLOCKS` stay
backed only by `sase bead dep`. Full output shows every link that touches the bead,
including links stored on another bead, document-sidecar rows, and aggregate-only
automatic citations or audited reads. Each row is described from the displayed bead's
perspective using the relation registry: outgoing directed edges keep their authored
slug, incoming directed edges use the registered inverse, and undirected `related` edges
stay symmetric.

```text
LINKS (2)
  → implements · plan:202608/link-aware-bead-show.md
    Lands the approved CLI design.
    manual · added 2026-08-22T14:10:00Z by <agent-name>
  ↔ related · bead:<bead-id>
    Shares the same rendering contract.
    migrated · added 2026-08-20T09:00:00Z by <agent-name>

REFERENCED BY (1)
  ← cited-by · agent:<agent-name>
    Prompt citation of bead:<bead-id>.
    prompt citation · 3 uses · added 2026-08-22T15:00:00Z by <agent-name>
```

`LINKS` holds `manual`, `migrated`, and any other non-automatic origin. `REFERENCED BY`
holds `prompt_ref` and `read` origins with friendly labels (`prompt citation`,
`audited read`) and accumulated use counts. Unknown origin values print as raw labels.
Identity and provenance rows stay atomic; link reasons wrap with the same `--wrap`
budget as description prose. Missing optional sidecars mean there are no external rows.
A present but malformed or unsupported link index fails loudly and prints a hint to
rerun with `--no-links`. Stored `issue.refs` remain a separate `REFS` section.

`full` is the default detail block. `compact` prints the same single row as
`sase bead list` and never expands artifact links. `json` emits a single-bead envelope
with `issue`, `ancestors`, `children`, `depends_on`, `blocks`, `plan`, and an additive
`artifact_links` array, plus `page_url` when a hosted page URL resolves and
`created_by_url` when the creator's hosted agent page resolves; every relationship
reference includes a `resolved` flag and fixed null-valued fields for unresolved IDs.
Each `artifact_links` row includes both stored endpoints, the stored and
perspective-aware relations, direction (`outgoing`, `incoming`, or `symmetric`),
counterpart ref, reason, origin, actor, timestamp, and uses. The existing `issue.links`
outbound storage projection remains unchanged by default. `--no-links` omits both human
link sections, the top-level `artifact_links` array, and `issue.links`.

`issue.notes` is a breaking change from earlier releases: it is the list of structured
note records (`id`, `timestamp`, `author`, `text`, `edited_at`, `edited_by`), not a
single string. `issue.notes_text` is new and carries the flattened
`[<timestamp> · <author>] <text>` projection every prior consumer of `issue.notes`
actually wanted; a caller that parsed the old string field should switch to
`notes_text`. `sase bead search --format json` reports the same flattened text under its
own per-result `notes` key in `matched_fields`, unrelated to this detail-envelope shape.

The `issue.size` key is always present and is `null` for a bead with no stored size. The
`issue.external_ref` key is always present and is an empty string for a bead with no
external reference set. `issue.creation_reason` is included only when the stored filing
reason is non-empty. `sase bead list --format json` and `sase bead search --format json`
use this same issue object, so they follow the same rules for `size`, `external_ref`,
and `creation_reason`.

`--format full` renders a semantically colored, syntax-highlighted detail block
controlled by `-s/--style`. Styling is purely additive ANSI: stripping SGR escapes from
any styled output reproduces the exact `plain` bytes, so piping to a non-TTY (as every
agent does) is unaffected. `--color` decides **whether** ANSI may be emitted; `--style`
decides **how much** styling to apply once that gate is open:

`--style` has no effect on `--format json`, which is never styled. For
`--format compact`, `plain` forces no ANSI while `auto`/`rich` enable the compact row's
semantic colors when the color gate is open.

```bash
sase bead show <bead-id> --style rich --color always
```

`-p/--pager` controls paging for long terminal output:

`auto` refuses to page when `TERM` is unset or `dumb`, stdout is redirected,
`SASE_AGENT` is set, or the output fits the terminal. The `SASE_AGENT` guard prevents
launched agents with a TTY from blocking on an interactive pager. When output pages,
`sase bead show --format full` runs the [SASE Pager](../tui/pager.md) in-process with
one structured section per bead. Direct output still uses the same flattened bytes, so
shell pipelines remain plain stdout.

```bash
sase bead show <bead-id> --pager always
```

`CREATION REASON`, `DESCRIPTION`, `NOTES`, and task `+1 EVIDENCE` notes wrap at the
configured `markdown.print_width` total columns by default (`88` unless you configure
otherwise); `NOTES` appears only when the bead has notes. The budget includes the
rendered indent: with `--wrap 60`, no line in a description block exceeds 60 columns
unless it contains a single token that is longer than the budget. Wrapping is
break-only: short lines are emitted byte-for-byte, existing line breaks are not reflowed
into longer paragraphs, and `--wrap none` or `--wrap 0` disables wrapping. `--wrap auto`
uses the current terminal width, floored at 20 columns.

The wrapper never splits URLs, inline code spans, Markdown links, autolinks, or ordinary
non-whitespace tokens. Fenced code blocks, indented code, tables, tab-bearing lines,
structured relationship rows, plan paths, refs, and the title row are left unwrapped.

```bash
sase bead show <bead-id> --wrap auto
```

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-show) for this
command's options.

## Related

- [Bead CLI](bead-cli.md)
- [Bead CLI queries](bead-cli-query.md)
