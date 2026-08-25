---
keyword: Sase Workspace
aliases:
  - workspace
---

A sase workspace is a numbered clone of a project's primary repo, managed by the
workspace store and tracked in that project's `registry.json`. Each SASE agent claims
exactly one workspace until completion. Workspace directories are not repos. Linked-repo
clones materialized for a workspace are repo checkouts, not additional workspaces.
