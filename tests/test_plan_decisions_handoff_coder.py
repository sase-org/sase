"""Coder-block tests for Plan Decisions handoff.

Split from ``tests.test_plan_decisions_handoff``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._plan_decisions_handoff_helpers import STAMPED_TALE

AUTO_TALE = """---
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
    answer: pane
decided_by: auto
---
# Plan

> [!decision] grouping = pane Order by pane.
> [!decision] grouping = mode Order by mode.
"""

MEMORY_TALE = """---
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
    answer: pane
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: "please also update the tui memory note"
    default: true
    answer: false
decided_by: auto
---
# Plan

> [!decision] grouping = pane Order by pane.
Body mentions tui_note.
"""

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
---
# Plan

> [!decision] grouping = pane Order by pane.
"""

__all__ = [
    "AUTO_TALE",
    "MEMORY_TALE",
    "PENDING_TALE",
    "tale_path",
    "test_auto_coder_block_says_no_human_reviewed",
    "test_builders_pending_and_accepted",
    "test_declined_memory_routes_by_audience",
    "test_pending_plan_yields_no_coder_block",
    "test_reviewer_block_helper_fails_open",
    "test_reviewer_block_helper_prefers_archived_copy",
    "test_reviewer_coder_block_names_branch_and_default",
]


@pytest.fixture()
def tale_path(tmp_path: Path) -> Path:
    path = tmp_path / "tale.md"
    path.write_text(STAMPED_TALE, encoding="utf-8")
    return path


def test_reviewer_coder_block_names_branch_and_default(tale_path: Path) -> None:
    from sase.sdd.plan_decision_handoff import coder_decisions_block

    block = coder_decisions_block(tale_path)
    assert "Reviewer decisions for this plan" in block
    assert "grouping = mode" in block
    assert "planner default: pane" in block
    assert "Implement only the branches selected above." in block


def test_auto_coder_block_says_no_human_reviewed(tmp_path: Path) -> None:
    path = tmp_path / "auto.md"
    path.write_text(AUTO_TALE, encoding="utf-8")
    from sase.sdd.plan_decision_handoff import coder_decisions_block

    block = coder_decisions_block(path)
    assert "no human reviewed" in block


def test_pending_plan_yields_no_coder_block(tmp_path: Path) -> None:
    path = tmp_path / "pending.md"
    path.write_text(PENDING_TALE, encoding="utf-8")
    from sase.sdd.plan_decision_handoff import coder_decisions_block

    assert coder_decisions_block(path) == ""


def test_declined_memory_routes_by_audience(tmp_path: Path) -> None:
    path = tmp_path / "memory.md"
    path.write_text(MEMORY_TALE, encoding="utf-8")
    from sase.sdd.plan_decision_handoff import coder_decisions_block

    coder_block = coder_decisions_block(path, audience="tale_coder")
    phase_block = coder_decisions_block(path, audience="epic_phase")
    assert "/sase_new_task" in coder_block
    assert "PROPOSED FOLLOW-UP:" not in coder_block
    assert "PROPOSED FOLLOW-UP:" in phase_block
    assert "/sase_new_task" not in phase_block


def test_reviewer_block_helper_prefers_archived_copy(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(PENDING_TALE, encoding="utf-8")
    archived = tmp_path / "archived.md"
    archived.write_text(STAMPED_TALE, encoding="utf-8")
    plan_result = SimpleNamespace(
        saved_plan_path=str(archived), plan_file=str(plan_path)
    )
    from sase.axe.run_agent_exec_plan_accept import _reviewer_decisions_block

    block = _reviewer_decisions_block(plan_result, plan_path, tmp_path)
    assert block.startswith("\n\nReviewer decisions for this plan")


def test_reviewer_block_helper_fails_open(tmp_path: Path) -> None:
    plan_result = SimpleNamespace(saved_plan_path=None, plan_file="/nope.md")
    from sase.axe.run_agent_exec_plan_accept import _reviewer_decisions_block

    assert _reviewer_decisions_block(plan_result, "/nope.md", tmp_path) == ""


def test_builders_pending_and_accepted(tale_path: Path) -> None:
    from sase.sdd._plan_display_decisions import (
        accepted_decisions_text,
        decision_text_lines,
        format_decision_value,
        pending_decisions_text,
    )
    from sase.sdd.plan_decision_handoff import load_stamped_decisions

    stamped = load_stamped_decisions(tale_path)
    assert stamped is not None
    pending = decision_text_lines(pending_decisions_text(stamped.sheet))
    accepted = decision_text_lines(
        accepted_decisions_text(stamped.sheet, stamped.decided_by, stamped.decided_via)
    )
    assert format_decision_value(True) == "yes"
    assert format_decision_value(False) == "no"
    assert format_decision_value("mode") == "mode"
    assert any("\u2605" in line for line in pending)
    assert any("How should the overlay group bindings?" in line for line in pending)
    assert accepted[0] == "decided by reviewer · TUI"
    assert any("\u25c9 grouping = mode\u25cf" in line for line in accepted)
