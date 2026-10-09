"""Shared fixtures for the plan-decide CLI test split.

Public helpers live in this already-private module so the split test
modules can share them without importing ``_``-prefixed names from each
other. The ``tests.test_plan_decide_cli`` facade re-exports
:data:`PENDING_TALE` for existing importers.
"""

from __future__ import annotations

from typing import Any

PENDING_TALE = """---
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
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: "and note the convention in the tui memory"
    default: false
---
# Plan

> [!decision] grouping = pane Order by pane.
> [!decision] grouping = mode Order by mode.
Body mentions tui_note.
"""


def make_definitions() -> list[dict[str, Any]]:
    from sase.sdd.plan_decisions import build_definitions
    from sase.sdd.plan_validate import validate_plan

    validation = validate_plan(PENDING_TALE, "tale")
    assert validation.ok, [str(diagnostic) for diagnostic in validation.diagnostics]
    assert validation.plan is not None
    return build_definitions(validation, "")
