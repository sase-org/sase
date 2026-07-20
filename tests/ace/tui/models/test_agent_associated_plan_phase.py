"""Associated-plan enrichment tests for phase workers and epic roles."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
from sase.ace.tui.models.agent_associated_plan import (
    PhaseBeadSummary,
    resolve_agent_plan_enrichment,
)
from sase.agent.bead_display import BeadIssueLookupSession
from sase.bead.model import BeadTier, Issue, IssueType
from tests.ace.tui.models._agent_associated_plan_helpers import write_epic, write_plan
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_caches() -> Iterator[None]:
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


def test_modern_phase_without_plan_stays_bead_only_without_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = write_epic(tmp_path / "plans" / "epic.md")
    agent = make_agent(
        agent_name="sase-1.2",
        epic_bead_id="sase-1",
        phase_bead_id="sase-1.2",
        epic_plan_ref="plans/epic.md",
        sdd_plan_path="plans/epic.md",
        plan_committed=True,
        workspace_dir=str(tmp_path),
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("modern phase must not read beads"),
    )

    enrichment = resolve_agent_plan_enrichment(agent)

    assert enrichment.role == "phase"
    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.actual_plan_path == str(plan.resolve())
    assert enrichment.phase_bead.epic_title == "Epic phase metadata"
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_paths == (str(plan.resolve()),)


def test_legacy_phase_resolves_parent_design_but_suppresses_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = write_epic(tmp_path / "plans" / "epic.md")
    agent = make_agent(agent_name="sase-1.2", workspace_dir=str(tmp_path))
    phase = Issue(
        id="sase-1.2",
        title="Phase",
        issue_type=IssueType.PHASE,
        parent_id="sase-1",
    )
    epic = Issue(
        id="sase-1",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans/epic.md",
    )
    issues = {phase.id: phase, epic.id: epic}
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: issues.get(bead_id),
    )

    with BeadIssueLookupSession() as lookup_session:
        enrichment = resolve_agent_plan_enrichment(
            agent,
            lookup_session=lookup_session,
        )

    assert enrichment.role == "phase"
    assert enrichment.phase_bead == PhaseBeadSummary(
        id="sase-1.2",
        description="Phase `docs` in approved epic plan `plans/epic.md`.",
        actual_plan_path=str(plan.resolve()),
        display_plan_path="plans/epic.md",
        plan_exists=True,
        plan_readable=True,
        epic_title="Epic phase metadata",
    )
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())


def test_phase_pending_authored_plan_keeps_parent_bead_and_uses_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic = write_epic(tmp_path / "plans" / "parent.md")
    authored = write_plan(
        tmp_path / "archive" / "provider_update_snapshot.md",
        "Teach providers to report update context.",
    )
    agent = make_agent(
        agent_name="sase-83.1--plan",
        agent_family_role="root",
        epic_bead_id="sase-83",
        phase_bead_id="sase-83.1",
        epic_plan_ref="plans/parent.md",
        archived_plan_path=str(authored),
        # Pending phase rows still carry the parent's compatibility path and
        # commit state until their authored plan is accepted.
        sdd_plan_path="plans/parent.md",
        plan_committed=True,
        workspace_dir=str(tmp_path),
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("explicit parent must not read beads"),
    )

    enrichment = resolve_agent_plan_enrichment(agent)

    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.actual_plan_path == str(epic.resolve())
    assert enrichment.associated_plan is not None
    assert enrichment.associated_plan.actual_path == str(authored.resolve())
    assert enrichment.associated_plan.effective_tier == "plan"
    assert enrichment.associated_plan.committed is False
    assert enrichment.resolved_plan_paths == (
        str(epic.resolve()),
        str(authored.resolve()),
    )


@pytest.mark.parametrize(
    ("family_role", "plan_action"),
    [("root", "tale"), ("code", None)],
    ids=["approved-root", "coder-without-action"],
)
def test_sase_83_phase_handoff_renders_parent_bead_and_committed_tale_plan(
    tmp_path: Path,
    family_role: str,
    plan_action: str | None,
) -> None:
    epic = write_epic(tmp_path / "plans" / "agent_cli_update_awareness.md")
    archived = write_plan(
        tmp_path / "archive" / "provider_update_snapshot.md",
        "Teach providers to report update context.",
    )
    committed = write_plan(
        tmp_path / "plans" / "provider_update_snapshot.md",
        "Teach providers to report update context.",
    )
    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name=(
                "sase-83.1--code" if family_role == "code" else "sase-83.1--plan"
            ),
            agent_family_role=family_role,
            epic_bead_id="sase-83",
            phase_bead_id="sase-83.1",
            epic_plan_ref="plans/agent_cli_update_awareness.md",
            archived_plan_path=str(archived),
            sdd_plan_path="plans/provider_update_snapshot.md",
            plan_committed=True,
            plan_action=plan_action,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.actual_plan_path == str(epic.resolve())
    assert enrichment.phase_bead.epic_title == "Epic phase metadata"
    assert enrichment.associated_plan is not None
    assert enrichment.associated_plan.actual_path == str(committed.resolve())
    assert enrichment.associated_plan.authored_tier == "tale"
    assert enrichment.associated_plan.effective_tier == "tale"
    assert enrichment.associated_plan.committed is True
    assert enrichment.resolved_plan_paths == (
        str(epic.resolve()),
        str(committed.resolve()),
    )


def test_historical_phase_recovers_parent_and_keeps_authored_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic = write_epic(tmp_path / "plans" / "parent.md")
    archived = write_plan(
        tmp_path / "archive" / "authored.md",
        "Keep the phase-authored handoff visible.",
    )
    committed = write_plan(
        tmp_path / "plans" / "authored.md",
        "Keep the phase-authored handoff visible.",
    )
    phase = Issue(
        id="sase-83.1",
        title="Phase",
        issue_type=IssueType.PHASE,
        parent_id="sase-83",
    )
    parent = Issue(
        id="sase-83",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans/parent.md",
    )
    issues = {phase.id: phase, parent.id: parent}
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: issues.get(bead_id),
    )

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name="sase-83.1--code",
            agent_family_role="code",
            epic_bead_id="sase-83",
            phase_bead_id="sase-83.1",
            archived_plan_path=str(archived),
            sdd_plan_path="plans/authored.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.actual_plan_path == str(epic.resolve())
    assert enrichment.associated_plan is not None
    assert enrichment.associated_plan.actual_path == str(committed.resolve())


def test_missing_parent_store_does_not_suppress_authored_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authored = write_plan(
        tmp_path / "archive" / "authored.md",
        "Degrade BEAD without erasing PLAN.",
    )
    monkeypatch.setattr(plan_model, "_lookup_issue", lambda *_args, **_kwargs: None)

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name="sase-83.1--plan",
            agent_family_role="root",
            epic_bead_id="sase-83",
            phase_bead_id="sase-83.1",
            archived_plan_path=str(authored),
            sdd_plan_path=str(authored),
            plan_committed=False,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.description is None
    assert enrichment.phase_bead.actual_plan_path is None
    assert enrichment.associated_plan is not None
    assert enrichment.associated_plan.actual_path == str(authored.resolve())
    assert enrichment.associated_plan.effective_tier == "plan"


@pytest.mark.parametrize(
    ("epic_bead_id", "phase_bead_id", "expected_description"),
    [
        (
            "sase-1",
            "sase-1.1",
            "Normalize the authoritative validator payload.",
        ),
        (
            "sase-1",
            "sase-1.2",
            "Phase `docs` in approved epic plan `plans/epic.md`.",
        ),
        (
            "sase-42.3",
            "sase-42.3.3",
            "Phase `render` in approved epic plan `plans/epic.md`.",
        ),
    ],
    ids=["first", "middle", "nested-epic-id"],
)
def test_modern_phase_uses_validated_frontmatter_order_without_bead_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    epic_bead_id: str,
    phase_bead_id: str,
    expected_description: str,
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
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("modern phase must not read beads"),
    )

    enrichment = resolve_agent_plan_enrichment(agent)

    assert enrichment.role == "phase"
    assert enrichment.phase_bead == PhaseBeadSummary(
        id=phase_bead_id,
        description=expected_description,
        actual_plan_path=str(plan.resolve()),
        display_plan_path="plans/epic.md",
        plan_exists=True,
        plan_readable=True,
        epic_title="Epic phase metadata",
    )
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())


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


@pytest.mark.parametrize("failure", ["missing", "damaged", "out-of-range"])
def test_modern_phase_plan_failures_stay_bare_and_never_expose_epic(
    tmp_path: Path,
    failure: str,
) -> None:
    plan = tmp_path / "plans" / "epic.md"
    if failure == "damaged":
        plan.parent.mkdir(parents=True)
        plan.write_text("---\ntier: [epic\n---\n# Broken\n", encoding="utf-8")
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
    assert enrichment.phase_bead.description is None
    assert enrichment.phase_bead.epic_title is None
    assert enrichment.phase_bead.actual_plan_path == str(plan.resolve())
    assert enrichment.phase_bead.display_plan_path == "plans/epic.md"
    assert enrichment.phase_bead.plan_exists is (failure != "missing")
    assert enrichment.phase_bead.plan_readable is (failure != "missing")
    assert enrichment.associated_plan is None


@pytest.mark.parametrize(
    ("agent_name", "epic_bead_id", "expected_role"),
    [
        ("planner", "sase-1", "author"),
        ("sase-1", "sase-1", "land"),
        ("sase-1.land", None, "land"),
        ("sase-1", None, "land"),
    ],
    ids=["author", "modern-land", "legacy-dot-land", "legacy-exact-land"],
)
def test_epic_author_and_land_roles_keep_complete_plan(
    tmp_path: Path,
    agent_name: str,
    epic_bead_id: str | None,
    expected_role: str,
) -> None:
    plan = write_epic(tmp_path / "plans" / "epic.md")
    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name=agent_name,
            epic_bead_id=epic_bead_id,
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.role == expected_role
    assert enrichment.associated_plan is not None
    assert enrichment.associated_plan.actual_path == str(plan.resolve())
    assert len(enrichment.associated_plan.phases) == 4


def test_legacy_dotted_phase_defaults_to_suppressed_plan_when_unconfirmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_epic(tmp_path / "plans" / "epic.md")
    monkeypatch.setattr(plan_model, "_lookup_issue", lambda *_args, **_kwargs: None)

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name="sase-1.2",
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.role == "phase"
    assert enrichment.associated_plan is None
    assert enrichment.phase_bead is None
    assert enrichment.resolved_plan_paths == ()


def test_explicit_phase_role_recovers_missing_phase_id_without_bead_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = write_epic(tmp_path / "plans" / "epic.md")
    agent = make_agent(
        agent_name="sase-1.2",
        agent_family_role="phase",
        epic_bead_id="sase-1",
        epic_plan_ref="plans/epic.md",
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
    plan = write_epic(tmp_path / "plans" / "epic.md")

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name="phase-worker",
            agent_family_role="phase",
            epic_bead_id="sase-1",
            epic_plan_ref="plans/epic.md",
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.role == "phase"
    assert enrichment.phase_bead is None
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())
