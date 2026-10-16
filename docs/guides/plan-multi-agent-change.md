---
title: Plan a multi-agent change
description: Turn a large change into a reviewed plan whose phases agents work through.
---

# Plan a multi-agent change

This guide turns a change that is too large for one agent into a reviewed plan with
ordered phases. It assumes the goal is clear but the decomposition is not; if the work
fits one agent, run it directly instead.

## Before you start

You need a checkout where `sase` runs and a project with plan storage configured. No
running agent is required.

## 1. Write the plan file and validate it

Write a Markdown plan with frontmatter naming its tier: `tale` for work one agent
implements directly, `epic` for work split into `phases` with `id`, `title`,
`depends_on`, and `size` entries. Keep the body to the outcome, the phases, and the
decisions the reviewer must make.

Check the schema before proposing anything:

```bash
sase plan validate sase_plan_feature.md
```

The validator reports every problem in one pass with the field at fault. Fix those lines
and re-run until it passes.

## 2. Propose the plan and get it approved

Submit the file for review:

```bash
sase plan propose sase_plan_feature.md
```

Approve it from the TUI or the CLI. An epic needs its kind stated explicitly so it is
never launched as a single agent by accident:

```bash
sase plan approve sase_plan_feature --kind epic
```

Approval archives the plan and starts the work: a tale launches its coder, while an epic
hands its phases to the bead tracker. Answer any plan decision at approval time with a
repeated `-D id=value` flag.

## 3. Follow the phases through

Preview what an epic will launch before it starts, then launch it:

```bash
sase bead work sase_plan_feature.md --dry-run
sase bead work sase_plan_feature.md --yes
```

Track progress with the bead list and the plan list. Each phase runs its own agent, so a
stuck phase can be retried without redoing the phases that already landed.

## If it goes wrong

A plan that never leaves review usually failed validation or is waiting on a decision:
re-run the validator and check the pending approvals with `sase plan`. For a phase that
fails or never starts, see [Unstick a queued agent](unstick-queued-agent.md).

## Related

- [Spec-driven development](../sdd.md) — plan tiers, storage, and the approval flow.
- [Beads](../beads.md) — phases, dependencies, and tracking commands.
- [Work units](../concepts/work-units.md) — when to use a plan over a goal or a Patch.
