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
from sase.bead.model import (
    BeadTier,
    Issue,
    IssueType,
    PhaseSize,
    TaskPlusOneEvidence,
)
from tests.ace.tui.models._agent_associated_plan_helpers import write_epic, write_plan
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_caches() -> Iterator[None]:
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


def test_modern_phase_without_authored_plan_allows_exact_note_lookup(
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
    phase = Issue(
        id="sase-1.2",
        title="Ignored bead title",
        issue_type=IssueType.PHASE,
        parent_id="stale-parent",
        notes="[2026-08-01T14:00:00Z · bryan] implementation note",
    )
    lookups: list[str] = []

    def lookup(_agent: object, bead_id: str, **_kwargs: object) -> Issue | None:
        lookups.append(bead_id)
        return phase if bead_id == phase.id else None

    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lookup,
    )

    enrichment = resolve_agent_plan_enrichment(agent)

    assert enrichment.role == "phase"
    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.actual_plan_path == str(plan.resolve())
    assert enrichment.phase_bead.phase_title == "Independent documentation"
    assert enrichment.phase_bead.epic_title == "Epic phase metadata"
    assert enrichment.phase_bead.size == "small"
    assert enrichment.phase_bead.notes == phase.notes
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_paths == (str(plan.resolve()),)
    assert lookups == [phase.id]


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
        notes=(
            "[2026-08-01T15:00:00Z · phase-agent] exact phase note\n\n"
            "[2026-08-01T15:04:00Z · reviewer] follow-up"
        ),
    )
    epic = Issue(
        id="sase-1",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans/epic.md",
        notes="parent note must not appear",
    )
    issues = {phase.id: phase, epic.id: epic}
    lookups: list[str] = []

    def lookup(_agent: object, bead_id: str, **_kwargs: object) -> Issue | None:
        lookups.append(bead_id)
        return issues.get(bead_id)

    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lookup,
    )

    with BeadIssueLookupSession() as lookup_session:
        enrichment = resolve_agent_plan_enrichment(
            agent,
            lookup_session=lookup_session,
        )

    assert enrichment.role == "phase"
    assert enrichment.phase_bead == PhaseBeadSummary(
        id="sase-1.2",
        phase_title="Independent documentation",
        description="Phase `docs` in approved epic plan `plans/epic.md`.",
        actual_plan_path=str(plan.resolve()),
        display_plan_path="plans/epic.md",
        plan_exists=True,
        plan_readable=True,
        epic_title="Epic phase metadata",
        size="small",
        notes=phase.notes,
    )
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())
    assert lookups == [phase.id, epic.id]


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
    lookups: list[str] = []

    def lookup(_agent: object, bead_id: str, **_kwargs: object) -> None:
        lookups.append(bead_id)
        return None

    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lookup,
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
    assert lookups == ["sase-83.1"]


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
    assert tuple(phase.size for phase in enrichment.associated_plan.phases) == (
        "small",
        "small",
        "medium",
        "large",
    )


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


@pytest.mark.parametrize("task_id", ("sase-task", "sase-task.4"))
def test_task_worker_resolves_to_plan_free_task_bead_lane(
    task_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Issue(
        id=task_id,
        title="Implement task surfaces",
        issue_type=IssueType.TASK,
        description="Render task metadata without reading a plan file.",
        size=PhaseSize.MEDIUM,
        notes=(
            "  [2026-08-01T14:03:00Z · alice] first note\r\n"
            "continued line\r\n\r\n"
            "[2026-08-01T14:07:00Z · bob] second note  "
        ),
        plus_one_evidence=[
            TaskPlusOneEvidence(
                timestamp="2026-08-01T15:00:00Z",
                reporter="agent.beta",
                note="Independent reproduction.",
            )
        ],
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: task if bead_id == task.id else None,
    )
    monkeypatch.setattr(
        plan_model,
        "_load_plan_metadata",
        lambda *_args, **_kwargs: pytest.fail("task agents must not read plans"),
    )

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name=task_id,
            step_type="bash",
            sdd_plan_path="plans/task-must-not-resolve.md",
        )
    )

    assert enrichment.role == "task"
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_paths == ()
    assert enrichment.bead_summary is not None
    assert enrichment.bead_summary.id == task_id
    assert enrichment.bead_summary.bead_type == "task"
    assert enrichment.bead_summary.title == task.title
    assert enrichment.bead_summary.description == task.description
    assert enrichment.bead_summary.size == "medium"
    assert enrichment.bead_summary.notes == (
        "[2026-08-01T14:03:00Z · alice] first note\n"
        "continued line\n\n"
        "[2026-08-01T14:07:00Z · bob] second note"
    )
    assert enrichment.bead_summary.plus_one_count == 1
    assert enrichment.bead_summary.plus_one_evidence == tuple(task.plus_one_evidence)
    assert enrichment.bead_summary.display_plan_path is None
