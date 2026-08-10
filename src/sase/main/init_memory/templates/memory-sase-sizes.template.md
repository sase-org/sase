---
type: long
parent: sase/memory/sase_beads.md
description:
  SASE size scale guidance for epic phases, task beads, and tale plans, including plan-first behavior, task defaults,
  and model routing.
---

# SASE Sizes

SASE uses one size scale for epic phases, task beads, and tale plans: `xsmall`, `small`, `medium`, `large`, `xlarge`.
Size chooses the default work model through `@<size>_worker` aliases and decides whether the worker plans before
implementing. An explicit `model` always wins over size-derived routing.

- `xsmall`: the simplest tasks needing almost no reasoning, such as launching SASE agents only to observe their output
  while testing a SASE agent feature.
- `small`: focused work the agent can implement directly.
- `medium`: substantial but bounded work still implemented directly from its description.
- `large`: work that needs a separate planning handoff and may itself justify an epic plan.
- `xlarge`: rare; use when the work is too large to plan effectively alone, or when intentionally deferring part of a
  feature's planning. Choose it only when fairly confident the worker will author an epic plan.

Only `large` and `xlarge` receive `#plan` and plan before implementing. `xsmall`, `small`, and `medium` implement
directly.

Tale plans MUST declare `size: xsmall | small | medium`. A tale is single-agent direct implementation work, so `large`
and `xlarge` are invalid tale sizes; work that large belongs in an epic.

Authoring a plan with `/sase_plan` is itself `large` or `xlarge` work: `large` means the agent authors a tale, while
`xlarge` means the agent authors an epic. The task or phase size names the handoff; the tale plan's own `size` then
names the follow-up implementation scope.

When creating a new task bead, default to `large`. Use `xsmall`, `small`, or `medium` only when very confident you know
the precise root cause, and describe that root cause in the bead. Use `xlarge` only when very certain the work needs an
epic plan and multiple agents.

Default model aliases are `@xsmall_worker`, `@small_worker`, `@medium_worker`, `@large_worker`,
and `@xlarge_worker`. An explicit `model` on a bead or plan takes precedence.
