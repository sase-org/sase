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
    description: "'Implement the requested change' section: deliver and verify the approved implementation."
---
# Plan

Implement the requested change.
"""
