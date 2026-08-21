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

| Relation       | Inverse          | Directed | Written by                                 |
| -------------- | ---------------- | -------- | ------------------------------------------ |
| `cites`        | `cited-by`       | yes      | prompt-reference expansion                 |
| `read`         | `read-by`        | yes      | `sase artifact read`                       |
| `related`      | `related`        | no       | `sase artifact link`; `RELATED:` migration |
| `supersedes`   | `superseded-by`  | yes      | `sase artifact link`                       |
| `implements`   | `implemented-by` | yes      | `sase artifact link`                       |
| `derives-from` | `derived-into`   | yes      | `sase artifact link`                       |

`blocks` and `depends-on` are reserved. Use `sase bead dep` for scheduling and blocking
relationships instead of storing those as artifact links.

## Commands

Create or update a deliberate link:

```bash
sase artifact link add <source-ref> <relation> <target-ref> "<why>"
```

List one artifact's neighborhood, or the current project's recent links:

```bash
sase artifact link list <ref> -d both
sase artifact link list -l 20 -R related
```

Remove links between a pair:

```bash
sase artifact link rm <source-ref> <target-ref>
sase artifact link rm <source-ref> <target-ref> -R implements
```

Read an artifact as context with an audited reason:

```bash
sase artifact read <ref> "<why you need this context>"
```

`read` strips managed Links and Referenced By blocks before printing Markdown. Inside a
SASE agent run with an agent identity, it also records a `read` edge from the agent to
the artifact. Outside an agent run it still prints the artifact and writes the audit
row, but warns that no graph edge was recorded. `show`, `path`, and `open` remain silent
reads.

`link add`, `link rm`, and `migrate-notes --apply` write the artifact-link graph
directly. `link list` reads the current graph rows.

## Rendering

SASE renders deliberate manual and migrated links near the top of the artifact markdown
file in a managed `## Links` table. Automatic prompt citations and audited reads render
at the bottom in `## Referenced By`.

Markdown document artifacts are their own artifact markdown file. Non-Markdown files use
a sibling `<stem>.md` companion created lazily on the first link. Beads, agents, and
Patches use generated pages, so agents should update their underlying stores with SASE
commands and never hand-edit those generated pages. Stitches have no page of their own;
links to a stitch render on the other artifact.

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

## Storage lifecycle

Artifact-link truth lives in three places with different durability:

| Path                                         | Role                                                                                    | Versioned?                                                                                                                               |
| -------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Sidecar `links/**/*.json`                    | Per-artifact schema-v2 index. This is the durable source used to rebuild the graph.     | Yes. Committed in the owning document sidecar.                                                                                           |
| Sidecar `links/**/*.lock`                    | Zero-byte `flock` sentinel for one index. Synchronization state only; never graph data. | No. Ignored by `/links/**/*.lock`. Existing tracked empty sentinels may remain as compatibility residue; new locks are not added to VCS. |
| `~/.sase/projects/<key>/artifact-links.json` | Rebuildable project-local aggregate plus its lock.                                      | No. Local SASE state, never a sidecar commit.                                                                                            |

`sase artifact link add` and `rm` commit each sidecar they actually change once the
graph mutation succeeds. One command that updates many indexes in the same repository
still creates one `chore(artifact-links): persist link indexes` commit. Crossing
repository boundaries is the lower bound on commit count: two document sidecars means
two commits. Bead endpoints write `LinkAdded` / `LinkRemoved` events and fold into the
existing bead-store commit and publication boundary rather than a document-sidecar file.
A no-op upsert or removal creates no commit.

Implicit agent `read` links accumulate during a run and are committed by the built-in
commit finalizer even when the turn ends through a plan handoff and therefore has no
final declaration. That pass peels only eligible link JSON (and the lock-ignore rule, on
first use) out of each sidecar, leaving unrelated or pre-existing dirty paths for the
normal declaration. Publication of a finalizer-created sidecar commit is verified
synchronously so an ephemeral checkout cannot report success while holding the only
copy.
