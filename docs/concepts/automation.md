---
title: Automation and human checkpoints
description: How SASE runs recurring work and keeps important decisions reviewable.
search:
  boost: 2
---

# Automation and human checkpoints

SASE moves repeatable work forward in the background and brings people in when a
decision needs review.

## The idea in one picture

```text
Scheduler ──► recurring work and reviews ──► decision
                                              ├── autonomy profile ──► automatic outcome
                                              └── gate ───────────────► human checkpoint
```

The diagram shows how background work can proceed under an autonomy profile or pause for
a person's decision.

## How it works

The scheduler runs recurring routines. Mentors can review proposed changes and leave
findings for a person to consider. Plan approvals put a checkpoint on a proposed
approach, so it can be accepted or sent back with feedback before work proceeds. Other
gates present their available choices and keep the decision attached to the work.

Autonomy profiles set how supported approval gates are handled. A profile can allow a
decision to proceed automatically or leave it for a person. Checkpoints make the choice
visible and preserve human judgment when the work needs it.

## When it matters

- Automate recurring checks when the same work needs to happen over time.
- Use mentor reviews to surface focused feedback on proposed changes.
- Keep a person in the loop when a choice depends on context or carries a meaningful
  tradeoff.

## Do it

- [Get started with SASE](../start/index.md) — run an agent and review its result.
- [Schedule recurring work](../guides/schedule-recurring-work.md) — run a check on a
  schedule.
- [Get automated code review](../guides/get-automated-code-review.md) — review each
  change automatically.

## Look it up

- [Scheduler](../axe.md) — recurring routines and jobs.
- [Mentors](../reference/automation/mentors.md) — automated review of proposed changes.
- [Notifications and gates](../notifications.md) — approval requests and decisions.
- [Autonomy profiles](../reference/cli/autonomy.md) — supported automatic gate
  decisions.
- [Glossary](../reference/glossary.md) — scheduler and gate terms.
- [Design decisions](../reference/design-decisions.md#gates-never-block) — how gates
  keep decisions reviewable.
