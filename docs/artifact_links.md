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

`read` strips managed Links and Referenced By blocks before printing Markdown. When the
`artifact_links` beta flag is enabled inside an agent run, it also records a `read` edge
from the agent to the artifact. `show`, `path`, and `open` remain silent reads.

`link add`, `link rm`, and `migrate-notes --apply` require the `artifact_links` feature
flag. `link list` can read existing rows with the flag off, and `read` still prints with
an audit warning when it cannot record a link edge.

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
