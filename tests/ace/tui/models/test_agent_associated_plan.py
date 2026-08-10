"""Core associated-plan summary tests for Agents-tab enrichment."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
from sase.ace.tui.models.agent_associated_plan import AssociatedPlanPhaseSummary
from sase.bead.model import Issue
from tests.ace.tui.models._agent_associated_plan_helpers import (
    resolve_agent_associated_plan,
    write_epic,
    write_plan,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_caches() -> Iterator[None]:
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


def test_pending_tale_maps_to_tale_and_uses_home_shortened_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    plan = write_plan(
        home / ".sase" / "plans" / "202607" / "pending.md",
        "Deliver the pending plan",
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))

    summary = resolve_agent_associated_plan(agent)

    assert summary is not None
    assert summary.title == "Associated plan metadata"
    assert summary.goal == "Deliver the pending plan"
    assert summary.authored_tier == "tale"
    assert summary.effective_tier == "tale"
    assert summary.size == "small"
    assert not summary.size_defaulted
    assert summary.display_path == "~/.sase/plans/202607/pending.md"
    assert summary.actual_path == str(plan.resolve())
    assert summary.committed is None


def test_pending_epic_maps_to_epic(tmp_path: Path) -> None:
    plan = write_plan(tmp_path / "epic.md", "Land every phase", tier="epic")

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
    plan = write_plan(
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
    plan = write_epic(tmp_path / "epic.md")

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
            size="small",
            model=None,
        ),
        AssociatedPlanPhaseSummary(
            id="docs",
            title="Independent documentation",
            depends_on=(),
            description=None,
            size="small",
            model=None,
        ),
        AssociatedPlanPhaseSummary(
            id="render",
            title="Responsive roadmap",
            depends_on=("core", "docs"),
            description=None,
            size="medium",
            model="codex/gpt-5.6-sol",
        ),
        AssociatedPlanPhaseSummary(
            id="verify",
            title="End-to-end verification",
            depends_on=("render",),
            description=None,
            size="large",
            model=None,
        ),
    )
    with pytest.raises(FrozenInstanceError):
        summary.phases[0].title = "changed"  # type: ignore[misc]


def test_legacy_missing_phase_sizes_normalize_to_small_at_consumption(
    tmp_path: Path,
) -> None:
    plan = write_epic(tmp_path / "legacy-epic.md")
    plan.write_text(
        "\n".join(
            line
            for line in plan.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("size:")
        )
        + "\n",
        encoding="utf-8",
    )

    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    )

    assert summary is not None
    assert summary.phase_availability == "available"
    assert [phase.size for phase in summary.phases] == ["small"] * 4


def test_explicit_invalid_phase_size_keeps_all_phase_metadata_unavailable(
    tmp_path: Path,
) -> None:
    plan = write_epic(tmp_path / "invalid-size-epic.md")
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "    size: medium\n",
            "    size: enormous\n",
        ),
        encoding="utf-8",
    )

    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    )

    assert summary is not None
    assert summary.phase_availability == "unavailable"
    assert summary.phases == ()


def test_explicit_tale_survives_failed_commit_and_selects_archive(
    tmp_path: Path,
) -> None:
    archived = write_plan(tmp_path / "archive.md", "Keep the local plan")
    sdd = write_plan(tmp_path / "workspace" / "plans" / "plan.md", "SDD copy")
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
    sdd = write_plan(workspace / relative, "Ship the approved plan")
    archived = write_plan(tmp_path / "archive.md", "Archived proposal")
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
    archived = write_plan(tmp_path / "archive.md", "Archived proposal")
    sdd = write_plan(workspace / "plans" / "epic.md", "Approved epic")
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
    plan = write_plan(tmp_path / "direct.md", "Deliver the direct plan")
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


def test_returns_none_without_plan_or_bead_association() -> None:
    assert resolve_agent_associated_plan(make_agent(agent_name="utility")) is None
