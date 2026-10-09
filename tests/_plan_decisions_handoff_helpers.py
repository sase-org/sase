"""Shared tales for Plan Decisions handoff tests.

Split from ``tests.test_plan_decisions_handoff``; the original module
re-exports its tests so its import path keeps working.

Names are public so the ``test_plan_decisions_handoff_*`` split modules can
share them without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

STAMPED_TALE = """---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane, matching the footer hints
      mode: By leader mode; denser, but splits pane actions
    default: pane
    why: pane keeps the footer's order
    answer: mode
decided_by: reviewer
decided_via: tui
---
# Plan

> [!decision] grouping = pane Order by pane.
> [!decision] grouping = mode Order by mode.
"""

STAMPED_EPIC = """---
tier: epic
title: Keymap help overlay epic
goal: Ship the overlay.
phases:
  - id: build
    title: Build it
    depends_on: []
    size: small
    description: Build the overlay.
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane, matching the footer hints
      mode: By leader mode; denser, but splits pane actions
    default: pane
    why: pane keeps the footer's order
    answer: mode
decided_by: reviewer
decided_via: telegram
---
# Plan

> [!decision] grouping = mode Order by mode.
"""
