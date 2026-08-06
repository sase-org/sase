"""Reusable valid plan documents for approval-boundary tests."""

VALID_TALE_PLAN = """---
tier: tale
title: Approved implementation
goal: Deliver the approved implementation
---
# Plan

Implement the requested change.
"""

VALID_EPIC_PLAN = """---
tier: epic
title: Approved implementation
goal: Deliver the approved implementation in ordered phases
phases:
  - id: implementation
    title: Implement the requested change
    depends_on: []
    description: "implementation: deliver and verify the approved implementation."
    size: small
---
# Plan

Implement the requested change.
"""

# ``VALID_EPIC_PLAN`` with a hand-authored trailing-text annotation on the
# machine-owned ``PARENT`` header bullet -- the exact mistake that motivated
# the ``header-invalid`` diagnostic (see plan_header_validation.md).
MALFORMED_HEADER_EPIC_PLAN = VALID_EPIC_PLAN.replace(
    "---\n# Plan",
    "---\n\n"
    "- **PARENT:** [202608/parent.md](202608/parent.md) (epic sase-1, closed)\n\n"
    "# Plan",
)
