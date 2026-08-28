# Artifact Links

Artifact links are typed relationships between SASE artifacts. They answer "why are
these durable records connected?" without overloading prompt citations, bead
dependencies, or free-text notes.

An **artifact** is any durable record addressable by an artifact reference: a plan,
research report, bead, completed agent, Patch, stitch, or indexed file. Each artifact
has a canonical `<kind>:<argument>` identity. An **artifact markdown file** is the
Markdown document or generated page where SASE renders that artifact's typed links.

## Relation Registry

The registry is closed. Use one of these slugs exactly:

| Relation       | Inverse          | Directed | Written by                                                |
| -------------- | ---------------- | -------- | --------------------------------------------------------- |
| `cites`        | `cited-by`       | yes      | prompt references and structured header derivation        |
| `read`         | `read-by`        | yes      | `sase artifact read`                                      |
| `related`      | `related`        | no       | CLI / plan inlet; `RELATED:` migration                    |
| `supersedes`   | `superseded-by`  | yes      | CLI / plan inlet                                          |
| `implements`   | `implemented-by` | yes      | CLI / plan inlet; plan, agent, and stitch projections     |
| `derives-from` | `derived-into`   | yes      | CLI / plan inlet; research lineage derivation             |
| `produced-by`  | `produced`       | yes      | projected from a stitch's recorded agent                  |
| `launched`     | `launched-by`    | yes      | projected from a configured chop and its published agents |

`blocks` and `depends-on` are reserved. Use `sase bead dep` for scheduling and blocking
relationships instead of storing those as artifact links.

Run `sase artifact link relation list` to inspect the closed registry, or
`sase artifact link relation show <slug>` for one relation's direction, positive and
negative examples, and recommended endpoint kinds. Both forms accept `-j/--json`.
Direction matters: the replacement **supersedes** the old artifact, a plan or agent
**implements** a bead, a stitch is **produced-by** an agent, a chop **launched** an
agent, and a derived report **derives-from** its source. `related` is undirected. Only
`related`, `supersedes`, `implements`, and `derives-from` are writable by the CLI;
`cites` and `read` are observational rows, while `produced-by` and `launched` are
read-only projections from other durable evidence.

## Commands

Create or update a deliberate link:

```bash
sase artifact link add <source-ref> <relation> <target-ref> "<why>"
```

The source is always explicit; it never defaults to the current agent. References may
include their prompt-only leading `@`. `<why>` must be one non-empty line of at most 240
characters. Repeating an identical edge is an `unchanged` success rather than a second
row.

List one artifact's neighborhood, or the current project's recent links:

```bash
sase artifact link list <ref> -d both
sase artifact link list -l 20 -R related
```

Without a reference, `list` shows the current project's newest 50 rows. With one, it
shows that artifact's neighborhood. `-d in|out|both`, `-R/--relation`, and `-o/--origin`
(`manual`, `migrated`, `prompt_ref`, `read`, `derived`, or `projected`) narrow it;
`-l 0` is unlimited and `-j` emits a stable JSON array. The default `--source index`
includes machine-local projected rows; `--source store` reads durable truth only.

Ask SASE for write-free, hard-evidence suggestions before adding a deliberate edge:

```bash
sase artifact link suggest
sase artifact link suggest plan:202608/example.md -l 20
```

Suggestions come only from deterministic filename lineage, a shared bead or epic,
overlapping audited-read sets, or an audited read-log candidate. Existing persisted
links are excluded (`related` is compared in either direction). Each row names its
signal and evidence. This command never writes graph rows, companion files, or commits;
review a suggestion and use `link add` yourself when it expresses the intended meaning.

Remove links between a pair:

```bash
sase artifact link rm <source-ref> <target-ref>
sase artifact link rm <source-ref> <target-ref> -R implements
```

Read an artifact as context with an audited reason:

```bash
sase artifact read <ref> "<why you need this context>"
```

`read` strips leading frontmatter plus managed Links and Referenced By blocks before
printing Markdown. Inside a SASE agent run with an agent identity, it also records a
`read` edge from the agent to the artifact. Outside an agent run it still prints the
artifact and writes the audit row, but warns that no graph edge was recorded. `show`,
`path`, and `open` remain silent reads.

After the body, `read` prints a `Links:` footer to stderr with up to five one-hop
neighbors, semantic links first, followed by `(+N more)` when needed. Reading an
artifact that is the target of `supersedes` also emits a direct warning naming its
replacement.

`link add`, `link rm`, and `migrate-notes --apply` write the artifact-link graph
directly. `link list` reads the current graph rows.

## Projected relationships

Some relationships are computed into the machine-local read model instead of being
stored as link sidecars:

- a published agent's `bead_id`, `epic_bead_id`, or `phase_bead_id` projects
  `agent:<name> implements bead:<id>`;
- a primary-repository commit with a `SASE_BEAD` trailer projects
  `stitch:<sha> implements bead:<id>`;
- a commit with a `SASE_AGENT` trailer (or legacy `AGENT`) projects
  `stitch:<sha> produced-by agent:<name>`; and
- a published chop-agent name that resolves against the live AXE configuration projects
  `chop:<lumberjack>/<chop> launched agent:<name>`.

Projected rows carry `origin: projected` and a `created_by: projection:<rule>` marker.
They appear in `sase artifact link list`, `sase artifact doctor`, and ACE alongside
durable links, but they are recomputed read-model data: `link rm` and the ACE remove
action cannot delete them. Change the durable source evidence instead, then refresh or
repair the aggregate. The health check compares the aggregate against both durable
sidecar truth and these expected projections.

## Rendering

SASE renders deliberate manual and migrated links near the top of the artifact markdown
file in a managed `## Links` table. Automatic prompt citations and audited reads render
at the bottom in `## Referenced By`.

When a prompt expands a document artifact reference, SASE may append up to five one-hop,
directed semantic neighbors as `(linked: …)`. Only `implements`, `derives-from`, and
`supersedes` participate; the expansion is never transitive, and it omits the broad
`related` relation plus observational `cites` / `read` rows.

Markdown document artifacts are their own artifact markdown file. Non-Markdown files use
a sibling `<stem>.md` companion created lazily on the first link. Beads, agents, and
Patches use generated pages, so agents should update their underlying stores with SASE
commands and never hand-edit those generated pages. Stitches have no page of their own;
links to a stitch render on the other artifact.

## Browsing links in ACE

When the selected Agent, Artifact, or AXE chop has links, ACE shows a contextual link
rail. Press `$` to arm it, then `$` again for the first link, `1`-`9` for a numbered
link, or `0` for the complete links panel. A projected group may occupy one rail entry;
choosing it opens a panel scoped to that group instead of guessing which member to
follow.

The panel explains relation direction, provenance, rationale, missing targets, and
staleness. `a`-`z` follow the first 26 rows directly, Enter follows the highlighted row,
and arrows or `Ctrl+N`/`Ctrl+P` move the highlight. `-` removes a writable durable link;
projected rows are read-only. Cross-tab follows record a 32-hop trail: `Ctrl+O` walks
backward and `Ctrl+Shift+O` walks forward, restoring the prior tab, pane, project scope,
query, selection, and supported fold state. Ordinary navigation starts a new trail.

## Authoring links in a proposed plan

An agent may attach deliberate links while authoring a plan by adding a transient
`links:` list to its YAML frontmatter:

```yaml
---
tier: tale
title: Implement the artifact browser
goal: Make historical artifacts searchable
size: small
links:
  - ref: bead:sase-123
    relation: implements
    description: This plan implements the accepted task
---
```

Each entry requires string `ref`, `relation`, and `description` values.
`sase plan propose` validates the entire list before mutating the proposal, restricts it
to the four CLI-writable relations, and enforces the registry's recommended direction
and endpoint kinds. It then removes `links:` from the archived plan, persists the rows
with `manual` origin, and refreshes the managed `## Links` block. The list is an
authoring inlet, not retained plan metadata.

## Automatic derivation and repair

SASE durably derives only relationships backed by deterministic structured evidence:

- `plan:<path> implements bead:<id>` from a plan's `bead_id:` frontmatter, when the bead
  is known to the readable store.
- `agent:<name> cites plan:<path>` by following a plan's canonical `PROMPT` header to
  the archived prompt's canonical `AGENTS` entries, after the agent page is published.
- A research lead `derives-from` its on-disk `__a` and `__b` research-swarm siblings.

Derivation runs on relevant plan/archive and sidecar-commit paths. The built-in hourly
AXE `artifact_link_backfill` chop covers older documents in bounded, checkpointed
batches, drains queued read rows for agents that have since published, recomputes
projected relationships, reconciles the machine-local aggregate, and repairs dangling
references from Git rename history. See
[Default lumberjacks](axe.md#housekeeping-1-hour-interval).

## Beads

Use artifact links for relationship context between beads:

```bash
sase artifact link add bead:<new-task-id> related bead:<other-bead-id> "<why>"
```

Use bead dependencies only for scheduling:

```bash
sase bead dep add <blocked-bead-id> <blocking-bead-id>
```

Historical `RELATED:` notes remain in bead history. `sase artifact link migrate-notes`
dry-runs the conversion, and `--apply` writes typed `related` edges plus `MIGRATED:`
notes without deleting the original text.

Historical schema-v1 `Referenced By` JSON sidecars must be migrated before graph reads.
After artifact-link graduation, readers fail loudly on schema-v1 files instead of
rewriting them implicitly.

## Health and recovery

`sase artifact doctor` reports link health alongside the file index: dangling or
unpublished agent references, stale rendered tables, missing or orphaned companions,
expected durable-plus-projected versus aggregate counts, audited reads versus durable
`read` rows, queued and dropped outbox rows, derived-link coverage, and counts by origin
and relation. It exits 1 for unhealthy state; unpublished agent references are
informational because a queued publication may still resolve them.

`sase artifact doctor --fix` rebuilds the aggregate and managed projections from durable
truth, repairs references whose files can be followed through Git rename history, and
performs the ordinary artifact-index enrichment pass. It does not infer graph state by
parsing hand-authored Markdown.

## Storage lifecycle

Artifact-link truth lives in several places with different durability:

| Path                                                        | Role                                                                                                   | Versioned?                                                                                                                               |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Sidecar `links/**/*.json`                                   | Per-artifact schema-v2 index. This is the durable source used to rebuild the graph.                    | Yes. Committed in the owning document sidecar.                                                                                           |
| Sidecar `links/**/*.lock`                                   | Zero-byte `flock` sentinel for one index. Synchronization state only; never graph data.                | No. Ignored by `/links/**/*.lock`. Existing tracked empty sentinels may remain as compatibility residue; new locks are not added to VCS. |
| `~/.sase/projects/<key>/artifact-links.json`                | Rebuildable project-local aggregate of durable rows plus projected relationships, with its lock.       | No. Local SASE state, never a sidecar commit.                                                                                            |
| `~/.sase/projects/<key>/artifact-link-outbox.jsonl`         | Replay queue for an agent's `read` rows until its published identity can own the durable sidecar link. | No. Machine-local; drained after publication and by hourly housekeeping.                                                                 |
| `~/.sase/projects/<key>/artifact-link-outbox-dropped.jsonl` | Audit trail for stale terminal-agent rows that could not become publishable.                           | No. Machine-local.                                                                                                                       |

`sase artifact link add` and `rm` commit each sidecar they actually change once the
graph mutation succeeds. One command that updates many indexes in the same repository
still creates one `chore(artifact-links): persist link indexes` commit. Crossing
repository boundaries is the lower bound on commit count: two document sidecars means
two commits. Bead endpoints write `LinkAdded` / `LinkRemoved` events and fold into the
existing bead-store commit and publication boundary rather than a document-sidecar file.
A no-op upsert or removal creates no commit.

An audited agent `read` updates the local graph immediately and appends a replayable
outbox row. Once that agent has a published sidecar identity, the commit workflow drains
its rows and commits eligible link JSON; the hourly backfill retries publication gaps.
Rows for terminal agents that remain unpublished for 90 days are removed from the live
queue and appended to the dropped audit. Link commits peel only eligible JSON (and the
lock-ignore rule on first use) out of each sidecar, leaving unrelated or pre-existing
dirty paths for the normal declaration. Publication is verified so an ephemeral checkout
cannot report success while holding the only copy.
