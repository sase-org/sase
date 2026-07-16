"""Associated-plan summary and cache tests for Agents-tab enrichment."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import FrozenInstanceError
import os
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
from sase.ace.tui.models.agent_associated_plan import (
    AssociatedPlanPhaseSummary,
    AssociatedPlanSummary,
    resolve_agent_plan_enrichment,
)
from sase.ace.tui.models.agent import Agent
from sase.agent.bead_display import BeadIssueLookupSession
from sase.bead.model import BeadTier, Issue, IssueType
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_caches() -> Iterator[None]:
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


def _write_plan(path: Path, goal: str, *, tier: str | None = "tale") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tier_line = f"tier: {tier}\n" if tier is not None else ""
    path.write_text(
        f"---\n{tier_line}goal: {goal!r}\n---\n# Plan\n",
        encoding="utf-8",
    )
    return path


def _write_epic(path: Path, goal: str = "Deliver every authored phase") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "tier: epic\n"
        "title: Epic phase metadata\n"
        f"goal: {goal!r}\n"
        "phases:\n"
        "  - id: core\n"
        "    title: Canonical phase summaries\n"
        "    depends_on: []\n"
        "    description: Normalize the authoritative validator payload.\n"
        "  - id: docs\n"
        "    title: Independent documentation\n"
        "    depends_on: []\n"
        "  - id: render\n"
        "    title: Responsive roadmap\n"
        "    depends_on: [core, docs]\n"
        "    model: codex/gpt-5.6-sol\n"
        "  - id: verify\n"
        "    title: End-to-end verification\n"
        "    depends_on: [render]\n"
        "---\n"
        "# Plan\n\n"
        "Implement it.\n",
        encoding="utf-8",
    )
    return path


def resolve_agent_associated_plan(
    agent: Agent,
    *,
    lookup_session: BeadIssueLookupSession | None = None,
) -> AssociatedPlanSummary | None:
    """Return the associated-plan portion of role-aware enrichment."""
    return resolve_agent_plan_enrichment(
        agent,
        lookup_session=lookup_session,
    ).associated_plan


def test_pending_tale_maps_to_tale_and_uses_home_shortened_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    plan = _write_plan(
        home / ".sase" / "plans" / "202607" / "pending.md",
        "Deliver the pending plan",
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))

    summary = resolve_agent_associated_plan(agent)

    assert summary is not None
    assert summary.goal == "Deliver the pending plan"
    assert summary.authored_tier == "tale"
    assert summary.effective_tier == "tale"
    assert summary.display_path == "~/.sase/plans/202607/pending.md"
    assert summary.actual_path == str(plan.resolve())
    assert summary.committed is None


def test_pending_epic_maps_to_epic(tmp_path: Path) -> None:
    plan = _write_plan(tmp_path / "epic.md", "Land every phase", tier="epic")

    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    )

    assert summary is not None
    assert summary.authored_tier == "epic"
    assert summary.effective_tier == "epic"


@pytest.mark.parametrize(
    ("plan_action", "plan_committed", "authored_tier", "expected_tier"),
    [
        ("approve", None, "tale", "plan"),
        ("approve", False, "epic", "plan"),
        ("tale", None, "epic", "tale"),
        ("tale", False, "epic", "tale"),
        ("commit", None, "epic", "tale"),
        ("commit", False, "epic", "tale"),
        ("epic", None, "tale", "epic"),
        ("epic", False, "tale", "epic"),
        (None, False, "epic", "plan"),
        (None, None, "tale", "tale"),
        (None, None, "epic", "epic"),
        (None, True, None, "tale"),
        (None, None, None, None),
        ("unknown", False, "epic", None),
    ],
    ids=[
        "approve",
        "approve-failed-commit",
        "tale",
        "tale-failed-commit",
        "legacy-commit-action",
        "legacy-commit-action-failed-commit",
        "epic",
        "epic-failed-commit",
        "legacy-uncommitted",
        "authored-tale",
        "authored-epic",
        "legacy-committed-without-tier",
        "unresolved",
        "unknown-action",
    ],
)
def test_effective_tier_approval_precedence_and_compatibility(
    tmp_path: Path,
    plan_action: str | None,
    plan_committed: bool | None,
    authored_tier: str | None,
    expected_tier: str | None,
) -> None:
    plan = _write_plan(
        tmp_path / "plan.md",
        "Preserve the selected approval tier",
        tier=authored_tier,
    )

    summary = resolve_agent_associated_plan(
        make_agent(
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_action=plan_action,
            plan_committed=plan_committed,
        )
    )

    assert summary is not None
    assert summary.effective_tier == expected_tier


def test_authored_epic_phases_are_independent_of_displayed_tale_tier(
    tmp_path: Path,
) -> None:
    plan = _write_epic(tmp_path / "epic.md")

    summary = resolve_agent_associated_plan(
        make_agent(
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_committed=False,
            plan_action="tale",
        )
    )

    assert summary is not None
    assert summary.authored_tier == "epic"
    assert summary.effective_tier == "tale"
    assert summary.phase_availability == "available"
    assert summary.phases == (
        AssociatedPlanPhaseSummary(
            id="core",
            title="Canonical phase summaries",
            depends_on=(),
            description="Normalize the authoritative validator payload.",
            model=None,
        ),
        AssociatedPlanPhaseSummary(
            id="docs",
            title="Independent documentation",
            depends_on=(),
            description=None,
            model=None,
        ),
        AssociatedPlanPhaseSummary(
            id="render",
            title="Responsive roadmap",
            depends_on=("core", "docs"),
            description=None,
            model="codex/gpt-5.6-sol",
        ),
        AssociatedPlanPhaseSummary(
            id="verify",
            title="End-to-end verification",
            depends_on=("render",),
            description=None,
            model=None,
        ),
    )
    with pytest.raises(FrozenInstanceError):
        summary.phases[0].title = "changed"  # type: ignore[misc]


def test_explicit_tale_survives_failed_commit_and_selects_archive(
    tmp_path: Path,
) -> None:
    archived = _write_plan(tmp_path / "archive.md", "Keep the local plan")
    sdd = _write_plan(tmp_path / "workspace" / "plans" / "plan.md", "SDD copy")
    agent = make_agent(
        archived_plan_path=str(archived),
        sdd_plan_path=str(sdd),
        plan_path=str(archived),
        plan_committed=False,
        plan_action="tale",
        workspace_dir=str(tmp_path / "workspace"),
    )

    summary = resolve_agent_associated_plan(agent)

    assert summary is not None
    assert summary.actual_path == str(archived.resolve())
    assert summary.effective_tier == "tale"
    assert summary.committed is False


def test_committed_tale_uses_sidecar_relative_sdd_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    relative = Path("sase/repos/plans/202607/approved plan.md")
    sdd = _write_plan(workspace / relative, "Ship the approved plan")
    archived = _write_plan(tmp_path / "archive.md", "Archived proposal")
    agent = make_agent(
        archived_plan_path=str(archived),
        sdd_plan_path=relative.as_posix(),
        plan_committed=True,
        plan_action="commit",
        workspace_dir=str(workspace),
    )

    summary = resolve_agent_associated_plan(agent)

    assert summary is not None
    assert summary.actual_path == str(sdd.resolve())
    assert summary.display_path == relative.as_posix()
    assert summary.effective_tier == "tale"
    assert summary.committed is True


def test_legacy_epic_action_prefers_sdd_and_overrides_authored_tier(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    archived = _write_plan(tmp_path / "archive.md", "Archived proposal")
    sdd = _write_plan(workspace / "plans" / "epic.md", "Approved epic")
    agent = make_agent(
        archived_plan_path=str(archived),
        sdd_plan_path=str(sdd),
        plan_action="epic",
        workspace_dir=str(workspace),
    )

    summary = resolve_agent_associated_plan(agent)

    assert summary is not None
    assert summary.actual_path == str(sdd.resolve())
    assert summary.effective_tier == "epic"
    assert summary.committed is True


def test_direct_metadata_wins_before_bead_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path / "direct.md", "Deliver the direct plan")
    agent = make_agent(
        archived_plan_path=str(plan),
        plan_path=str(plan),
        epic_bead_id="sase-1",
        workspace_dir=str(tmp_path),
    )

    def unexpected_lookup(*_args: object, **_kwargs: object) -> Issue | None:
        raise AssertionError("direct plan metadata must win")

    monkeypatch.setattr(plan_model, "_lookup_issue", unexpected_lookup)

    summary = resolve_agent_associated_plan(agent)
    assert summary is not None
    assert summary.goal == "Deliver the direct plan"


def test_modern_phase_without_plan_stays_bead_only_without_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(
        agent_name="sase-1.2",
        epic_bead_id="sase-1",
        phase_bead_id="sase-1.2",
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("modern phase must not read beads"),
    )

    enrichment = resolve_agent_plan_enrichment(agent)

    assert enrichment.role == "phase"
    assert enrichment.bead_display == "sase-1.2"
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path is None


def test_legacy_phase_resolves_parent_design_but_suppresses_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path / "plans" / "epic.md", "Complete the epic")
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
    assert enrichment.bead_display == "sase-1.2"
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())


@pytest.mark.parametrize(
    ("epic_bead_id", "phase_bead_id", "expected"),
    [
        (
            "sase-1",
            "sase-1.1",
            "sase-1.1 - Normalize the authoritative validator payload.",
        ),
        (
            "sase-1",
            "sase-1.2",
            "sase-1.2 - Phase `docs` in approved epic plan `plans/epic.md`.",
        ),
        (
            "sase-42.3",
            "sase-42.3.3",
            "sase-42.3.3 - Phase `render` in approved epic plan `plans/epic.md`.",
        ),
    ],
    ids=["first", "middle", "nested-epic-id"],
)
def test_modern_phase_uses_validated_frontmatter_order_without_bead_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    epic_bead_id: str,
    phase_bead_id: str,
    expected: str,
) -> None:
    plan = _write_epic(tmp_path / "plans" / "epic.md")
    agent = make_agent(
        agent_name=phase_bead_id,
        epic_bead_id=epic_bead_id,
        phase_bead_id=phase_bead_id,
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
    assert enrichment.bead_display == expected
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())


def test_modern_phase_normalizes_multiline_description(tmp_path: Path) -> None:
    plan = _write_epic(tmp_path / "plans" / "epic.md")
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "description: Normalize the authoritative validator payload.",
            "description: >-\n      Normalize the authoritative\n      validator payload.",
        ),
        encoding="utf-8",
    )
    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name="sase-1.1",
            epic_bead_id="sase-1",
            phase_bead_id="sase-1.1",
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.bead_display == (
        "sase-1.1 - Normalize the authoritative validator payload."
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
        _write_epic(plan)
    phase_bead_id = "sase-1.99" if failure == "out-of-range" else "sase-1.1"

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name=phase_bead_id,
            epic_bead_id="sase-1",
            phase_bead_id=phase_bead_id,
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.role == "phase"
    assert enrichment.bead_display == phase_bead_id
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
    plan = _write_epic(tmp_path / "plans" / "epic.md")
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
    _write_epic(tmp_path / "plans" / "epic.md")
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
    assert enrichment.bead_display is None


def test_bead_tier_preserves_known_epic_fallback_on_association_cache_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic = Issue(
        id="sase-1",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans/missing.md",
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: epic if bead_id == epic.id else None,
    )
    agent = make_agent(agent_name="sase-1", workspace_dir=str(tmp_path))

    first = resolve_agent_associated_plan(agent)
    assert first is not None
    assert first.phase_availability == "unavailable"

    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("association cache was not reused"),
    )
    cached = resolve_agent_associated_plan(agent)
    assert cached is not None
    assert cached.phase_availability == "unavailable"


def test_known_missing_plan_keeps_path_and_unavailable_metadata(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing plan.md"
    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(missing), plan_path=str(missing))
    )

    assert summary is not None
    assert summary.actual_path == str(missing.resolve())
    assert summary.goal is None
    assert summary.effective_tier is None
    assert not summary.exists
    assert not summary.readable
    assert not summary.frontmatter_readable
    assert summary.phase_availability == "not-applicable"
    assert summary.phases == ()


@pytest.mark.parametrize(
    ("plan_action", "expected_tier", "expected_phase_availability"),
    [
        ("approve", "plan", "not-applicable"),
        ("commit", "tale", "not-applicable"),
        ("tale", "tale", "not-applicable"),
        ("epic", "epic", "unavailable"),
    ],
)
def test_known_missing_plan_preserves_explicit_approval_tier(
    tmp_path: Path,
    plan_action: str,
    expected_tier: str,
    expected_phase_availability: str,
) -> None:
    missing = tmp_path / "missing plan.md"

    summary = resolve_agent_associated_plan(
        make_agent(
            archived_plan_path=str(missing),
            plan_path=str(missing),
            plan_action=plan_action,
            plan_committed=False,
        )
    )

    assert summary is not None
    assert summary.effective_tier == expected_tier
    assert summary.phase_availability == expected_phase_availability
    assert summary.phases == ()


def test_damaged_frontmatter_keeps_readable_plan_association(tmp_path: Path) -> None:
    plan = tmp_path / "damaged.md"
    plan.write_text("---\ntier: [tale\n---\n# Plan\n", encoding="utf-8")

    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    )

    assert summary is not None
    assert summary.exists
    assert summary.readable
    assert not summary.frontmatter_readable
    assert summary.goal is None
    assert summary.effective_tier is None


@pytest.mark.parametrize(
    "content",
    [
        "---\ntier: [epic\n---\n# Plan\n",
        "---\n- epic\n---\n# Plan\n",
        (
            "---\ntier: epic\ntitle: Invalid epic\ngoal: Retain the goal\n"
            "phases:\n  - id: core\n    title: Valid first phase\n"
            "    depends_on: []\n  - id: later\n"
            "    title: Missing dependencies\n"
            "---\n# Plan\n"
        ),
    ],
)
def test_invalid_known_epic_never_leaks_partial_phases(
    tmp_path: Path,
    content: str,
) -> None:
    plan = tmp_path / "invalid epic.md"
    plan.write_text(content, encoding="utf-8")

    summary = resolve_agent_associated_plan(
        make_agent(
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_action="epic",
        )
    )

    assert summary is not None
    assert summary.phase_availability == "unavailable"
    assert summary.phases == ()


def test_unreadable_known_epic_never_attempts_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_epic(tmp_path / "unreadable.md")
    monkeypatch.setattr(plan_model.os, "access", lambda *_args: False)
    monkeypatch.setattr(
        plan_model,
        "validate_plan",
        lambda *_args: pytest.fail("unreadable plans must not be validated"),
    )

    summary = resolve_agent_associated_plan(
        make_agent(
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_action="epic",
        )
    )

    assert summary is not None
    assert summary.exists
    assert not summary.readable
    assert summary.phase_availability == "unavailable"
    assert summary.phases == ()


def test_readable_tale_never_renders_phases_even_with_epic_runtime_context(
    tmp_path: Path,
) -> None:
    plan = _write_plan(tmp_path / "tale.md", "Keep the compact tale")

    summary = resolve_agent_associated_plan(
        make_agent(
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_action="epic",
        )
    )

    assert summary is not None
    assert summary.effective_tier == "epic"
    assert summary.authored_tier == "tale"
    assert summary.phase_availability == "not-applicable"
    assert summary.phases == ()


def test_frontmatter_cache_reuses_parse_until_mtime_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path / "cached.md", "First goal")
    agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    real_reader = Path.read_text
    reads: list[Path] = []

    def read(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        reads.append(path)
        return real_reader(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", read)

    assert resolve_agent_associated_plan(agent).goal == "First goal"  # type: ignore[union-attr]
    assert resolve_agent_associated_plan(agent).goal == "First goal"  # type: ignore[union-attr]
    assert reads == [plan.resolve()]

    previous_mtime = plan.stat().st_mtime_ns
    _write_plan(plan, "Second goal", tier="epic")
    os.utime(
        plan,
        ns=(plan.stat().st_atime_ns, max(plan.stat().st_mtime_ns, previous_mtime + 1)),
    )

    updated = resolve_agent_associated_plan(agent)
    assert updated is not None
    assert updated.goal == "Second goal"
    assert updated.effective_tier == "epic"
    assert reads == [plan.resolve(), plan.resolve()]


def test_epic_phase_cache_reuses_validation_until_signature_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_epic(tmp_path / "cached epic.md")
    agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    real_validator = plan_model.validate_plan
    validations: list[str] = []

    def validate(content: str, tier: str):  # type: ignore[no-untyped-def]
        validations.append(content)
        return real_validator(content, tier)

    monkeypatch.setattr(plan_model, "validate_plan", validate)

    first = resolve_agent_associated_plan(agent)
    cached = resolve_agent_associated_plan(agent)
    assert first is not None
    assert cached is not None
    assert cached.phases == first.phases
    assert len(validations) == 1

    previous_mtime = plan.stat().st_mtime_ns
    updated_content = plan.read_text(encoding="utf-8").replace(
        "Responsive roadmap",
        "Responsive phase roadmap",
    )
    plan.write_text(updated_content, encoding="utf-8")
    os.utime(
        plan,
        ns=(plan.stat().st_atime_ns, max(plan.stat().st_mtime_ns, previous_mtime + 1)),
    )

    updated = resolve_agent_associated_plan(agent)
    assert updated is not None
    assert updated.phases[2].title == "Responsive phase roadmap"
    assert len(validations) == 2


def test_returns_none_without_plan_or_bead_association() -> None:
    assert resolve_agent_associated_plan(make_agent(agent_name="utility")) is None
