"""Fail-closed associated-plan tests for explicit phase-family metadata."""

from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
from sase.ace.tui.models.agent_associated_plan import resolve_agent_plan_enrichment
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _write_epic(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "tier: epic\n"
        "title: Epic phase metadata\n"
        "goal: Keep phase workers phase-local.\n"
        "phases:\n"
        "  - id: core\n"
        "    title: Core phase\n"
        "    depends_on: []\n"
        "  - id: docs\n"
        "    title: Documentation phase\n"
        "    depends_on: [core]\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    return path


def test_explicit_phase_role_recovers_missing_phase_id_without_bead_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_epic(tmp_path / "plans" / "epic.md")
    agent = make_agent(
        agent_name="sase-1.2",
        agent_family_role="phase",
        epic_bead_id="sase-1",
        sdd_plan_path="plans/epic.md",
        plan_committed=True,
        workspace_dir=str(tmp_path),
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("explicit phase must not read beads"),
    )

    enrichment = resolve_agent_plan_enrichment(agent)

    assert enrichment.role == "phase"
    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.id == "sase-1.2"
    assert enrichment.phase_bead.description == (
        "Phase `docs` in approved epic plan `plans/epic.md`."
    )
    assert enrichment.phase_bead.epic_title == "Epic phase metadata"
    assert enrichment.phase_bead.actual_plan_path == str(plan.resolve())
    assert enrichment.phase_bead.display_plan_path == "plans/epic.md"
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())


def test_explicit_phase_role_without_bead_identity_stays_phase_local(
    tmp_path: Path,
) -> None:
    plan = _write_epic(tmp_path / "plans" / "epic.md")

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name="phase-worker",
            agent_family_role="phase",
            epic_bead_id="sase-1",
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.role == "phase"
    assert enrichment.phase_bead is None
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())
