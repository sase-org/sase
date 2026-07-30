# Bead Issue Tracking

Bead is a lightweight, git-native issue tracking system built into sase. It uses Rust-backed event storage,
query/reduction, and mutation logic through the required `sase_core_rs` extension, with generated JSONL compatibility
projections for older tooling (inspired by [Fossil](https://fossil-scm.org/)). Issues are organized into plan-like
containers and executable child phases. Plan beads can represent ordinary plans or executable epics through their `tier`
metadata.

![Bead issue model, storage sync, and epic wave execution](images/bead-epic-work-infographic.png)

## Table of Contents

- [Quick Start](#quick-start)
- [Data Model](#data-model)
  - [Issue Types](#issue-types)
  - [Status Lifecycle](#status-lifecycle)
  - [Bead Claim Lifecycle](#bead-claim-lifecycle)
  - [Dependencies](#dependencies)
- [Storage](#storage)
  - [Directory Structure](#directory-structure)
  - [Event Log + Compatibility Projections](#event-log-compatibility-projections)
  - [Sync Mechanism](#sync-mechanism)
- [Bead Pages](#bead-pages)
- [CLI Commands](#cli-commands)
- [Rust Backend](#rust-backend)
- [Current Checkout Source Of Truth](#current-checkout-source-of-truth)
- [ACE TUI Integration](#ace-tui-integration)

## Quick Start

```bash
PLANS_ROOT=$(sase repo path plans)
sase bead init                                          # Initialize beads in current project
sase bead create -t "New feature" --type "plan(${PLANS_ROOT}/202605/feature.md)" --tier plan
sase bead create -t "Epic" --type "plan(${PLANS_ROOT}/202605/epic.md)" --tier epic
sase bead create -t "Sub-task" --type "phase(beads-001)" --size small # Create a sized phase
sase bead list                                          # List open, claimed, and in-progress issues
sase bead list --status=open                            # List open issues
sase bead list --status=closed                          # List closed issues
sase bead search auth                                   # Search issues in every status
sase bead ready                                         # Show issues ready to work on
sase bead show beads-001                                # View issue details
sase bead update beads-001.1 --status=in_progress       # Claim an issue
sase bead note beads-001.1 "Verified with just check"   # Append an attributed note
sase bead open beads-001.1                              # Reopen an issue
sase bead close beads-001.1                             # Close an issue
sase bead dep add beads-001.2 beads-001.1               # Add dependency
sase bead dep list beads-001.2 --format full            # Inspect dependency provenance
sase bead dep tree beads-001.2                          # Follow the blocking chain
sase bead dep rm beads-001.2 beads-001.1                # Remove a wrong dependency
sase bead blocked                                       # Show blocked issues
sase bead sync                                          # Export and stage JSONL in git
sase bead pages refresh                                # Preview regenerated bead pages
sase bead pages refresh --write                        # Regenerate, commit, and push bead pages
sase bead pages url beads-001.1                        # Print the hosted page URL when available
sase bead stats                                         # Project statistics
sase bead doctor                                        # Health check
sase bead work "$PLANS_ROOT/202605/epic.md" --dry-run   # Preview bead creation and launch waves
sase bead work "$PLANS_ROOT/202605/epic.md" --yes       # Create, link, and launch an epic plan
sase bead work beads-001                                # Launch agents for an epic plan bead
```

## Data Model

### Issue Types

| Type      | Description                                          | ID Format                                 |
| --------- | ---------------------------------------------------- | ----------------------------------------- |
| **Plan**  | Plan-like container with a tier; may be a child epic | `{prefix}-{counter}` or `{parent_id}.{N}` |
| **Phase** | Sized executable task within an epic/plan bead       | `{parent_id}.{N}`                         |

Plans are groupings that can optionally link to an SDD file via the `design` field. Phases always belong to a parent
plan and use hierarchical IDs (e.g., `beads-001.1`, `beads-001.2`). An epic proposed by a phase or land agent becomes a
child plan bead beneath the bead responsible for that agent. For example, phase `beads-001.2` can own child epic
`beads-001.2.1`; an epic proposed by the land agent can become the next direct child such as `beads-001.3`.

Plan beads carry a tier. The paths below are relative to the effective plans root. Use `sase repo path plans` or
`SASE_SDD_PLANS_DIR` to locate it without depending on the storage layout.

| Tier   | Plans-root path | Behavior                                           |
| ------ | --------------- | -------------------------------------------------- |
| `plan` | `{YYYYMM}/*.md` | Normal non-epic implementation plan (`tier: tale`) |
| `epic` | `{YYYYMM}/*.md` | Executable multi-phase plan (`tier: epic`)         |

Epics use the plan syntax:

```bash
sase bead create --title "Epic" --type "plan(${SASE_SDD_PLANS_DIR}/202605/epic.md)" --tier epic
```

### Status Lifecycle

| Status        | Icon | Description                                                  |
| ------------- | ---- | ------------------------------------------------------------ |
| `open`        | `○`  | Not started                                                  |
| `claimed`     | `◎`  | Reserved by a live agent that has not started work           |
| `in_progress` | `◐`  | Being worked on, or preassigned in an epic launch checkpoint |
| `closed`      | `✓`  | Completed or abandoned                                       |

Status can transition between values via `sase bead update --status=<status>`, with one completion guard: moving a bead
to `closed` is rejected while any descendant remains open, claimed, or in progress. Close those descendants deliberately
first; `update --status=closed` never cascades. `sase bead open <id>` reopens the bead and every closed ancestor above
it, clearing their resolutions so a closed parent never sits above reopened work. `claimed` is machine-managed by the
agent runner (see [Bead Claim Lifecycle](#bead-claim-lifecycle)); do not set it by hand.

Every new close records a typed `resolution`: `done`, `canceled`, or `superseded`. Normal closes default to `done`;
`close_reason` remains optional free text for the human explanation. Historical closed beads are not backfilled, so
their resolution remains unset and human-readable detail views show `(unrecorded)`.

### Bead Claim Lifecycle

An agent launched with `%id(<name>, bead=<id>)` reserves its bead before it starts working, so a bead is never silently
owned by a process that nothing else can see:

```
open ──claim──▶ claimed ──promote──▶ in_progress ──close──▶ closed
  ▲                │
  └────release─────┘        (claim owner died before launching)
```

- **Claim.** When a bead-carrying agent enters a wait phase (dependency `%wait`, runner-slot, or duration waits), the
  runner sets the bead to `claimed` and assigns it to the agent name. Claims are written to the project's canonical bead
  store, committed locally, and then published synchronously on a best-effort basis so other hosts can see the claim:
  the runner runs the managed sync worker for that store right after the commit lands. Publication never rolls a claim
  back — a missing git repo or missing remote is a silent local-only outcome, and a real sync failure only prints a
  warning with the managed-sync log path while the local commit stands. Claiming is advisory: it never blocks or fails
  an agent launch, and a straight-through launch with no waits skips it entirely. Because it is advisory, the claim is
  acquired **best-effort**: the runner retries a bounded number of times (refreshing the canonical store once when the
  bead is not there yet, which is normal right after an epic graph is published), and whatever it fails to acquire is
  picked up by the `bead_claim_checks` reconciler. A bead can therefore turn `claimed` a few seconds after its agent
  starts waiting rather than instantly.
- **Promote.** Immediately before model execution the runner performs the existing just-in-time claim, which sets
  `status=in_progress` and assigns the runner name. Promotion is what makes the claim permanent; from that point the
  claim is never released automatically. In managed standalone SDD stores the promotion must produce a local commit and
  is published the same best-effort way before model execution; in in-tree stores the agent commits the promotion along
  with its implementation instead.
- **Release.** If the owning agent dies before it ever promoted its claim, the bead returns to `open` with an empty
  assignee. The runner shutdown path releases the claim on ordinary kills (except when a retry handoff is pending, which
  keeps the claim), and the `bead_claim_checks` chop is the backstop for SIGKILL, crashes, and reboots. It releases a
  claim only when the owning agent is dead, never promoted, and resolvable to its artifact; anything else is left
  untouched and reported by `sase doctor` instead. A committed release is published the same best-effort way as a claim,
  so a freed bead does not stay claimed on other hosts.
- **Reconcile.** The `bead_claim_checks` chop — registered under the `waits` lumberjack — runs in both directions. Next
  to the release pass above, an acquire pass claims a bead on behalf of a live agent that is waiting without a claim,
  which is what makes a lost or delayed claim self-healing within one `waits` interval. A held claim is recorded in the
  agent's `bead_claim.json` artifact file, so an agent that already holds its claim costs the chop nothing: it is
  filtered out without opening a bead store. `sase doctor` reports the residue in either direction — a claim with no
  resolvable owner, and a live pre-launch agent whose bead is still `open`.

Claim and release are compare-and-swap operations: a claim succeeds only from `open` (re-claiming your own claim is a
no-op), and a release succeeds only when the bead is still `claimed` by the releasing agent. Both decline silently
rather than overwriting someone else's state, so all three layers are safe to run concurrently.

The diagram above describes an ordinary bead-carrying agent. `sase bead work` uses a stronger batch checkpoint: before
spawning any epic worker, it sets every scheduled phase to `in_progress` with its deterministic worker as assignee and
does the same for the epic and land worker. The later runner-side wait claim and launch promotion become idempotent
no-ops. Scheduling still ignores bead status and decides from agent liveness (artifacts and PID checks), so a retry can
schedule preassigned work without creating a duplicate name.

### Dependencies

Dependencies are one-way relationships: issue A **depends on** issue B. Every edge records the source issue, the target
issue, when the edge was added, and who added it. An issue is:

- **Ready** if it is `open` and all its dependencies are `closed`.
- **Blocked** if it has at least one dependency with status `open`, `claimed`, or `in_progress`.

`sase bead dep list` prints the forward `DEPENDS ON` view, the reverse `BLOCKS` view, or both, including the edge's
provenance in `--format full`. `sase bead dep tree` walks the same graph when a one-level detail view is not enough.
Removing a dependency appends a `dependency_removed` event rather than editing or erasing the original add event, so
history keeps both the mistake and its correction.

## Storage

### Directory Structure

When the workspace provider declares in-tree storage, as the built-in `bare_git` provider does:

```
sdd/beads/
  config.json           # Configuration (issue prefix, counter, owner)
  events/
    manifest.json       # Event-store schema and migration metadata
    streams/
      <root-id>.jsonl   # Canonical append-only event stream
  issues.jsonl          # Generated compatibility projection
  beads.db              # SQLite compatibility cache (gitignored)
```

Providerless local storage and legacy single-sidecar storage use `.sase/sdd/beads/` with the same structure. Local
storage uses the primary workspace; every sidecar layout uses the active workspace clone and records provider/remote
metadata in the primary workspace's `.sase/sdd-store.json`.

Split sidecar storage puts bead state in its own auto-cloned `<owner>/<repo>--beads` repository, checked out at
`<workspace>/sase/repos/beads`. That repository keeps the store **at its root** rather than under a `beads/`
subdirectory, so `config.json`, `metadata.json`, `issues.jsonl`, and `events/` sit beside the generated `README.md`,
`assets/`, `.gitignore`, and generated `pages/`. A split project that has not been migrated yet still keeps bead state
at `beads/` in the root of its auto-cloned `--plans` repository; the `.sase/sdd-store.json` record decides which, and
only a record that names a `beads` sidecar (schema version 3) resolves to the dedicated repository. See
[SDD Storage](sdd_storage.md) for the record format and the adoption transaction that performs the move.

Isolating bead state this way gives it its own git history, its own cooperative write lock, and its own
repository-health preflight, so hot bead writes no longer serialize behind plan writes and a wedged bead rebase cannot
block plan commits or epic approval.

Normal bead commands read and write one store for the active checkout. In in-tree mode, canonical bead state lives in
the current checkout's `sdd/beads/events/**` event store plus `sdd/beads/config.json`. Providerless local commands route
to the primary workspace's `.sase/sdd/beads/` store. Sidecar-policy commands first materialize the provider store, then
route to the active workspace clone so an agent in workspace `#N` writes its matching `.sase/sdd/` checkout, its
`sase/repos/beads/` clone, or its `sase/repos/plans/beads/` directory. If the event store is absent, reads fall back to
legacy `issues.jsonl`. Numbered sibling workspaces and legacy stores are not merged into normal `sase bead` reads.

`sase bead` clones the beads sidecar on demand. When the store record names one and `sase/repos/beads` is missing or its
origin does not match the recorded remote, the command materializes the clone before serving the request—reads included,
since a read cannot be served from a clone that does not exist. If the clone cannot be made usable, the command fails
with an error naming the repository and its remote. Projects whose record has no beads sidecar clone nothing extra.

### Event Log + Compatibility Projections

Rust owns the bead storage/query/mutation path. The append-only event streams are the canonical git-portable state.
`issues.jsonl` remains a generated compatibility projection, and `beads.db` remains a local compatibility cache. They
are kept in sync:

- **Writes** append canonical Rust events first, then regenerate `issues.jsonl` and refresh `beads.db`.
- **Reads** prefer `events/manifest.json` plus `events/streams/*.jsonl`, falling back to legacy `issues.jsonl` only when
  no event store is present.
- **History** replays those same streams in projection order; `sase bead history <id>` makes every recorded field
  revision readable without changing canonical state.
- **Fresh clones** read directly from the tracked event streams and can rebuild the compatibility mirrors on demand.
- **Dependency removals** are recorded as `dependency_removed` events. During merged replay, a remove sorts after an add
  with the same timestamp, so add-then-remove deterministically leaves the edge absent.

The `.gitignore` excludes `beads.db*` files. The event store, `issues.jsonl`, and `config.json` are tracked in git.

### Sync Mechanism

`sase bead sync` regenerates the compatibility projection from the canonical event store and stages the bead state in
the owning git repo, including `events/**`, `issues.jsonl`, and `config.json`. The projection contains one JSON object
per line, sorted by issue ID for clean diffs.

When both stores exist, the event store wins. Manual edits to `issues.jsonl` do not change command output unless the
event store is absent.

## Bead Pages

Projects with a hosted beads sidecar can publish one Markdown page per bead. Pages live in the `--beads` repository
under `pages/<root>/`, where `<root>` is the bead ID segment before the first dot. The root bead renders as
`pages/<root>/README.md`; descendants render as `pages/<root>/<bead-id>.md`.

An artifact reference such as `@bead:sase-9z` addresses that generated page directly. The payload is the exact bead ID,
with no prefix-less shorthand and no `#L`, `#page=`, or `#t=` fragment support. Addressing is lexical and offline: SASE
derives the page path from the ID without reading `issues.jsonl`, then reports the page missing if it has not yet been
published. Run `sase bead pages refresh --write` to publish or repair bead pages before sharing durable `@bead:` refs.

Pages are generated projections, not hand-maintained state. They are rebuilt from the canonical bead event store plus
the primary repository's commit history, and they link to the bead's plan, parent and child beads, dependencies,
associated agents, and commits. Current commits use a structured `SASE_BEAD=<id>` footer tag instead of a subject-line
parenthetical; historical commits with trailing `(<bead-id>)` subjects are still recognized when the ID exists in the
store.

```bash
sase bead pages refresh                 # dry run; writes nothing
sase bead pages refresh --write         # write changed pages and commit one beads-sidecar batch
sase bead pages refresh --bead beads-1  # refresh one lineage
sase bead pages refresh --json          # machine-readable report
sase bead pages url beads-1.2           # print the hosted URL for one bead
```

Per-commit publication refreshes the committed bead's lineage after a `create_commit` or `create_pull_request` workflow
that carries `SASE_BEAD=`. The shared `pages/README.md` roster is owned by `sase bead pages refresh`, so regular commits
avoid rewriting a file every active agent could touch. `sase bead show <id>` prints a `PAGE` section when the local
sidecar remote and branch resolve to a hosted URL; `--format json` includes `page_url` in the same case. An epic agent
clan's summary panel also shows its epic bead's hosted page URL when one resolves; run `sase plan links refresh` to
repair a plan whose `BEAD` bullet predates hosted links. Epic clan summaries place the label and complete URL on one
logical line, with no SASE-authored break or whitespace inside the address. A panel too narrow for the composed row
moves the whole address to the next row flush-left, so terminal URL matchers and copy/paste always see the complete
target.

## CLI Commands

With no subcommand, `sase bead` defaults to `sase bead list` with default options. Use the explicit `sase bead list`
form when passing list filters.

### `sase bead blocked`

Show all issues that have at least one active (non-closed) blocker.

### `sase bead close <id> [<id2> ...]`

Close one or more issues. Every requested bead is checked before the first write, so a batch either closes completely or
leaves the store untouched. A bead with any non-closed descendant is rejected and names the unfinished work; phase
agents should continue to close only their assigned phase bead, not the parent epic.

For an epic plan bead, `--phases` (`-p`) closes phase beads by their numeric bead-ID suffix: for example,
`sase bead close sase-at -p 1-3,5` closes `sase-at.1`, `sase-at.2`, `sase-at.3`, and `sase-at.5`. The option accepts
comma-separated numbers and inclusive ranges, may be repeated, and requires exactly one epic ID. It never closes the
epic itself. A plan-tier, untiered, or phase target is rejected without writing to the store.

`--force` is the explicit exception for canceling or superseding an unfinished tree. It requires a non-empty reason and
an explicit `canceled` or `superseded` resolution; `--force --resolution done` is rejected. A forced close recursively
closes the unfinished descendants with the same non-done resolution, gives each one a close reason naming the forcing
parent, and records the swept descendant IDs in that parent's close event.

`--note` appends one attributed note to every explicitly listed bead before the close events, in the same mutation, so
completion evidence and the close land in one commit and one push instead of two. The note text and attribution match
`sase bead note`; forced closes apply it only to the listed beads, never to the swept descendants. Keep `sase bead note`
for mid-work progress notes.

Closing a delegated child plan/epic also closes its parent phase automatically once every child of that phase is closed.
This upward cascade continues only through phase parents and never auto-closes a parent plan/epic; the parent land agent
retains that responsibility. Removing a child epic does not trigger the cascade, so its phase stays open and can be
scheduled again on retry.

| Flag               | Description                                                                         |
| ------------------ | ----------------------------------------------------------------------------------- |
| `-f, --force`      | Sweep unfinished descendants; requires a reason and `canceled` or `superseded`      |
| `-n, --note`       | Append this attributed note to each listed issue before closing it                  |
| `-p, --phases`     | Close numbered phases of one epic; accepts comma-separated numbers and ranges       |
| `-r, --reason`     | Optional close reason text; required with `--force`                                 |
| `-R, --resolution` | `canceled`, `done`, or `superseded`; defaults to `done`, which force does not allow |

### `sase bead create`

Create a new issue.

| Flag                | Required | Description                                                                                                                                                                                                                          |
| ------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `-t, --title`       | yes      | Issue title                                                                                                                                                                                                                          |
| `-T, --type`        | yes      | Bead type: `plan(<file>)`, `plan(<file>,<parent>)`, or `phase(<parent_id>)`                                                                                                                                                          |
| `-d, --description` | no       | Issue description                                                                                                                                                                                                                    |
| `-a, --assignee`    | no       | Assignee name                                                                                                                                                                                                                        |
| `--tier`            | no       | Plan-bead tier: `plan` or `epic`                                                                                                                                                                                                     |
| `-c, --changespec`  | no       | Attach a ChangeSpec name to a plan bead                                                                                                                                                                                              |
| `-b, --bug-id`      | no       | Bug ID for the attached ChangeSpec; requires `--changespec`                                                                                                                                                                          |
| `-m, --model`       | no       | Model used when this bead is launched. Provider-qualified (e.g. `codex/gpt-5.6-sol`) or a configured local alias (e.g. `#pro`). On epic plan beads this becomes the land-agent model; on phase beads it is the per-phase work model. |
| `-z, --size`        | no       | Phase size: `xsmall`, `small`, `medium`, `large`, or `xlarge`. Valid only on phase beads; an omitted legacy/manual value behaves as `small`.                                                                                         |

ChangeSpec metadata is valid only on plan beads. It is used by the epic-approval and `sase bead work` flows to keep plan
beads linked to the ChangeSpec they are intended to produce.

### `sase bead dep`

Inspect and manage dependency edges. With no child subcommand, `sase bead dep` delegates to `sase bead dep list` and
prints the same central delegation notice used by other default-list verbs.

```bash
sase bead dep
sase bead dep add <issue> <depends_on>
sase bead dep list [<id>]
sase bead dep rm <issue> <depends_on> [<depends_on2> ...]
sase bead dep tree [<id>]
```

`dep add` makes `<issue>` depend on `<depends_on>`. The issue becomes blocked if the dependency is not yet closed.

`dep list` prints dependency edges with their blocking state and recorded provenance. A scoped read, such as
`sase bead dep list beads-001.2`, includes every bead status by default because closed dependencies are usually what you
need to see when explaining readiness. A store-wide read defaults to `open`, `claimed`, and `in_progress`, matching
`sase bead list`.

`dep tree` walks the dependency graph as a deterministic tree. `--direction out` follows what the root waits on,
`--direction in` follows what is waiting on the root, and `--direction both` renders both trees. Store-wide trees use
the same active-status default as store-wide `dep list`; scoped trees include every status by default.

Tree output marks graph states explicitly:

- `⇡ (shown above)` means a shared subtree was already expanded, as in a fan-in diamond.
- `↻ (cycle)` means a dependency cycle was detected and that branch stopped.
- `(+N more, use --levels 0)` means `--levels` truncated descendants.
- `? <id> (not found)` means an edge points at an unresolved bead ID.

`dep rm` removes one or more existing dependency edges from `<issue>` in one all-or-nothing mutation. The command
records `dependency_removed` events and then reports whether the source bead is ready or still blocked.

| Subcommand | Flag              | Values                                     | Description                                      |
| ---------- | ----------------- | ------------------------------------------ | ------------------------------------------------ |
| `list`     | `-c, --color`     | `auto`, `always`, `never`                  | Color mode for text output                       |
| `list`     | `-d, --direction` | `both`, `in`, `out`                        | Edges to show; defaults to `both`                |
| `list`     | `-f, --format`    | `compact`, `full`, `json`                  | Output format; defaults to `compact`             |
| `list`     | `-n, --limit`     | non-negative integer                       | Maximum root beads to print; `0` means unlimited |
| `list`     | `-s, --status`    | `open`, `claimed`, `in_progress`, `closed` | Filter by endpoint/status root (repeatable)      |
| `tree`     | `-c, --color`     | `auto`, `always`, `never`                  | Color mode for text output                       |
| `tree`     | `-d, --direction` | `both`, `in`, `out`                        | Direction to walk; defaults to `out`             |
| `tree`     | `-f, --format`    | `compact`, `full`, `json`                  | Output format; defaults to `compact`             |
| `tree`     | `-L, --levels`    | non-negative integer                       | Maximum levels to descend; `0` means unlimited   |
| `tree`     | `-s, --status`    | `open`, `claimed`, `in_progress`, `closed` | Filter by bead status (repeatable)               |

### `sase bead doctor`

Run health checks on the beads database. Checks for:

- Missing `config.json`, event store, legacy projection, or compatibility cache
- Projection drift between canonical events and `issues.jsonl`
- Invalid events or unreduced orphan phase records
- Uncommitted bead-state changes
- Orphan children (phase or nested-plan beads whose parent is missing)
- `claimed` beads whose assignee resolves to no agent artifact (reported only; run `sase bead open <id>` to clear them)
- `open` beads owned by a live agent that has not started work yet (reported only; it means the `bead_claim_checks` chop
  is not running or is failing, since it should have claimed them)

If bead commands fail before opening a store, run `sase core health` first. It verifies that the required `sase_core_rs`
extension is importable and exposes the representative bead CLI binding used by the fast path.

### `sase bead history [<id>]`

Replay one bead's canonical event stream as an ordered, field-level timeline. Compact output prints the timestamp,
actor, operation, and changed field names for each event. Full output prints every prior and new value, including
earlier note revisions that later updates replaced. JSON emits one envelope with `issue_id`, `schema_version`, and
`entries`.

Use `--lost-notes` to report notes snapshots whose nonblank text no longer appears in the current notes. With no
positional ID it scans the whole store; with an ID it checks only that bead. Findings are sorted by bead ID. Add
`--restore` to preview provenance-tagged appends, prompt once, and restore every finding through the same atomic append
mutation used by `sase bead note`. Restoration is idempotent: restored text is retained by later append snapshots, so a
second scan reports nothing. Non-interactive restoration declines safely, and `--restore` without `--lost-notes` is a
usage error.

| Flag               | Values                    | Description                                                    |
| ------------------ | ------------------------- | -------------------------------------------------------------- |
| `-F, --field`      | field name                | Restrict to events changing the field; repeatable              |
| `-f, --format`     | `compact`, `full`, `json` | Output format; defaults to `compact`                           |
| `-n, --limit`      | non-negative integer      | Newest entries to print; omitted or `0` is unlimited           |
| `-l, --lost-notes` | boolean                   | Report beads whose current notes dropped an earlier revision   |
| `-R, --restore`    | boolean                   | With `--lost-notes`, re-append findings after one confirmation |

### `sase bead init`

Initialize the bead store for the current project. In effective in-tree SDD mode this is `sdd/beads/`; local and legacy
separate-repo modes use `.sase/sdd/beads/`. Split sidecar mode uses the root of the `--beads` repository once the store
record names that sidecar, and `beads/` in the `--plans` repository until then.

### `sase bead list`

List issues with optional filtering. Without `--status`, the command lists `open`, `claimed`, and `in_progress` issues;
pass `--status=closed` when you need closed history. When the default active query is empty and no explicit `--status`
was given, the command falls back to listing closed beads. `--status`, `--type`, and `--tier` are repeatable.

| Flag           | Values                                     | Description                                                                           |
| -------------- | ------------------------------------------ | ------------------------------------------------------------------------------------- |
| `-f, --format` | `compact`, `json`, `full`                  | Output format; defaults to `compact`                                                  |
| `-n, --limit`  | integer                                    | Maximum beads to print; closed listings default to the newest 20, `0` means unlimited |
| `-s, --status` | `open`, `claimed`, `in_progress`, `closed` | Filter by status (repeatable)                                                         |
| `--tier`       | `plan`, `epic`                             | Filter by plan-bead tier                                                              |
| `-t, --type`   | `plan`, `phase`                            | Filter by type (repeatable)                                                           |

Active (open/claimed/in-progress) listings are unlimited by default. Whenever the final status scope includes `closed`
and `--limit` is omitted, only the newest 20 beads print; pass `--limit 0` for the full closed history.

### `sase bead note <id> <text>`

Append one timestamped, attributed entry to an issue's notes. The entry is recorded as
`[<timestamp> · <author>] <text>`, separated from existing notes by a blank line. The mutation runs atomically in the
Rust bead store, so concurrent note writers append to the current value rather than replacing each other.

| Flag           | Description                                                               |
| -------------- | ------------------------------------------------------------------------- |
| `-a, --author` | Author recorded on the entry; defaults to current agent, then store owner |

### `sase bead onboard`

Display a quick-start guide with common command examples.

### `sase bead open <id>`

Reopen an issue with an `issue_opened` event. Every closed ancestor above it is reopened in the same mutation, and the
command prints the ancestor IDs it changed. Resolutions are cleared on the reopened bead and ancestors; historical close
reasons and timestamps remain available.

### `sase bead ready`

Show issues that are ready to work on: `open` status with all dependencies `closed`. A `claimed` bead is already spoken
for by a live agent, so it does not appear in `ready`.

### `sase bead rm <id> [<id2> ...]`

Remove one or more issues and recursively cascade-delete the union of all their descendants, including phases nested
beneath child epics. Every requested ID is validated before anything is removed, so a missing ID leaves the store
unchanged. Overlapping or repeated selections remove and print each issue only once. This is irreversible.

### `sase bead search <query>`

Find beads whose indexed text fields contain a case-insensitive literal substring. This is substring search, not regex
or glob matching. Current indexed fields include ID, title, description, notes, design/plan path, owner, assignee,
model, phase size, ChangeSpec name/bug ID, status, type, and tier; timestamps are not searched. Unlike `sase bead list`,
search includes `open`, `claimed`, `in_progress`, and `closed` beads by default, so it is the quickest way to recover
older context.

Compact output prints each matching bead with a short snippet. For multi-line fields such as descriptions or notes, the
snippet uses the line that matched the query when possible instead of always showing the first line. JSON output exposes
the exact `matched_fields` list for each result.

```bash
sase bead search auth
sase bead search auth --format json
sase bead search auth --format full --limit 3
sase bead search auth --status open --type phase
sase bead search auth --type plan --tier epic
```

| Flag           | Values                                     | Description                                     |
| -------------- | ------------------------------------------ | ----------------------------------------------- |
| `-c, --color`  | `auto`, `always`, `never`                  | Color mode for compact output                   |
| `-f, --format` | `compact`, `json`, `full`                  | Output format; defaults to `compact`            |
| `-n, --limit`  | non-negative integer                       | Maximum results; omitted or `0` means unlimited |
| `-s, --status` | `open`, `claimed`, `in_progress`, `closed` | Filter by status (repeatable)                   |
| `--tier`       | `plan`, `epic`                             | Filter by plan-bead tier (repeatable)           |
| `-t, --type`   | `plan`, `phase`                            | Filter by type (repeatable)                     |

### `sase bead show <id>`

Display complete details for an issue including status, type, tier, parent lineage, dependencies, blockers, description,
notes, ChangeSpec metadata, model, linked plan path, and the hosted page URL when one resolves locally. Closed beads
include their resolution, close reason, and close timestamp; legacy closures without a resolution show `(unrecorded)`.
Phase beads show their effective size (`small` for legacy beads without a stored size). Any bead's children are grouped
as phases (with status and size) and child epics (with tier and status), including child epics owned by a phase bead.
Nested beads show their complete lineage back to the root plan. A `claimed` bead also prints
`Claimed by: <assignee> (agent has not started working yet)`.

`full` is the default detail block. `compact` prints the same single row as `sase bead list`. `json` emits a single-bead
envelope with `issue`, `ancestors`, `children`, `depends_on`, `blocks`, and `plan`, plus `page_url` when a hosted page
URL resolves; every relationship reference includes a `resolved` flag and fixed null-valued fields for unresolved IDs.

| Flag           | Values                    | Description                       |
| -------------- | ------------------------- | --------------------------------- |
| `-f, --format` | `compact`, `json`, `full` | Output format; defaults to `full` |

### `sase bead stats`

Show project statistics: total, open, claimed, in-progress, and closed counts, plus plan and phase counts.

### `sase bead sync`

Regenerate the compatibility projection from the canonical event store and stage bead state in git. It does not create a
commit; the staged event/projection files are included in the next normal project or SDD commit.

| Flag           | Description                                   |
| -------------- | --------------------------------------------- |
| `-s, --status` | Check whether bead state has unstaged changes |

### `sase bead update <id>`

Update one or more fields on an issue.

| Flag                | Description                                                                   |
| ------------------- | ----------------------------------------------------------------------------- |
| `-s, --status`      | Change status                                                                 |
| `-t, --title`       | Change title                                                                  |
| `-d, --description` | Change description                                                            |
| `-n, --notes`       | Replace notes                                                                 |
| `-D, --design`      | Change plan path                                                              |
| `-a, --assignee`    | Change assignee                                                               |
| `--tier`            | Change plan tier                                                              |
| `-m, --model`       | Change the launch model. Pass an empty string to clear.                       |
| `-z, --size`        | Change a phase bead's `xsmall`, `small`, `medium`, `large`, or `xlarge` size. |

Use `sase bead update --notes` for an explicit field replacement. Use `sase bead note` when recording progress that
should accumulate with earlier notes.

### `sase bead work <target>`

Create or resume an epic from a validated Markdown plan, or launch an existing epic-tier plan bead. A target is treated
as a plan file when it ends in `.md`, contains a path separator, or names an existing file; other targets are bead IDs.
Both modes use the same launcher to run one agent per non-closed, non-delegated phase plus a final land agent.

Plan-file mode is the canonical epic-approval entry point. It:

1. Validates the file against the epic plan schema and reports the complete diagnostics on failure.
2. Resolves the project's SDD and bead stores, initializing the bead store when needed.
3. Archives the plan under the resolved `{YYYYMM}/` plans directory and commits it.
4. Resumes the linked epic when the archived plan already has a valid `bead_id`.
5. Otherwise creates the epic plan bead from the plan's `title`, `goal`, top-level `model`, optional `parent_bead`, and
   optional ChangeSpec metadata; creates phase beads with their authored sizes in `phases[]` order; wires every
   `depends_on` edge; and commits the new `bead_id` link.
6. Invokes the existing bead-ID launch path.

A missing phase description becomes a deterministic pointer to the plan and phase ID. A linked `bead_id` that no longer
exists fails with instructions to remove the stale link or restore the bead store. Failures before the launch checkpoint
is committed remove the newly-created epic and children and restore the plan link. A publication failure after the
checkpoint preserves the linked, preassigned epic as the safe retry point even though no runner spawned. If dispatch
fails with no runner spawned, plan-file mode removes a newly created graph and restores the plan link; for an epic that
already existed, it instead restores that epic's prior readiness, assignments, and statuses. Once a runner has spawned,
the linked epic and checkpoint are preserved for recovery and partial runners are terminated. Every plan-file failure
after archiving prints the exact `sase bead work ... --yes` command to resume.

When an epic-tier plan is proposed from bead work, `sase plan propose` automatically stamps `parent_bead` from the phase
agent's `SASE_PHASE_BEAD_ID`, or from the land agent's `SASE_EPIC_BEAD_ID`. Plan-file mode resolves that bead and
creates the new epic beneath it, yielding recursive IDs such as `beads-001.2.1`; an unresolved parent fails with a
remedy instead of silently creating a top-level epic. `--parent <bead-id>` overrides the authored association, while
`--parent top-level` explicitly creates an unparented epic. The override applies only to plan-file targets.

`--dry-run` plan-file mode validates and resolves the stores, previews the archive destination, parented epic ID,
authored beads, routed models, and dependency waves, and does not write files, create beads, reserve names, or launch
agents. `--json` prints one stable object for scripting; successful human output always ends with a grep-friendly
`Epic: <id>` line used by approval hosts.

Once an epic bead exists, the shared launch path:

1. Validates that `<epic_id>` resolves to an issue of type `plan` with `tier=epic`. If the plan is already marked
   `is_ready_to_work`, the command treats the run as a retry and schedules any remaining non-closed phases. A phase that
   owns a non-closed child plan/epic is delegated work already in flight and is skipped until that child closes or is
   removed; retries therefore do not launch a duplicate phase agent.
2. On a confirmed launch, force-reuses the deterministic bead-work names — `<epic_id>.<N>` (for each open phase),
   `<epic_id>.land` (for the land agent), and the legacy `<epic_id>` land-agent name — by wiping any prior owner of
   those names, whether that owner is a completed, dismissed, or planned reservation or a still-live agent (live owners
   are terminated). This also covers owners that hold the name only as a `workflow_name`. If the forced-reuse cleanup
   cannot complete (a wipe fails or a name is still reserved afterward), the command aborts before mutating any bead
   state. `--dry-run` performs no cleanup; it only warns which live agents a real launch would force-reuse.
3. Flips the epic plan bead's `is_ready_to_work` flag to `True` when it was not already ready.
4. Builds a Kahn-wave schedule from the epic's schedulable open phase children, respecting dependencies and excluding
   delegated phases with an open child plan/epic. When every remaining phase is delegated, only the land agent is
   launched and remains parked behind the phase beads.
5. Associates each rendered worker with exactly one bead in its `%id`: the first phase uses its full agent name plus
   `bead=<phase-id>` beside the separate clan declaration, later phases combine their suffix, `clan=<epic-id>`, and
   `bead=<phase-id>`, and the land agent combines `land`, the clan, and `bead=<epic-id>`.
6. Renders a single `---`-separated multi-prompt. Each per-phase agent is named `<epic_id>.<N>` and references the
   [`work_phase_bead`](xprompt.md#available-tags) xprompt; a final land agent named `<epic_id>.land` references the
   [`land_epic`](xprompt.md#available-tags) xprompt. Every segment joins clan `<epic_id>` and assigns that whole clan to
   tribe `@epic` with the single `%clan(<epic_id>, tribe=epic)` directive. Each phase dependency becomes both a `%w`
   wait on the blocker phase-agent name and a `%w(bead=<blocker-phase-id>)` closure wait. The land agent likewise waits
   on every launched phase agent and on every authored phase bead, including already-closed or currently delegated
   phases. Requiring both conditions prevents a phase that delegated to a child epic from releasing dependents merely
   because its original agent finished; the child epic must land and close the parent phase first. A failed or killed
   phase keeps dependents and the land agent parked until its agent name is retried successfully and its bead closes.
   `xsmall`, `small`, and `medium` phases implement directly with `%model:@xsmall_phase_worker`,
   `%model:@small_phase_worker`, and `%model:@medium_phase_worker`, respectively. Only `large` and `xlarge` phases
   append `#plan` after their work reference and use `%model:@large_phase_worker` and `%model:@xlarge_phase_worker`. A
   stored phase `model` always wins over the size-derived alias without changing whether the phase receives `#plan`, and
   a missing legacy size behaves as `small`. The land agent emits `%model:<value>` when the epic plan bead has a stored
   `model`. Without one, it emits `%model:@epic_lander` below `bead.big_epic_phase_threshold` and
   `%model:@big_epic_lander` at or above the threshold (default `5`), using the total authored phase count even when
   resumed work has already-closed phases. Normal landers fall through `@epic_lander` to `@default`, while landers
   selected by the threshold fall through `@big_epic_lander` to provider-aware `@smartest`. `xsmall` phases fall through
   `@xsmall_phase_worker` to the load-balanced `@cheaper` pool, `small` phases through `@small_phase_worker` to the
   `@cheap` pool, `medium` phases through `@medium_phase_worker` to `@default@high`, `large` phases through
   `@large_phase_worker` to `@smart`, and `xlarge` phases through `@xlarge_phase_worker` to `@smartest`. The independent
   `@cheapest` provider fallback is available for explicit use but has no automatic consumer. Builtin aliases can be
   configured under `llm_provider.model_aliases.builtin`. Each phase segment and the final land-epic segment carries
   bare `%auto`, so submitted implementation and landing plans are auto-approved. An agent may author a tale or an epic
   as needed; the plan's authored `tier` selects the corresponding automatic follow-up path.
7. Before spawning any runner, batch-preassigns every scheduled phase bead to its rendered worker and the epic bead to
   `<epic_id>.land`, setting all of them to `in_progress`. It commits readiness, assignments, and the complete graph as
   one `chore(beads): checkpoint approved epic graph <id>` checkpoint. A retry whose graph is already committed may have
   no new checkpoint commit. Before dispatch, SASE applies the target-specific synchronization rules below.
8. Dispatches the rendered multi-prompt. Runner-side waiting claims and launch promotions see their preassignment and
   become no-ops. Each segment uses a force-reuse `%id(!<agent_name>, bead=<bead-id>)` form (with `clan=` on join
   segments), so re-running `sase bead work` after a killed or failed run wipes stale name owners before relaunch. The
   schedule is status-blind and uses agent liveness, which makes the checkpoint safe to retry.

When a phase agent auto-approves an epic-tier implementation plan, that child epic is created beneath the phase and the
phase remains open while delegated work runs. Landing the child epic triggers the upward close cascade described above,
which closes the phase and lets its bead-gated dependents proceed. Until then, parent-epic retries skip that delegated
phase. The land agent now genuinely requires every phase bead to close; if a phase crashes before closure, retry or
close that phase explicitly rather than expecting landing to sweep it up.

| Flag                  | Description                                                                                   |
| --------------------- | --------------------------------------------------------------------------------------------- |
| `-a, --artifacts-dir` | Planner artifacts directory to back-fill after an approved epic launch                        |
| `-c, --cl-name`       | ChangeSpec name for the approved epic completion notification                                 |
| `-n, --dry-run`       | Validate and preview plan archiving, bead creation, model routing, and waves without mutation |
| `-j, --json`          | Print one machine-readable result object; also implies `--yes-to-all`                         |
| `-P, --no-push`       | Skip checkpoint synchronization; a remote-backed detached store stops before spawning         |
| `-p, --parent`        | Override a plan file's `parent_bead`; pass `top-level` to force an unparented epic            |
| `-y, --yes`           | Skip only the launch confirmation prompt                                                      |
| `-Y, --yes-to-all`    | Skip both the destructive-cleanup and launch confirmation prompts                             |

The work xprompts are resolved by `XPromptTag` (tag-based lookup), so a project-local or user-defined xprompt with the
matching tag overrides the built-in. For epic-tier work, every phase and land segment carries bare `%auto`, so spawned
agents can auto-approve submitted tale or epic plans and follow the path selected by the authored `tier`, without a
human-in-the-loop checkpoint between dependency waves.

When the epic plan bead is attached to ChangeSpec metadata (`--changespec` / `--bug-id`), `sase bead work` preserves the
current project's VCS context in the generated prompt. The first phase segment targets the project reference and adds a
`#pr` reference for the ChangeSpec, while later phase and land segments target the ChangeSpec ref directly. For
non-ChangeSpec epics launched from a known SASE workspace, each segment is still prefixed with the detected VCS workflow
and project name (for example `#git:sase` or `#gh:sase-org/sase`). If the current directory is not associated with a
SASE project, the prompts are left unprefixed and run in the caller's normal launch context.

If checkpoint creation fails before it commits, the command restores every phase/epic status and assignee it changed,
and restores `is_ready_to_work` only when this attempt set it. A detached-store publication failure after the local
checkpoint commit stops before spawning and preserves that checkpoint as the safe retry point; rerun without `--no-push`
after fixing the remote. For an existing epic, an agent-dispatch failure before any runner spawns restores the prior
assignments and commits the recovery. Plan-file mode additionally removes a graph created by that invocation and
restores its plan link. A partial-spawn failure SIGTERMs the children it did start and preserves the preassigned
checkpoint for recovery. An epic that was already ready remains ready.

Successful launches do not add a post-launch bead commit: the pre-spawn graph checkpoint is the complete launch-owned
state. The accepted `bead.push_after_commit` configuration field is not consulted by this current path. The exact
synchronization sequence depends on the target:

- For a bead-ID target, SASE runs the managed sync worker synchronously after the checkpoint unless `--no-push` was
  passed. A store with no Git remote makes that sync a local no-op. Any reported sync or push error stops the launch
  before dispatch, including for an in-tree Git store. A remote-backed detached store has the additional requirement
  that the checkpoint was actually pushed.
- For a plan-file target, SASE synchronously publishes a remote-backed detached bead graph before dispatch. After a
  successful dispatch it makes a best-effort synchronous push of the plans store, which publishes the archived plan and
  its `bead_id` link. A failure in this later plans-store push is a warning, not a launch failure.
- `--no-push` skips these synchronization steps. It is usable only when workers can see the local checkpoint directly; a
  remote-backed detached bead store exits nonzero before any agent is spawned.

## Rust Backend

The bead data model, event reducer, JSONL/config codecs, compatibility-cache refresh, mutation transactions, ID
allocation, deterministic work-plan DAG, and common CLI output planning are implemented in `sase-core` and exposed
through `sase_core_rs`. Python keeps the host logic that belongs in the application layer: locating the active bead
store, relativizing plan paths, resolving VCS context and xprompts for `sase bead work`, prompting the user, launching
agents, rolling back failed launches, and incrementing telemetry counters.

Common `sase bead` commands dispatch through an early CLI fast path before the full top-level parser is built. Help text
and host-coupled commands still fall through to the normal Python parser/handlers where needed.

Use these checks when changing bead internals:

```bash
sase core health -j
pytest tests/test_bead tests/test_core_facade/test_bead_read.py tests/test_core_facade/test_bead_mutation.py
just rust-check
just bead-perf-smoke
```

## Current Checkout Source Of Truth

In in-tree mode, every `sase bead` read and mutation command uses the current checkout's `sdd/beads/events/**` event
store and `sdd/beads/config.json`, with `issues.jsonl` used only as a fallback when events are absent. Running the
command in `myproject/` reads that checkout's bead state; running it in `myproject_2/` reads `myproject_2/sdd/beads/`.
The CLI does not merge sibling workspace stores, and duplicate IDs in another checkout do not override the active
checkout's records.

ID allocation also uses only the active store's `config.json` and canonical event state. If a sibling checkout has not
pulled or merged the latest bead state, it may allocate IDs based on its local state; sync bead changes through the
normal VCS workflow when several agents are coordinating on the same project.

Cross-project helper surfaces, such as mobile/editor bead pickers, may inspect one canonical store per known project,
but they still do not merge numbered sibling workspaces or legacy bead stores for the same project.

## ACE TUI Integration

### Plan File Linking

When creating a plan bead with `--type plan(PATH)`, the file path is stored in the `design` field. The ACE TUI can
navigate from a bead to its linked SDD file.

For SDD-generated epics, `PATH` should be the shared plan reference emitted by the plan approval flow: `sdd/plans/...`
in in-tree mode, `.sase/sdd/plans/...` in local and legacy separate-repo modes, or `<YYYYMM>/...` in the split `--plans`
repository. SASE resolves those references against the effective SDD root when launching bead work. For manual commands
and prompts, `SASE_SDD_PLANS_DIR` or `sase repo path plans` is less ambiguous than guessing which relative prefix
applies.

### Plan Approval Flow

The plan approval popup in ACE includes normal approval and **E** (Epic) actions. Normal approval saves to the resolved
SDD `plans/` directory with `tier: tale`. Every epic approval surface behaves the same way — ACE,
`sase plan approve --kind epic`, Telegram, and bare gate responses all submit one deduplicated global `detached` task
that runs `sase bead work <plan-file> --yes-to-all` from the project's primary workspace, then record that the host owns
the launch in the planner response. Because the task is detached and global, no interactive session owns it: it survives
the approving process, appears in every default `sase task list` and Tasks-tab scope, is streamable with
`sase task show <id> --follow`, supports kill, and still emits the epic-completion notification. The approval passes
`--artifacts-dir` (and `--cl-name` when a ChangeSpec is involved), so a successful launch back-fills the epic ID and
committed plan path into planner metadata.

There is no planner-side subprocess fallback and no foreground path. If the host cannot resolve the primary workspace,
finds the approved-epic plans store unusable, or fails to submit the task, approval fails loudly and reports the
`sase bead work <plan> --yes-to-all` resume command rather than launching invisibly. After a successful handoff, the
planner writes its prompt snapshot, finishes as `EPIC APPROVED`, and does not race the command for ownership of the epic
plan file.
