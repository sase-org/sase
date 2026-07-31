"""Tests for sase.bead.attribution (bead creator resolution)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.attribution import (
    acting_agent_name,
    plan_proposed_by,
    resolve_bead_creator,
)
from sase.bead.model import IssueType
from sase.core.agent_identity_facade import globalize_owned_agent_name


def test_acting_agent_name_globalizes_sase_agent_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "q8--plan")
    assert acting_agent_name() == globalize_owned_agent_name("q8--plan")


def test_acting_agent_name_ignores_bare_sase_agent_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SASE_AGENT=1`` is a launcher boolean, never an agent name."""
    monkeypatch.setenv("SASE_AGENT", "1")
    assert acting_agent_name() is None


def test_acting_agent_name_without_agent_env() -> None:
    assert acting_agent_name() is None


def test_acting_agent_name_from_agent_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "q8"}), encoding="utf-8"
    )
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    assert acting_agent_name() == globalize_owned_agent_name("q8")


def test_acting_agent_name_prefers_meta_over_bare_sase_agent_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "q8"}), encoding="utf-8"
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    assert acting_agent_name() == globalize_owned_agent_name("q8")


def test_acting_agent_name_rejects_invalid_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "not a valid name!")
    assert acting_agent_name() is None


def _write_plan(path: Path, frontmatter: str) -> Path:
    path.write_text(f"---\n{frontmatter}---\n\n# Plan\n", encoding="utf-8")
    return path


def test_plan_proposed_by_reads_field(tmp_path: Path) -> None:
    plan = _write_plan(
        tmp_path / "plan.md",
        "tier: epic\nproposed_by: bbugyi200.athena.q8--plan\n",
    )
    assert plan_proposed_by(plan) == "bbugyi200.athena.q8--plan"


def test_plan_proposed_by_missing_file(tmp_path: Path) -> None:
    assert plan_proposed_by(tmp_path / "nope.md") is None


def test_plan_proposed_by_without_frontmatter(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    assert plan_proposed_by(plan) is None


def test_plan_proposed_by_absent_key(tmp_path: Path) -> None:
    plan = _write_plan(tmp_path / "plan.md", "tier: epic\n")
    assert plan_proposed_by(plan) is None


def test_plan_proposed_by_blank_value(tmp_path: Path) -> None:
    plan = _write_plan(tmp_path / "plan.md", "tier: epic\nproposed_by: '   '\n")
    assert plan_proposed_by(plan) is None


def test_resolve_bead_creator_phase_defers_to_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "q8")
    assert resolve_bead_creator(issue_type=IssueType.PHASE) is None


def test_resolve_bead_creator_plan_prefers_proposer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "q8")
    assert (
        resolve_bead_creator(
            issue_type=IssueType.PLAN,
            plan_proposed_by="bbugyi200.athena.other--plan",
        )
        == "bbugyi200.athena.other--plan"
    )


def test_resolve_bead_creator_plan_falls_back_to_acting_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "q8")
    assert resolve_bead_creator(
        issue_type=IssueType.PLAN
    ) == globalize_owned_agent_name("q8")


def test_resolve_bead_creator_task_uses_acting_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "q8")
    assert resolve_bead_creator(
        issue_type=IssueType.TASK
    ) == globalize_owned_agent_name("q8")


def test_resolve_bead_creator_task_without_agent() -> None:
    assert resolve_bead_creator(issue_type=IssueType.TASK) is None
