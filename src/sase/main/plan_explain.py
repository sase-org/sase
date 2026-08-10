"""Tier-specific authoring guidance for ``sase plan validate --explain``."""

from __future__ import annotations


PLAN_HEADER_BLOCK_NOTE = """SASE owns the plan's provenance header block; do not author it. SASE writes and reconciles
the leading `PROMPT`, `PARENT`, `BEAD`, `AGENTS`, and `COMMITS` Markdown bullets itself, and `sase plan links refresh`
keeps them current. A hand-authored bullet that deviates from the canonical form is a validation error, not a style
choice: a link-shaped section (`PLAN`, `PROMPT`, `PARENT`, `BEAD`) must be a bolded key followed by exactly one
Markdown link and nothing else, and a list-shaped section (`AGENTS`, `ARTIFACTS`, `COMMITS`) must be a bare bolded key
whose entries are indented bullets.
In particular, name a parent plan through the `PARENT` bullet SASE writes, never through a `parent:` frontmatter
property: that property is deprecated and is migrated into the bullet."""

TALE_PLAN_EXPLANATION = (
    """A tale requires this frontmatter shape:

```yaml
---
tier: tale
title: Focused capability rollout
goal: Describe the outcome this plan will achieve.
size: medium
---
# Plan: Descriptive title

Describe the implementation.
```

Every tale must declare `size`. Read `sase/memory/sase_sizes.md` with the `/sase_memory_read` skill before choosing it;
that note owns the size meanings, plan-first behavior, and model routing rules. Set `model` explicitly only when the
user's prompt requested a specific model.

"""
    + PLAN_HEADER_BLOCK_NOTE
)

EPIC_PLAN_EXPLANATION = (
    """An epic requires a title and a non-empty ordered phase list:

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
    description: "core: implement workspace selection and safety guards."
  - id: cli
    title: sase workspace gc command
    depends_on: [core]
    size: small
    description: "cli: add the CLI flow and progress reporting."
  - id: smoke
    title: End-to-end GC smoke exercises
    depends_on: [cli]
    size: xsmall
    description: "smoke: exercise successful and guarded cleanup."
---
# Plan: Descriptive title

Describe the implementation.
```

Phase IDs must be unique slugs. Dependencies may only name earlier-listed phases; do not use self, duplicate, unknown,
or forward references. Give every phase a `description` that starts with that phase's own `id` followed by `: `, then
briefly summarizes the phase's section of the plan body. Do not quote or repeat the section title — the phase's `title`
already names that section — and do not reference the plan file itself because `sase bead show` already displays it.
Every phase must declare `size: xsmall | small | medium | large | xlarge`. Choose it after reading
`sase/memory/sase_sizes.md` with the `/sase_memory_read` skill; that note owns the size meanings, plan-first behavior,
and model routing rules.

A phase's `model` is optional. Set it explicitly only when the user's prompt requested a specific model. For a phase
with no requested model, omit it so size-derived routing can choose the default. The optional top-level `model` selects
the tale follow-up or the epic's land agent.

"""
    + PLAN_HEADER_BLOCK_NOTE
)

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
