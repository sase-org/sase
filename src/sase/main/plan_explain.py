"""Tier-specific authoring guidance for ``sase plan validate --explain``."""

from __future__ import annotations


TALE_PLAN_EXPLANATION = """A tale requires this frontmatter shape:

```yaml
---
tier: tale
title: Focused capability rollout
goal: Describe the outcome this plan will achieve.
---
# Plan: Descriptive title

Describe the implementation.
```"""

EPIC_PLAN_EXPLANATION = """An epic requires a title and a non-empty ordered phase list:

```yaml
---
tier: epic
title: Workspace GC rewrite
goal: >
  Stale workspace checkouts are garbage-collected safely, and reclaim progress is visible.
phases:
  - id: core
    title: GC planner and safety checks
    depends_on: []
    size: medium
    description: "'GC planner and safety checks' section: implement workspace selection and safety guards."
  - id: cli
    title: sase workspace gc command
    depends_on: [core]
    size: small
    description: "'sase workspace gc command' section: add the CLI flow and progress reporting."
  - id: smoke
    title: End-to-end GC smoke exercises
    depends_on: [cli]
    size: small
    description: "'End-to-end GC smoke exercises' section: exercise successful and guarded cleanup."
    model: haiku
---
# Plan: Descriptive title

Describe the implementation.
```

Phase IDs must be unique slugs. Dependencies may only name earlier-listed phases; do not use self, duplicate, unknown,
or forward references. Give every phase a `description` that names its section in the plan body and briefly summarizes
that section; do not reference the plan file itself because `sase bead show` already displays it. Every phase must
declare `size: small | medium | large`. Use `medium` when the phase is potentially a lot of work and justifies its own
plan file. Use `large` when you suspect that plan file would itself be large enough to merit an epic tier. Use `small`
otherwise. Small phase agents implement directly and do not create plans. Medium and large phase agents create plans
before implementation. By default, phase size also selects the model capability appropriate for the work, unless that
phase has an explicit `model` override.

A phase's `model` is optional. Only set it when the user's prompt requested a specific model, or when that phase's agent
does not do real consequential work (for example, a phase that exercises or tests the feature itself). An explicit phase
model is allowed for every size and always takes precedence over the size-derived default. The optional top-level
`model` selects the tale's coder follow-up or the epic's land agent."""

INVALID_PLAN_TIER_HINT = (
    "Set a valid `tier: tale` or `tier: epic` property in the plan frontmatter."
)

_PLAN_EXPLANATIONS = {
    "tale": TALE_PLAN_EXPLANATION,
    "epic": EPIC_PLAN_EXPLANATION,
}


def plan_explanation(tier: str) -> str:
    """Return authoring guidance for one supported plan tier."""
    try:
        return _PLAN_EXPLANATIONS[tier]
    except KeyError as exc:
        raise ValueError(f"unsupported plan tier: {tier}") from exc


__all__ = [
    "EPIC_PLAN_EXPLANATION",
    "INVALID_PLAN_TIER_HINT",
    "TALE_PLAN_EXPLANATION",
    "plan_explanation",
]
