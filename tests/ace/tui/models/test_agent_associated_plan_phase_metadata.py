"""Associated-plan phase metadata projection and failure tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
from sase.ace.tui.models.agent_associated_plan import (
    PhaseBeadSummary,
    resolve_agent_plan_enrichment,
)
from sase.bead.model import Issue, IssueType, PhaseSize
from tests.ace.tui.models._agent_associated_plan_helpers import write_epic
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_caches() -> Iterator[None]:
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


@pytest.mark.parametrize(
    (
        "epic_bead_id",
        "phase_bead_id",
        "expected_phase_title",
        "expected_description",
        "expected_size",
    ),
    [
        (
            "sase-1",
            "sase-1.1",
            "Canonical phase summaries",
            "Normalize the authoritative validator payload.",
            "small",
        ),
        (
            "sase-1",
            "sase-1.2",
            "Independent documentation",
            "Phase `docs` in approved epic plan `plans/epic.md`.",
            "small",
        ),
        (
            "sase-42.3",
            "sase-42.3.3",
            "Responsive roadmap",
            "Phase `render` in approved epic plan `plans/epic.md`.",
            "medium",
        ),
    ],
    ids=["first", "middle", "nested-epic-id"],
)
def test_modern_phase_uses_validated_frontmatter_order_for_structure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    epic_bead_id: str,
    phase_bead_id: str,
    expected_phase_title: str,
    expected_description: str,
    expected_size: str,
) -> None:
    plan = write_epic(tmp_path / "plans" / "epic.md")
    agent = make_agent(
        agent_name=phase_bead_id,
        epic_bead_id=epic_bead_id,
        phase_bead_id=phase_bead_id,
        epic_plan_ref="plans/epic.md",
        sdd_plan_path="plans/epic.md",
        plan_committed=True,
        workspace_dir=str(tmp_path),
    )
    phase_issue = Issue(
        id=phase_bead_id,
        title="Stale bead title must not win",
        issue_type=IssueType.PHASE,
        parent_id="stale-parent",
        description="Stale bead description must not win.",
        created_at="2026-08-01T14:30:00Z",
        notes="phase-owned note survives structure projection",
        size=PhaseSize.XLARGE,
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: (
            phase_issue if bead_id == phase_issue.id else None
        ),
    )

    enrichment = resolve_agent_plan_enrichment(agent)

    assert enrichment.role == "phase"
    assert enrichment.phase_bead == PhaseBeadSummary(
        id=phase_bead_id,
        phase_title=expected_phase_title,
        description=expected_description,
        actual_plan_path=str(plan.resolve()),
        display_plan_path="plans/epic.md",
        plan_exists=True,
        plan_readable=True,
        epic_title="Epic phase metadata",
        size=expected_size,  # type: ignore[arg-type]
        created_at=phase_issue.created_at,
        notes=phase_issue.notes,
    )
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())


@pytest.mark.parametrize("lookup_result", ["missing", "wrong-type"], ids=str)
def test_modern_phase_issue_lookup_failure_keeps_plan_summary_note_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lookup_result: str,
) -> None:
    plan = write_epic(tmp_path / "plans" / "epic.md")
    wrong_type = Issue(
        id="sase-1.1",
        title="Wrong type",
        issue_type=IssueType.TASK,
        notes="task notes must not appear on a phase lane",
    )

    def lookup(_agent: object, bead_id: str, **_kwargs: object) -> Issue | None:
        if lookup_result == "wrong-type" and bead_id == wrong_type.id:
            return wrong_type
        return None

    monkeypatch.setattr(plan_model, "_lookup_issue", lookup)

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name="sase-1.1",
            epic_bead_id="sase-1",
            phase_bead_id="sase-1.1",
            epic_plan_ref="plans/epic.md",
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.role == "phase"
    assert enrichment.phase_bead == PhaseBeadSummary(
        id="sase-1.1",
        phase_title="Canonical phase summaries",
        description="Normalize the authoritative validator payload.",
        actual_plan_path=str(plan.resolve()),
        display_plan_path="plans/epic.md",
        plan_exists=True,
        plan_readable=True,
        epic_title="Epic phase metadata",
        size="small",
        notes=None,
    )
    assert enrichment.associated_plan is None


def test_modern_phase_normalizes_multiline_description(tmp_path: Path) -> None:
    plan = write_epic(tmp_path / "plans" / "epic.md")
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "description: Normalize the authoritative validator payload.",
            "description: >-\n      Normalize the authoritative\n"
            "      validator payload.",
        ),
        encoding="utf-8",
    )
    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name="sase-1.1",
            epic_bead_id="sase-1",
            phase_bead_id="sase-1.1",
            epic_plan_ref="plans/epic.md",
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.description == (
        "Normalize the authoritative validator payload."
    )


@pytest.mark.parametrize(
    "failure",
    ["missing", "damaged", "invalid-size", "out-of-range"],
)
def test_modern_phase_plan_failures_stay_bare_and_never_expose_epic(
    tmp_path: Path,
    failure: str,
) -> None:
    plan = tmp_path / "plans" / "epic.md"
    if failure == "damaged":
        plan.parent.mkdir(parents=True)
        plan.write_text("---\ntier: [epic\n---\n# Broken\n", encoding="utf-8")
    elif failure == "invalid-size":
        write_epic(plan)
        plan.write_text(
            plan.read_text(encoding="utf-8").replace(
                "    size: small\n",
                "    size: enormous\n",
                1,
            ),
            encoding="utf-8",
        )
    elif failure == "out-of-range":
        write_epic(plan)
    phase_bead_id = "sase-1.99" if failure == "out-of-range" else "sase-1.1"

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name=phase_bead_id,
            epic_bead_id="sase-1",
            phase_bead_id=phase_bead_id,
            epic_plan_ref="plans/epic.md",
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.role == "phase"
    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.id == phase_bead_id
    assert enrichment.phase_bead.phase_title is None
    assert enrichment.phase_bead.description is None
    assert enrichment.phase_bead.epic_title is None
    assert enrichment.phase_bead.size is None
    expected_path = (
        tmp_path / ".sase/sdd/plans/epic.md" if failure == "missing" else plan
    )
    assert enrichment.phase_bead.actual_plan_path == str(expected_path.resolve())
    assert enrichment.phase_bead.display_plan_path == "plans/epic.md"
    assert enrichment.phase_bead.plan_exists is (failure != "missing")
    assert enrichment.phase_bead.plan_readable is (failure != "missing")
    assert enrichment.associated_plan is None
