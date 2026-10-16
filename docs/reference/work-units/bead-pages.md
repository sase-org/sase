---
title: Bead pages
description: The generated pages that present bead records and their relationships.
---

# Bead pages

This page describes how SASE presents bead records in generated pages.

## Bead Pages {#bead-pages-1}

Projects with a hosted beads sidecar can publish one Markdown page per bead. Pages live
in the `--beads` repository under `pages/<root>/`, where `<root>` is the bead ID segment
before the first dot. The root bead renders as `pages/<root>/README.md`; descendants
render as `pages/<root>/<bead-id>.md`.

An artifact reference such as `@bead:<bead-id>` addresses that generated page directly.
The payload is the exact bead ID, with no prefix-less shorthand and no `#L`, `#page=`,
or `#t=` fragment support. Addressing is lexical and offline: SASE derives the page path
from the ID without reading `issues.jsonl`, then reports the page missing if it has not
yet been published. Run `sase bead pages refresh --write` to publish or repair bead
pages before sharing durable `@bead:` refs.

Pages are generated projections, not hand-maintained state. They are rebuilt from the
canonical bead event store plus the primary repository's commit history, and they link
to the bead's plan, artifact references, parent and child beads, dependencies,
associated agents, and commits. Current commits use a structured `SASE_BEAD=<id>` footer
tag instead of a subject-line parenthetical; historical commits with trailing
`(<bead-id>)` subjects are still recognized when the ID exists in the store. Published
agent and session pages in the agents sidecar link back to the bead they worked, so the
bead↔agent relationship is navigable in both directions.

Each page's identity block also renders the bead's creator as `**Created by:** <name>`,
between `**Owner:**` and `**Assignee:**`. It links to the creator's hosted
agents-sidecar page when one resolves and otherwise renders as inline code with no link;
a bead with no recorded creator omits the fact entirely.

```bash
sase bead pages refresh                 # dry run; writes nothing
sase bead pages refresh --write         # write changed pages and commit one beads-sidecar batch
sase bead pages refresh --bead beads-1  # refresh one lineage
sase bead pages refresh --json          # machine-readable report
sase bead pages url beads-1.2           # print the hosted URL for one bead
```

Per-commit publication refreshes the committed bead's lineage after a `create_commit` or
`create_pull_request` workflow that carries `SASE_BEAD=`. The shared `pages/README.md`
roster is owned by `sase bead pages refresh`, so regular commits avoid rewriting a file
every active agent could touch. `sase bead show <id>` prints a `PAGE` section when the
local sidecar remote and branch resolve to a hosted URL; `--format json` includes
`page_url` in the same case. Its `CREATED BY` section similarly links agent-created
beads to the corresponding hosted agents-sidecar page. An epic agent clan's summary
panel also shows its epic bead's hosted page URL when one resolves; run
`sase plan links refresh` to repair a plan whose `BEAD` bullet predates hosted links.
Epic clan summaries place the label and complete URL on one logical line, with no
SASE-authored break or whitespace inside the address. A panel too narrow for the
composed row moves the whole address to the next row flush-left, so terminal URL
matchers and copy/paste always see the complete target.

## Related

- [Bead storage](bead-storage.md)
