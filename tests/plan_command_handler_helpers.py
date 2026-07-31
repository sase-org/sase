"""Shared helpers for ``sase plan propose`` command-handler tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main import plan_command_handler
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.plan_header_block import (
    PlanHeaderSectionKind,
    parse_plan_header_block,
)
from sase.sdd.plan_validate import validate_plan


VALID_TALE = """---
tier: tale
title: Ship the planned change
goal: Ship the planned change
---
# Plan

body
"""

VALID_EPIC = """---
tier: epic
title: Ship the planned change
goal: Deliver the complete capability
phases:
  - id: implementation
    title: Implement the capability
    depends_on: []
    description: "implementation: build and verify the complete capability."
    size: small
---
# Plan

body
"""


def clear_bead_work_association_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep proposal tests independent from the launching agent's bead env."""
    monkeypatch.delenv("SASE_PHASE_BEAD_ID", raising=False)
    monkeypatch.delenv("SASE_EPIC_BEAD_ID", raising=False)
    monkeypatch.delenv("SASE_EPIC_PLAN_REF", raising=False)


def make_artifacts_dir(sase_home: Path) -> Path:
    """Create a realistic artifacts dir layout and return the timestamp dir."""
    artifacts_dir = (
        sase_home
        / "projects"
        / "demo"
        / "artifacts"
        / "workflow-plan"
        / "20260428120000"
    )
    artifacts_dir.mkdir(parents=True)
    return artifacts_dir


def invoke_plan(plan_file: Path) -> int:
    """Invoke ``handle_plan_propose_command`` and return its exit code."""
    with pytest.raises(SystemExit) as exc_info:
        plan_command_handler.handle_plan_propose_command(str(plan_file))
    return int(exc_info.value.code)


def assert_archived_associations(
    artifacts_dir: Path,
    content: str,
    expected_fields: dict[str, str],
) -> None:
    """Assert the archived plan has exactly the expected managed associations."""
    marker = json.loads(
        (artifacts_dir / ".sase_plan_pending").read_text(encoding="utf-8")
    )
    archived = Path(marker["plan_file"])
    archived_content = archived.read_text(encoding="utf-8")
    frontmatter, _body, _had_frontmatter = parse_frontmatter(archived_content)
    for field in ("bead", "parent_bead", "proposed_by"):
        if field in expected_fields:
            assert frontmatter[field] == expected_fields[field]
        else:
            assert field not in frontmatter
    assert "parent" not in frontmatter

    parsed_header = parse_plan_header_block(archived_content)
    parent_section = next(
        (
            section
            for section in parsed_header.sections
            if section.kind is PlanHeaderSectionKind.PARENT
        ),
        None,
    )
    expected_parent = expected_fields.get("parent")
    if expected_parent is None:
        assert parent_section is None
    else:
        assert parent_section is not None
        expected_label = expected_parent.split("plans/", 1)[-1]
        assert parent_section.label == expected_label
        assert parent_section.target == expected_label

    bead_section = next(
        (
            section
            for section in parsed_header.sections
            if section.kind is PlanHeaderSectionKind.BEAD
        ),
        None,
    )
    expected_bead = expected_fields.get("bead")
    if expected_bead is None:
        assert bead_section is None
    else:
        assert bead_section is not None
        assert bead_section.label == expected_bead
        assert bead_section.target is None

    tier = "epic" if content == VALID_EPIC else "tale"
    validation = validate_plan(archived_content, tier)
    assert validation.ok
    assert validation.plan is not None
    assert validation.plan.bead == expected_fields.get("bead")
    assert validation.plan.parent is None
    assert validation.plan.parent_bead == expected_fields.get("parent_bead")
    assert validation.plan.proposed_by == expected_fields.get("proposed_by")
