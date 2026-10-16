---
title: How changes land
description: How SASE carries agent changes through review and into version control.
search:
  boost: 2
---

# How changes land

SASE routes completed work through a host-owned workflow that records the result and
asks the active version-control provider to carry it forward.

## The idea in one picture

```text
Agent work ──► Host finalizer ──► VCS provider ──┬──► Commit or proposal
                                  └── Pull request ──► Patch
Commit or proposal ──► Stitches
```

## How it works

After an agent turn finishes, the host's
[commit finalizer](../contribute/commit-workflow-orchestrator.md#commit-finalizer)
checks for changes and runs the selected workflow. The workflow calls the
[VCS provider](../reference/vcs/index.md), which handles operations for the project's
version-control system.

A workflow can create a commit, save a proposal, or open a pull request. SASE records
commit and proposal results as [Stitches](../reference/vcs/index.md); a pull request
creates a Patch that carries the review state. The agent supplies the result for the
host to process, while the host owns the finalizer and the VCS operation.

## When it matters

- Choose a commit when the change belongs directly on the current branch.
- Choose a proposal when you want to save a diff for later application.
- Choose a pull request when another person should review the change before it merges.

## Do it

- [Review and land a change](../guides/review-and-land-change.md) — inspect an agent's
  result and complete its review.
- [Get automated code review](../guides/get-automated-code-review.md) — review each
  change automatically before it lands.

## Look it up

- [Commit workflows](../reference/vcs/index.md) — workflow behavior and finalizer
  details.
- [VCS providers](../reference/vcs/index.md) — version-control operations and provider
  boundaries.
- [Patch format](../reference/work-units/patches.md) — the review record created for a
  pull request.
