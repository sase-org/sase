---
title: Work units
description:
  How goals, plans, beads, and Patches represent outcomes, coordinated work, and
  reviewable changes.
search:
  boost: 2
---

# Work units

SASE uses separate records for the outcome a person wants, the work planned to reach it,
and the changes that need review.

## The idea in one picture

```text
Goal ──► Plan ──► Beads ──► Agent work ──► Patch
 desired    approach  work items              review
 outcome
```

This is one way to connect the records on a larger piece of work; a small change may use
only some of them.

## How it works

A **Goal** describes a result a person wants and how they will recognize it. A **plan**
records an approach; a larger plan can be broken into phases and dependencies. **Beads**
track the individual work units that agents or people can pick up. A **Patch** gathers a
proposed code change with its review state.

These records answer different questions. A Goal says what should become true. A plan
explains an approach. A bead identifies work to do. A Patch makes a resulting change
reviewable. Keeping those roles distinct makes it possible to revise a plan, retry one
work unit, or review a change without losing the desired outcome.

## When it matters

- Start with a Goal when the desired result needs a durable owner or progress history.
- Use a plan and beads when work needs decomposition, ordering, or explicit handoffs.
- Use a Patch when a change needs review and a record of its lifecycle.

## Do it

- [Get started with SASE](../start/index.md) — see work records in a first project
  workflow.

## Look it up

- [Goals](../goals.md) — goal records and their lifecycle.
- [Spec-driven development](../sdd.md) — plans and their storage.
- [Beads](../beads.md) — work units, dependencies, and execution.
- [Patch format](../change_spec.md) — review records for changes.
